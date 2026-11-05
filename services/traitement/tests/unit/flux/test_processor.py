"""Le processeur de bout en bout, sans Kafka ni base : scénario, rejets, retards, pannes."""

import json

import pytest
from conformance import assert_publication

from app.flux.ports import PublishFailed
from app.flux.processor import Processor

from .support import (
    T0,
    Clock,
    FakeArchive,
    FakeEpisodes,
    FakePublisher,
    FakeStats,
    iso,
    message,
    minute_of,
    raw,
    referential,
    slot,
)


class Rig:
    def __init__(self, *, replay=False) -> None:
        self.publisher, self.archive = FakePublisher(), FakeArchive()
        self.episodes, self.stats, self.clock = FakeEpisodes(), FakeStats(), Clock()
        self.processor = Processor(
            referential(),
            self.publisher,
            self.archive,
            self.episodes,
            self.stats,
            replay=replay,
            clock=self.clock,
            utc_now=self.clock.utc_now,
        )
        self.offset = 0

    def feed(self, *payloads: bytes, partition: int = 0) -> None:
        for payload in payloads:
            self.processor.handle(payload, b"INT_01", partition, self.offset)
            self.offset += 1

    def minutes(self, speeds: list[float | None], **kw) -> None:
        for index, speed in enumerate(speeds):
            count = 0 if speed is None else 5
            self.feed(*minute_of(index, speed=speed, count=count, **kw))

    def indicators(self, size: int = 60, road: str = "ROAD_002") -> list[dict]:
        events = self.publisher.on("traffic.indicators")
        return [
            e["data"]
            for e in events
            if e["data"]["window_size_s"] == size and e["data"]["road_segment_id"] == road
        ]

    def states(self, **kw) -> list[tuple[int, str]]:
        return [
            ((json_start(d["window_start"]) - T0) // 60_000, d["congestion_state"])
            for d in self.indicators(**kw)
        ]


def json_start(text: str) -> int:
    from .support import epoch_ms

    return epoch_ms(text)


# ----------------------------------------------------------------------------- scénario


def test_une_congestion_ouvre_puis_ferme_un_episode_et_publie_des_indicateurs_conformes():
    rig = Rig()
    # ratios 0,9 puis 0,3 (4 minutes) puis 0,9 : la vitesse fluide du tronçon est de 50 km/h
    rig.minutes([45.0, 15.0, 15.0, 15.0, 15.0, 45.0, 45.0, 45.0, 45.0, 45.0])
    rig.feed(slot(9 * 60 + 70))  # filigrane à 600 s : la minute 9 est fermée

    assert rig.states() == [
        (0, "FREE_FLOW"), (1, "FREE_FLOW"), (2, "CONGESTED"), (3, "CONGESTED"),
        (4, "CONGESTED"), (5, "CONGESTED"), (6, "CONGESTED"), (7, "FREE_FLOW"),
        (8, "FREE_FLOW"), (9, "FREE_FLOW"),
    ]  # fmt: skip
    for event in rig.publisher.on("traffic.indicators"):
        assert_publication("traitement", "traffic.indicators", event)

    opened, *updates, closed = rig.episodes.records
    assert opened.started_at_ms == T0 + 60_000  # début de la première minute dégradée
    assert opened.ended_at_ms is None and opened.peak_state == "CONGESTED"
    assert closed.ended_at_ms == T0 + 5 * 60_000  # début de la série de retour au fluide
    assert closed.window_count == 4
    assert closed.min_speed_ratio == 0.3
    assert len({r.episode_id for r in rig.episodes.records}) == 1


def test_les_cinq_minutes_reprennent_l_etat_stabilise_et_la_cle_est_le_carrefour():
    rig = Rig()
    rig.minutes([15.0] * 6)
    rig.feed(slot(6 * 60 + 60))

    five = rig.indicators(size=300)
    assert [d["congestion_state"] for d in five] == ["CONGESTED"]
    assert set(rig.publisher.keys_on("traffic.indicators")) == {"INT_01"}


def test_un_troncon_qui_se_tait_donne_des_fenetres_inconnues():
    rig = Rig()
    rig.feed(*minute_of(0, speed=45.0))
    # ROAD_001 (même carrefour) continue de parler pendant cinq minutes
    for index in range(1, 6):
        rig.feed(
            *minute_of(index, sensor="SENSOR_001", road="ROAD_001"),
            *minute_of(index, sensor="SENSOR_002", road="ROAD_001"),
        )

    silent = rig.indicators(road="ROAD_002")
    # filigrane 340 s : les minutes 0 à 4 sont fermées, les quatre dernières sont vides
    assert [d["congestion_state"] for d in silent] == ["FREE_FLOW"] + ["UNKNOWN"] * 4
    assert [d["sample_count"] for d in silent] == [6, 0, 0, 0, 0]
    rig.processor.flush_stats()
    assert rig.stats.total("quality", "empty_windows") == 4


def test_une_route_vide_en_congestion_est_retenue_sans_inventer_de_ratio():
    rig = Rig()
    rig.minutes([15.0, 15.0, None, None, None, 45.0, 45.0])
    rig.feed(slot(7 * 60 + 60))

    # minute 1 : CONGESTED confirmé. Minutes 2 et 3 : route vide, ratio absent, état CONGESTED
    # -> retenues. Minute 4 : troisième fenêtre vide, retour au fluide, publiée sans ratio.
    assert {m for m, _ in rig.states()} == {0, 1, 4, 5, 6}
    assert dict(rig.states())[4] == "FREE_FLOW"
    assert rig.processor.totals["withheld_degraded_without_ratio"] == 2
    rig.processor.flush_stats()
    assert rig.stats.total("quality", "withheld_degraded_without_ratio") == 2


# ------------------------------------------------------------------------------- rejets


def test_un_message_illisible_part_sur_errors_dlq_avec_copie_et_statistique():
    rig = Rig()
    rig.feed(b"\xff\xfe pas du json")

    [event] = rig.publisher.on("errors.dlq")
    assert_publication("traitement", "errors.dlq", event)
    assert event["data"]["reason_code"] == "UNREADABLE"
    assert event["subject"] == "UNKNOWN"
    assert event["id"] == "dlq:traitement:iot.raw:0:0"
    [document] = rig.archive.documents
    assert document["_id"] == event["id"] and document["service"] == "traitement"
    rig.processor.flush_stats()
    assert rig.stats.total("rejects", "UNREADABLE") == 1


def test_un_capteur_inconnu_est_rejete_avec_son_troncon():
    rig = Rig()
    rig.feed(raw(message(sensor="SENSOR_999", road="ROAD_001", time=iso(10))))

    [event] = rig.publisher.on("errors.dlq")
    assert event["data"]["reason_code"] == "UNKNOWN_SENSOR"
    assert event["subject"] == "INT_01"
    assert event["data"]["original_key"] is None or event["data"]["original_key"] == "INT_01"


def test_un_horodatage_futur_est_rejete_sauf_en_rejeu():
    future = raw(message(sensor="SENSOR_003", road="ROAD_002", time="2026-10-20T10:00:10Z"))
    live, replay = Rig(), Rig(replay=True)
    live.feed(future)
    replay.feed(future)

    assert [e["data"]["reason_code"] for e in live.publisher.on("errors.dlq")] == [
        "FUTURE_TIMESTAMP"
    ]
    assert replay.publisher.on("errors.dlq") == []


def test_un_message_trop_tardif_est_rejete_trace_et_compte():
    rig = Rig()
    rig.feed(*[p for i, p in enumerate(minute_of(0)) if i != 1])  # le créneau de 10 s manque
    rig.feed(slot(60 + 40))  # le temps avance : la minute 0 est fermée, puis définitive à 90 s
    rig.feed(slot(60 + 41))
    before = len(rig.publisher.on("errors.dlq"))
    rig.feed(slot(10))  # arrive avec 2 minutes de retard

    [event] = rig.publisher.on("errors.dlq")[before:]
    assert event["data"]["reason_code"] == "LATE"
    assert event["data"]["intersection_id"] == "INT_01"
    assert event["data"]["original_payload"]["data"]["sensor_id"] == "SENSOR_003"
    assert event["data"]["original_key"] == "INT_01"
    assert_publication("traitement", "errors.dlq", event)
    rig.processor.flush_stats()
    assert rig.stats.total("lateness", "late_rejected") == 1
    assert rig.stats.total("rejects", "LATE") == 1


def test_un_message_tardif_toleré_corrige_la_fenetre_et_garde_son_etat():
    rig = Rig()
    rig.feed(*[p for i, p in enumerate(minute_of(0, speed=15.0)) if i != 1])
    rig.feed(slot(70, speed=15.0))  # ferme la minute 0 (filigrane 60 s)
    [first] = rig.indicators()
    assert first["sample_count"] == 5

    rig.feed(slot(10, speed=15.0))  # le créneau manquant, 0 s après la fin de fenêtre

    first_again, corrected = rig.indicators()[0], rig.indicators()[1]
    ids = [
        e["id"] for e in rig.publisher.on("traffic.indicators") if e["data"]["window_size_s"] == 60
    ]
    assert ids[0] == ids[1]  # même identifiant : l'abonné écrase la ligne
    assert corrected["sample_count"] == 6 and corrected["vehicle_count"] == 30
    assert first_again["congestion_state"] == corrected["congestion_state"]
    rig.processor.flush_stats()
    assert rig.stats.total("lateness", "late_accepted") == 1


def test_un_doublon_et_une_mesure_suspecte_sont_comptes_sans_sortie():
    rig = Rig()
    one = slot(0)
    rig.feed(one, one)
    rig.feed(
        raw(
            message(
                sensor="SENSOR_003",
                road="ROAD_002",
                time=iso(20),
                count=500,
                speed=190.0,
                status="SUSPECT",
                flags=["IMPLAUSIBLE_VALUE"],
            )
        )
    )
    rig.feed(
        raw(
            message(
                sensor="SENSOR_003",
                road="ROAD_002",
                time=iso(30),
                count=3,
                speed=None,
                status="PARTIAL",
                flags=["MISSING_SPEED"],
            )
        )
    )
    rig.processor.flush_stats()

    assert rig.stats.total("quality", "accepted") == 2  # la mesure 0 et la partielle
    assert rig.stats.total("quality", "duplicates") == 1
    assert rig.stats.total("quality", "excluded_suspect") == 1
    assert rig.stats.total("quality", "partial") == 1
    assert rig.publisher.on("errors.dlq") == []


# ------------------------------------------------------------------- inactivité et reprise


def test_sans_nouveau_message_les_fenetres_en_cours_sont_publiees_apres_15_secondes():
    rig = Rig()
    rig.feed(*minute_of(0))
    assert rig.indicators() == []

    rig.clock.monotonic = 14.9
    rig.processor.tick()
    assert rig.indicators() == []
    rig.clock.monotonic = 15.0
    rig.processor.tick()
    assert [d["sample_count"] for d in rig.indicators()] == [6]


def test_le_point_de_controle_attend_les_accuses_et_ne_depasse_pas_une_fenetre_corrigeable():
    rig = Rig()
    rig.feed(*minute_of(0))  # offsets 0 à 5
    rig.feed(slot(60))  # offset 6 : la minute 0 reste corrigeable

    offsets = rig.processor.checkpoint()

    assert rig.publisher.flushes == 1
    assert offsets == {0: 0}  # la fenêtre ouverte contient l'offset 0 : on ne valide rien au-delà

    # offsets 7 à 9 : les minutes 0 et 1 sont définitives, mais la fenêtre de cinq minutes retient 0
    rig.feed(slot(150), slot(160), slot(170))
    assert rig.processor.checkpoint() == {0: 0}

    rig.feed(slot(350))  # offset 10 : filigrane 340 s, la fenêtre [0, 300[ est définitive
    assert rig.processor.checkpoint() == {0: 10}


def test_le_point_de_controle_valide_tout_quand_rien_n_est_retenu():
    rig = Rig()
    rig.feed(b"pas du json", b"{}")

    assert rig.processor.checkpoint() == {0: 2}


# ------------------------------------------------------------------------------ pannes


def test_une_panne_du_broker_remonte_pour_ne_pas_valider_l_offset():
    rig = Rig()
    rig.publisher.fail = True

    with pytest.raises(PublishFailed):
        rig.feed(b"pas du json")


def test_une_copie_de_rejet_manquante_n_arrete_pas_le_flux():
    from app.flux.ports import StoreFailed

    rig = Rig()

    def broken(document):
        raise StoreFailed("mongo")

    rig.archive.insert = broken
    rig.feed(b"pas du json")

    assert len(rig.publisher.on("errors.dlq")) == 1


def test_des_statistiques_non_ecrites_n_arretent_pas_le_flux():
    from app.flux.ports import StoreFailed

    rig = Rig()

    def broken(*args):
        raise StoreFailed("mongo")

    rig.stats.add = broken
    rig.feed(*minute_of(0))
    rig.processor.flush_stats()  # ne lève pas


def test_les_compteurs_du_processus_sont_lisibles():
    rig = Rig()
    rig.feed(b"x", *minute_of(0))
    rig.feed(slot(80))

    assert rig.processor.totals["rejected"] == 1
    assert rig.processor.totals["rejected_unreadable"] == 1
    assert rig.processor.totals["indicators_published"] >= 1
    assert json.dumps(dict(rig.processor.totals.counters))


def test_un_rejet_qui_violerait_le_contrat_devient_un_echec_de_traitement_sans_arreter_le_flux():
    from datetime import UTC, datetime

    from app.flux.model import Rejection

    rig = Rig()
    odd = Rejection(
        "MOTIF_INCONNU", "x" * 5000, {"secret": "valeur"}, "INT_01", "k" * 500, None, None, 3, 9
    )

    rig.processor._reject(odd, datetime(2026, 10, 20, 9, 0, tzinfo=UTC))

    [event] = rig.publisher.on("errors.dlq")
    assert_publication("traitement", "errors.dlq", event)
    assert event["data"]["reason_code"] == "PROCESSING_FAILED"
    assert event["subject"] == "UNKNOWN" and event["data"]["intersection_id"] is None
    assert "MOTIF_INCONNU" not in json.dumps(event["data"]["original_payload"])
    assert rig.processor.totals["rejected_processing_failed"] == 1
    assert len(rig.archive.documents) == 1
