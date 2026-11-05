"""Le pipeline d'écriture : faits, recommandations, rejets, ordre des étapes, pannes."""

import json

import pytest
from conformance import assert_publication

from app.flux.ports import StoreFailed
from app.pipeline.facts import IndicatorFact
from app.pipeline.ports import FactFailure
from app.pipeline.processor import Pipeline
from app.pipeline.recommender import Recommender
from tests.unit.flux.support import Clock, FakeArchive, FakePublisher, FakeStats, epoch_ms

from .support import indicator, raw
from .test_recommender import APPROACH_OF, REFERENCE

T0 = epoch_ms("2026-10-20T08:00:00Z")


class Journal:
    """Appels dans l'ordre, pour prouver : base d'abord, publication ensuite, accusé, offsets."""

    def __init__(self) -> None:
        self.calls: list[str] = []


class FakeFacts:
    def __init__(self, journal: Journal) -> None:
        self.journal = journal
        self.loaded: list[IndicatorFact] = []
        self.refuse: dict[str, FactFailure | None] = {}
        self.fail = False

    def load(self, facts):
        self.journal.calls.append("load")
        if self.fail:
            raise StoreFailed("base indisponible")
        failures = []
        for fact in facts:
            if fact.road_segment_id in self.refuse:
                failures.append(FactFailure(fact, "PROCESSING_FAILED", "ligne refusée par la base"))
            else:
                self.loaded.append(fact)
        return failures


class Rig:
    def __init__(self) -> None:
        self.journal = Journal()
        self.facts = FakeFacts(self.journal)
        self.publisher = FakePublisher()
        self.archive, self.stats, self.clock = FakeArchive(), FakeStats(), Clock()
        original_publish, original_flush = self.publisher.publish, self.publisher.flush
        self.publisher.publish = lambda *a: (
            self.journal.calls.append("publish"),
            original_publish(*a),
        )[1]
        self.publisher.flush = lambda: (self.journal.calls.append("flush"), original_flush())[1]
        self.recommender = Recommender(REFERENCE)
        self.pipeline = Pipeline(
            self.facts, self.recommender, self.publisher, self.archive, self.stats,
            clock=self.clock, utc_now=self.clock.utc_now,
        )  # fmt: skip
        self.offset = 0

    def feed(self, *payloads: bytes) -> None:
        for payload in payloads:
            self.pipeline.handle(payload, b"INT_01", 0, self.offset)
            self.offset += 1


def crossing_payloads(minute=0, states=("CONGESTED", "FREE_FLOW", "FREE_FLOW", "FREE_FLOW")):
    flows = (24, 15, 20, 18)
    payloads = []
    for (segment, _), state, flow in zip(APPROACH_OF.items(), states, flows, strict=True):
        degraded = state in ("SLOW", "CONGESTED")
        payloads.append(
            raw(
                indicator(
                    segment=segment,
                    intersection="INT_01",
                    start_ms=T0 + minute * 60_000,
                    state=state,
                    flow_veh_per_min=flow,
                    vehicle_count=flow,
                    speed_ratio=0.3 if degraded else 0.9,
                    average_speed_kmh=15.0,
                )  # fmt: skip
            )
        )
    return payloads


def test_les_indicateurs_sont_ecrits_puis_la_recommandation_publiee_puis_les_offsets_rendus():
    rig = Rig()
    rig.feed(*crossing_payloads())

    offsets = rig.pipeline.checkpoint()

    assert [f.road_segment_id for f in rig.facts.loaded] == [
        "ROAD_001",
        "ROAD_002",
        "ROAD_003",
        "ROAD_004",
    ]
    assert rig.journal.calls == [
        "load",
        "publish",
        "flush",
    ]  # la base avant le bus, l'accusé avant les offsets
    [(topic, key, event)] = rig.publisher.sent
    assert (topic, key) == ("traffic.recommendations", "INT_01")
    assert_publication("traitement", "traffic.recommendations", event)
    assert offsets == {0: 4}


def test_aucun_fait_aucune_ecriture():
    rig = Rig()

    assert rig.pipeline.checkpoint() == {}
    assert rig.journal.calls == ["flush"]


def test_les_ecritures_sont_regroupees_en_une_seule_transaction_par_point_de_controle():
    rig = Rig()
    rig.feed(*crossing_payloads(0), *crossing_payloads(1))
    rig.pipeline.checkpoint()

    assert rig.journal.calls.count("load") == 1
    assert len(rig.facts.loaded) == 8


def test_un_message_illisible_part_sur_errors_dlq_sans_toucher_a_la_base():
    rig = Rig()
    rig.feed(b"pas du json")

    offsets = rig.pipeline.checkpoint()

    [(topic, _, event)] = rig.publisher.sent
    assert topic == "errors.dlq"
    assert event["data"]["source_topic"] == "traffic.indicators"
    assert event["data"]["reason_code"] == "UNREADABLE"
    assert event["id"] == "dlq:traitement:traffic.indicators:0:0"
    assert_publication("traitement", "errors.dlq", event)
    assert rig.archive.documents[0]["_id"] == event["id"]
    assert rig.facts.loaded == [] and "load" not in rig.journal.calls
    assert offsets == {0: 1}


def test_une_ligne_refusee_par_la_base_est_rejetee_avec_sa_charge_d_origine():
    rig = Rig()
    rig.facts.refuse = {"ROAD_002": None}
    payloads = crossing_payloads()
    rig.feed(*payloads)

    rig.pipeline.checkpoint()

    [rejection] = [e for t, _, e in rig.publisher.sent if t == "errors.dlq"]
    assert rejection["data"]["reason_code"] == "PROCESSING_FAILED"
    assert rejection["data"]["original_payload"] == json.loads(payloads[1])
    assert len(rig.facts.loaded) == 3
    assert rig.recommender.stats["recommended"] == 0  # le groupe n'a que trois approches


def test_les_statistiques_comptent_ce_qui_est_ecrit_et_ce_qui_est_refuse():
    rig = Rig()
    rig.feed(*crossing_payloads(), b"pas du json")
    rig.pipeline.checkpoint()

    assert rig.stats.total("quality", "facts_loaded") == 4
    assert rig.stats.total("quality", "facts_rejected") == 1
    assert rig.stats.total("quality", "rejected_unreadable") == 1
    assert rig.stats.total("quality", "reco_recommended") == 1


def test_les_statistiques_du_recommandeur_ne_sont_pas_comptees_deux_fois():
    rig = Rig()
    rig.feed(*crossing_payloads())
    rig.pipeline.checkpoint()
    rig.pipeline.checkpoint()

    assert rig.stats.total("quality", "reco_recommended") == 1


def test_les_offsets_ne_depassent_pas_un_groupe_en_attente_de_ses_voisins():
    rig = Rig()
    rig.feed(*crossing_payloads()[:2])  # offsets 0 et 1 : la recommandation attend les deux autres

    assert rig.pipeline.checkpoint() == {0: 0}

    rig.feed(*crossing_payloads()[2:])
    assert rig.pipeline.checkpoint() == {0: 4}


def test_une_panne_de_la_base_n_emet_rien_ne_valide_rien_et_garde_les_faits():
    rig = Rig()
    rig.feed(*crossing_payloads())
    rig.facts.fail = True

    with pytest.raises(StoreFailed):
        rig.pipeline.checkpoint()

    assert rig.publisher.sent == []  # aucune recommandation avant l'écriture
    rig.facts.fail = False
    rig.pipeline.checkpoint()  # le point de contrôle suivant reprend les mêmes faits
    assert len(rig.facts.loaded) == 4


def test_rejouer_les_memes_indicateurs_redonne_la_meme_recommandation():
    first, second = Rig(), Rig()
    for rig in (first, second):
        rig.feed(*crossing_payloads())
        rig.pipeline.checkpoint()

    assert first.publisher.sent == second.publisher.sent


def test_une_statistique_non_ecrite_n_arrete_pas_le_pipeline():
    rig = Rig()

    def broken(*args):
        raise StoreFailed("mongo")

    rig.stats.add = broken
    rig.feed(*crossing_payloads())
    rig.pipeline.checkpoint()  # ne lève pas

    assert len(rig.facts.loaded) == 4
