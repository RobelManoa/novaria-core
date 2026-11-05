"""Fenêtres en temps d'événement : agrégation, filigrane, retard, désordre, vides, inactivité."""

import dataclasses

import pytest

from app.flux.model import Measurement
from app.flux.windows import WindowEngine

from .support import epoch_ms

T0 = epoch_ms("2026-10-20T08:00:00Z")  # aligné sur 5 minutes


def meas(
    *,
    start_s: float = 0,
    sensor: str = "SENSOR_001",
    road: str = "ROAD_001",
    inter: str = "INT_01",
    run: str = "r1",
    interval: int = 10,
    count: int = 4,
    speed: float | None = 40.0,
    occ: float | None = 0.3,
    queue: float | None = None,
    status: str = "VALID",
    ident: str | None = None,
) -> Measurement:
    time_ms = T0 + int(start_s * 1000) + interval * 1000
    return Measurement(
        id=ident or f"{run}:{sensor}:{time_ms}",
        run_id=run,
        source_type="SIMULATED",
        scenario_id=None,
        seed=None,
        dataset_id=None,
        sensor_id=sensor,
        road_segment_id=road,
        intersection_id=inter,
        time_ms=time_ms,
        interval_s=interval,
        vehicle_count=count,
        speed_kmh=speed,
        occupancy_rate=occ,
        queue_length_m=queue,
        status=status,
        flags=(),
        correlation_id=None,
    )


def feed(engine: WindowEngine, *items: Measurement, now: float = 0.0):
    """Ajoute les mesures dans l'ordre et rend toutes les émissions."""
    out = []
    for item in items:
        out.extend(engine.add(item, now).emissions)
    return out


def of(emissions, size=60, road="ROAD_001"):
    return [e for e in emissions if e.window.size_s == size and e.window.road_segment_id == road]


def starts(emissions) -> list[float]:
    return [(e.window.start_ms - T0) / 1000 for e in emissions]


def minute(road="ROAD_001", **kw):
    """Six mesures de 10 s qui remplissent la première minute d'un capteur."""
    return [meas(start_s=10 * i, road=road, **kw) for i in range(6)]


# ------------------------------------------------------------------------------ agrégation


def test_agrege_une_fenetre_d_une_minute():
    engine = WindowEngine()
    items = [
        meas(start_s=0, count=10, speed=20.0, occ=0.2, queue=5.0),
        meas(start_s=10, count=30, speed=40.0, occ=0.4, queue=12.5),
    ]
    feed(engine, *items)
    closed = engine.add(meas(start_s=70), 0.0).emissions

    window = of(closed)[0].window
    assert window.vehicle_count == 40
    assert window.sample_count == 2
    # moyenne pondérée par les véhicules : (10 × 20 + 30 × 40) ÷ 40, et non la moyenne simple 30
    assert window.average_speed_kmh == pytest.approx((10 * 20 + 30 * 40) / 40)
    assert window.occupancy_rate == pytest.approx((0.2 + 0.4) / 2)
    assert window.max_queue_length_m == 12.5


def test_une_fenetre_sans_vehicule_n_a_pas_de_vitesse():
    engine = WindowEngine()
    feed(engine, meas(start_s=0, count=0, speed=None, occ=0.0))
    window = of(engine.add(meas(start_s=70), 0.0).emissions)[0].window

    assert window.vehicle_count == 0
    assert window.average_speed_kmh is None
    assert window.sample_count == 1


def test_une_mesure_partielle_compte_mais_ne_pese_pas_dans_la_vitesse():
    engine = WindowEngine()
    feed(
        engine,
        meas(start_s=0, count=10, speed=30.0),
        meas(start_s=10, count=50, speed=None, status="PARTIAL"),
        meas(start_s=20, count=5, speed=40.0, occ=None, status="PARTIAL"),
    )
    window = of(engine.add(meas(start_s=70), 0.0).emissions)[0].window

    assert window.vehicle_count == 65
    assert window.sample_count == 3
    assert window.average_speed_kmh == pytest.approx((10 * 30 + 5 * 40) / 15)
    assert window.occupancy_rate == pytest.approx(0.3)  # deux valeurs sur trois


def test_sans_aucune_occupation_ni_file_les_champs_restent_nuls():
    engine = WindowEngine()
    feed(engine, meas(start_s=0, occ=None, queue=None, status="PARTIAL"))
    window = of(engine.add(meas(start_s=70), 0.0).emissions)[0].window

    assert window.occupancy_rate is None
    assert window.max_queue_length_m is None


def test_une_mesure_suspecte_est_exclue_mais_fait_avancer_le_temps():
    engine = WindowEngine()
    feed(engine, meas(start_s=0, count=10, speed=40.0))
    result = engine.add(meas(start_s=70, status="SUSPECT", count=500, speed=190.0), 0.0)

    assert result.verdict == "EXCLUDED"
    window = of(result.emissions)[0].window  # la mesure suspecte a fait avancer le filigrane
    assert (window.vehicle_count, window.sample_count) == (10, 1)
    assert engine.stats["excluded"] == 1


def test_un_doublon_est_ignore_et_compte():
    engine = WindowEngine()
    first = meas(start_s=0, count=7)
    assert engine.add(first, 0.0).verdict == "ACCEPTED"
    assert engine.add(first, 0.0).verdict == "DUPLICATE"

    window = of(engine.add(meas(start_s=70), 0.0).emissions)[0].window
    assert (window.vehicle_count, window.sample_count) == (7, 1)
    assert engine.stats["duplicates"] == 1


def test_une_mesure_va_dans_la_fenetre_qui_contient_son_debut():
    engine = WindowEngine()
    # début à 55 s, intervalle de 10 s : la fin (65 s) tombe dans la minute suivante, le début non
    feed(engine, meas(start_s=55, count=3))
    emissions = engine.add(meas(start_s=140), 0.0).emissions

    by_start = {e.window.start_ms - T0: e.window for e in of(emissions)}
    assert by_start[0].vehicle_count == 3
    assert by_start[60_000].vehicle_count == 0


# ------------------------------------------------------------------------------- fermeture


def test_la_fenetre_se_ferme_quand_le_filigrane_atteint_sa_fin():
    engine = WindowEngine()
    assert feed(engine, meas(start_s=0)) == []
    # filigrane = début le plus grand − 10 s : 60 s exactement ferme la minute, 59 s ne la ferme pas
    assert of(engine.add(meas(start_s=69), 0.0).emissions) == []
    closed = of(engine.add(meas(start_s=70), 0.0).emissions)
    assert starts(closed) == [0.0]
    assert closed[0].revision == 0


def test_une_fenetre_est_publiee_une_seule_fois():
    engine = WindowEngine()
    emissions = feed(engine, *minute(), meas(start_s=70), meas(start_s=80), meas(start_s=90))

    assert starts(of(emissions)) == [0.0]


def test_la_fenetre_de_cinq_minutes_se_ferme_avec_la_cinquieme_minute():
    engine = WindowEngine()
    emissions = feed(
        engine, meas(start_s=0), meas(start_s=290), meas(start_s=300), meas(start_s=309)
    )
    assert of(emissions, size=300) == []

    closed = engine.add(meas(start_s=310), 0.0).emissions
    assert starts(of(closed, size=300)) == [0.0]


def test_les_fenetres_sortent_par_fin_croissante_puis_par_taille():
    engine = WindowEngine()
    feed(engine, meas(start_s=0))
    emissions = engine.add(meas(start_s=400), 0.0).emissions  # ferme 5 minutes d'un coup

    order = [(e.window.end_ms, e.window.size_s) for e in emissions]
    assert order == sorted(order)
    assert (T0 + 300_000, 300) in order
    # la minute qui finit en même temps que la fenêtre de cinq minutes passe avant elle
    assert order.index((T0 + 300_000, 60)) < order.index((T0 + 300_000, 300))


def test_le_desordre_dans_la_tolerance_est_range_dans_la_bonne_fenetre():
    engine = WindowEngine()
    # la mesure de 50 s suit celle de 62 s : le filigrane est à 52 s, la minute reste ouverte
    emissions = feed(
        engine, meas(start_s=0, count=1), meas(start_s=62, count=1), meas(start_s=50, count=9)
    )
    assert emissions == []

    closed = of(engine.add(meas(start_s=75), 0.0).emissions)
    assert closed[0].window.vehicle_count == 10


# --------------------------------------------------------------------------------- retard


def test_un_message_tardif_dans_la_tolerance_met_a_jour_la_fenetre_deja_publiee():
    engine = WindowEngine()
    feed(engine, meas(start_s=0, count=10), meas(start_s=70))  # minute 0 publiée, filigrane 60 s
    result = engine.add(meas(start_s=20, count=5), 0.0)  # fin de fenêtre à 60 s, retard 0 s

    assert result.verdict == "ACCEPTED"
    update = of(result.emissions)
    assert starts(update) == [0.0]
    assert update[0].revision == 1
    assert update[0].window.vehicle_count == 15
    assert engine.stats["updated"] >= 1


def test_la_mise_a_jour_garde_l_etat_deja_publie():
    engine = WindowEngine()
    feed(engine, meas(start_s=0), meas(start_s=70))
    published = of(engine.add(meas(start_s=75), 0.0).emissions)  # rien de neuf
    assert published == []
    window = engine._runs["r1"].segments["ROAD_001"].windows[(60, T0)]
    window.state = "SLOW"

    update = of(engine.add(meas(start_s=20), 0.0).emissions)[0]
    assert update.window.state == "SLOW"


def test_la_fenetre_est_definitive_au_filigrane_fin_plus_30_secondes():
    engine = WindowEngine()
    feed(engine, meas(start_s=0))
    # le filigrane atteint 89 s : fin de fenêtre (60 s) + 30 s = 90 s, pas encore définitive
    engine.add(meas(start_s=99), 0.0)
    assert engine.add(meas(start_s=30), 0.0).verdict == "ACCEPTED"

    engine.add(meas(start_s=100), 0.0)  # filigrane 90 s : la minute 0 est définitive
    result = engine.add(meas(start_s=30, sensor="SENSOR_002"), 0.0)

    assert result.verdict == "LATE"
    assert result.emissions == []
    assert result.behind_ms == 30_000
    assert engine.stats["late"] == 1


def test_un_message_tardif_refuse_ne_change_aucune_fenetre():
    engine = WindowEngine()
    feed(engine, meas(start_s=0, count=10), meas(start_s=100))
    before = engine._runs["r1"].segments["ROAD_001"].windows[(300, T0)].vehicle_count

    engine.add(meas(start_s=5, count=99, sensor="SENSOR_002"), 0.0)

    assert engine._runs["r1"].segments["ROAD_001"].windows[(300, T0)].vehicle_count == before


def test_un_message_tardif_pour_la_minute_est_refuse_aussi_pour_les_cinq_minutes():
    engine = WindowEngine()
    emissions = feed(engine, meas(start_s=0, count=10), meas(start_s=100))
    assert engine.add(meas(start_s=5, count=99, sensor="SENSOR_002"), 0.0).verdict == "LATE"
    emissions += engine.add(meas(start_s=400), 0.0).emissions

    five = of(emissions, size=300)[0].window
    one = of(emissions, size=60)[0].window
    assert one.start_ms == T0
    # 10 véhicules à 0 s ; les 4 de la mesure à 100 s comptent dans les cinq minutes, pas les 99
    assert (one.vehicle_count, five.vehicle_count) == (10, 10 + 4)


# ------------------------------------------------------------------- fenêtres vides, portée


def test_un_troncon_muet_produit_des_fenetres_vides():
    engine = WindowEngine()
    # ROAD_002 parle à 0 s puis se tait ; ROAD_001 continue et fait avancer le filigrane
    feed(engine, meas(start_s=0, road="ROAD_002", sensor="SENSOR_003"))
    emissions = feed(engine, *[meas(start_s=s) for s in range(0, 200, 10)])

    silent = of(emissions, road="ROAD_002")
    # début le plus grand 190 s, filigrane 180 s : les minutes 0, 60 et 120 sont fermées
    assert starts(silent) == [0.0, 60.0, 120.0]
    assert [e.window.sample_count for e in silent] == [1, 0, 0]
    assert engine.stats["empty_windows"] == 2
    assert silent[1].window.road_segment_id == "ROAD_002"
    assert silent[1].window.provenance["run_id"] == "r1"


def test_une_fenetre_vide_garde_l_identite_du_troncon_meme_apres_elagage():
    engine = WindowEngine()
    feed(engine, meas(start_s=0, road="ROAD_002", sensor="SENSOR_003"))
    # 15 minutes plus tard, les fenêtres du tronçon muet ont toutes été élaguées (définitives)
    emissions = feed(engine, *[meas(start_s=s) for s in range(0, 900, 10)])

    silent = of(emissions, road="ROAD_002")
    assert len(silent) == 14  # minutes 0 à 13 : le filigrane est à 890 s
    assert {(e.window.run_id, e.window.intersection_id) for e in silent} == {("r1", "INT_01")}
    assert all(e.window.provenance["run_id"] == "r1" for e in silent)
    assert not [e for e in emissions if e.window.road_segment_id == ""]


def test_le_filigrane_est_propre_a_chaque_carrefour():
    engine = WindowEngine()
    feed(engine, meas(start_s=0, inter="INT_01"))
    other = engine.add(meas(start_s=500, inter="INT_02", road="ROAD_009", sensor="SENSOR_009"), 0.0)

    assert other.emissions == []  # le temps de INT_02 ne ferme rien chez INT_01


def test_les_runs_sont_independants():
    engine = WindowEngine()
    feed(engine, meas(start_s=0, run="a"))
    assert (
        engine.add(meas(start_s=500, run="b"), 0.0).emissions == []
    )  # le temps de b ferme rien chez a
    # le temps de a n'a pas bougé : une mesure de a à 5 s est reçue sans retard
    assert engine.add(meas(start_s=5, run="a", sensor="SENSOR_002"), 0.0).verdict == "ACCEPTED"


def test_une_mesure_ancienne_arrivant_en_premier_n_est_pas_perdue():
    engine = WindowEngine()
    feed(engine, meas(start_s=65, count=2))  # première vue : minute 1
    feed(engine, meas(start_s=50, count=3))  # minute 0, en désordre, dans la tolérance
    emissions = engine.add(meas(start_s=140), 0.0).emissions

    by_start = {e.window.start_ms - T0: e.window for e in of(emissions)}
    assert by_start[0].vehicle_count == 3
    assert by_start[60_000].vehicle_count == 2


def test_un_grand_trou_ne_cree_pas_un_flot_de_fenetres_vides():
    engine = WindowEngine(max_catchup=10)
    feed(engine, meas(start_s=0))
    emissions = engine.add(meas(start_s=3 * 86400), 0.0).emissions  # trois jours plus tard

    assert len(of(emissions)) <= 11
    assert engine.stats["skipped_windows"] > 4000


# ---------------------------------------------------------------------------- inactivité


def test_sans_message_les_fenetres_en_cours_sont_publiees_apres_15_secondes():
    engine = WindowEngine()
    feed(engine, meas(start_s=0, count=6), now=100.0)

    assert engine.flush_idle(114.9).emissions == []
    flushed = engine.flush_idle(115.0).emissions
    assert starts(of(flushed)) == [0.0]
    assert of(flushed)[0].window.vehicle_count == 6
    assert starts(of(flushed, size=300)) == [0.0]


def test_le_vidage_par_inactivite_ne_publie_pas_deux_fois():
    engine = WindowEngine()
    feed(engine, meas(start_s=0), now=0.0)
    assert engine.flush_idle(20.0).emissions
    assert engine.flush_idle(40.0).emissions == []


def test_un_message_apres_le_vidage_met_la_fenetre_a_jour():
    engine = WindowEngine()
    feed(engine, meas(start_s=0, count=6), now=0.0)
    engine.flush_idle(20.0)

    result = engine.add(meas(start_s=10, count=4), 21.0)

    update = of(result.emissions)
    assert [e.revision for e in update] == [1]
    assert update[0].window.vehicle_count == 10


def test_un_nouveau_message_apres_le_vidage_permet_un_second_vidage():
    engine = WindowEngine()
    feed(engine, meas(start_s=0), now=0.0)
    assert starts(of(engine.flush_idle(20.0).emissions)) == [0.0]

    feed(engine, meas(start_s=70), now=30.0)  # ferme la minute 0 de nouveau (déjà publiée)
    flushed = of(engine.flush_idle(50.0).emissions)

    assert starts(flushed) == [60.0]


def test_la_memoire_reste_bornee_sur_un_long_flux():
    engine = WindowEngine()
    feed(engine, *[meas(start_s=s) for s in range(0, 3600, 10)])

    track = engine._runs["r1"].segments["ROAD_001"]
    # seules les fenêtres encore corrigeables restent : une minute close, quelques-unes ouvertes
    assert len(track.windows) <= 8


def test_l_etat_d_un_run_inactif_est_libere_apres_dix_minutes():
    engine = WindowEngine()
    feed(engine, meas(start_s=0), now=0.0)
    flush = engine.flush_idle(600.0)

    assert flush.retired == ["r1"]
    assert engine._runs == {}


def test_un_run_encore_actif_n_est_pas_libere():
    engine = WindowEngine()
    feed(engine, meas(start_s=0), now=0.0)
    assert engine.flush_idle(599.0).retired == []


# ------------------------------------------------------------------------------- offsets


def at_offset(item: Measurement, partition: int, offset: int) -> Measurement:
    return dataclasses.replace(item, partition=partition, offset=offset)


def test_les_offsets_retenus_sont_les_plus_petits_des_fenetres_encore_corrigeables():
    engine = WindowEngine()
    engine.add(at_offset(meas(start_s=0), 0, 10), 0.0)
    engine.add(at_offset(meas(start_s=10), 0, 11), 0.0)
    engine.add(at_offset(meas(start_s=20, inter="INT_02", road="ROAD_009"), 1, 4), 0.0)

    assert engine.retained_offsets() == {0: 10, 1: 4}


def test_les_offsets_ne_retiennent_plus_une_fenetre_definitive():
    engine = WindowEngine()
    engine.add(at_offset(meas(start_s=0), 0, 10), 0.0)
    assert engine.retained_offsets() == {0: 10}

    # filigrane 90 s : la minute 0 est fermée et définitive ; la cinq minutes la retient encore
    engine.add(at_offset(meas(start_s=100), 0, 20), 0.0)
    assert engine.retained_offsets() == {0: 10}

    # filigrane 330 s : la cinq minutes [0, 300[ est définitive à son tour ; reste l'offset 30
    engine.add(at_offset(meas(start_s=340), 0, 30), 0.0)
    assert engine.retained_offsets() == {0: 30}


def test_une_mesure_sans_offset_ne_retient_rien():
    engine = WindowEngine()
    engine.add(meas(start_s=0), 0.0)

    assert engine.retained_offsets() == {}
