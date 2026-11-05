"""Le flux contre un vrai Kafka, un vrai PostgreSQL et un vrai MongoDB (MS-09).

Les comptes sont ceux du service (`svc_traitement`) : les tests prouvent aussi que leurs droits de
production suffisent. Lancer : `python3 scripts/dev/dev.py test-integration --service flux`.
"""

import json
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from app.flux.adapters.mongo_store import MongoStore
from app.flux.adapters.warehouse import Warehouse
from app.flux.episodes import EpisodeRecord
from app.flux.ports import StoreFailed
from tests.integration.scenario import RUN as SCENARIO_RUN
from tests.integration.scenario import generate as scenario_messages
from tests.integration.stack_flux import (
    MONGO_URL,
    POSTGRES_READ_URL,
    POSTGRES_URL,
    Probe,
    admin_engine,
    admin_mongo,
    clean_traces,
    clean_warehouse,
    committed_offsets,
    day_start,
    flux_worker,
    needs_flux,
    pipeline_worker,
    produce,
    produce_timed,
    read_topic,
    stats_total,
    wait_for,
)
from tests.unit.flux.support import message, raw

pytestmark = needs_flux


def assert_publication(topic: str, event: dict) -> None:
    """Conformité au contrat du sujet, comme le fait la matrice `contracts/topics.json`."""
    from conformance import (
        assert_publication as check,  # `contracts/` est ajouté au chemin par stack_flux
    )

    check("traitement", topic, event)


def at(day: int, seconds: float) -> str:
    moment = day_start(day) + timedelta(seconds=seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def ms(day: int, seconds: float) -> int:
    return int((day_start(day) + timedelta(seconds=seconds)).timestamp() * 1000)


# ----------------------------------------------------------------------------- référentiel


def test_le_referentiel_est_lu_dans_l_entrepot_avec_le_compte_du_service():
    referential = Warehouse(POSTGRES_URL).load_referential()

    sensor = referential.sensors["SENSOR_001"]
    assert (sensor.road_segment_id, sensor.intersection_id, sensor.reporting_interval_s) == (
        "ROAD_001",
        "INT_01",
        10,
    )
    assert referential.segments["ROAD_001"].free_flow_speed_kmh == 50.0
    assert referential.expected_samples("ROAD_001", 60) == 6


# --------------------------------------------------------------------------------- épisodes


def test_les_episodes_s_ecrivent_et_se_rejouent_sans_doublon_ni_retour_en_arriere():
    day, run_id = 11, f"it-ep-{uuid.uuid4().hex[:8]}"
    warehouse = Warehouse(POSTGRES_URL)
    opened = EpisodeRecord(
        episode_id=str(uuid.uuid4()),
        run_id=run_id,
        source_type="SIMULATED",
        road_segment_id="ROAD_001",
        started_at_ms=ms(day, 60),
        ended_at_ms=None,
        peak_state="SLOW",
        min_speed_ratio=0.5,
        window_count=2,
    )
    grown = replace(opened, peak_state="CONGESTED", min_speed_ratio=0.3, window_count=6)
    # À la clôture, le compte devient définitif (4), plus petit que le compte provisoire (6).
    closed = replace(grown, ended_at_ms=ms(day, 300), window_count=4)
    try:
        for record in (opened, grown, closed, opened, grown):  # les deux derniers : un rejeu
            warehouse.upsert(record)

        with admin_engine().connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT ended_at, peak_state, min_speed_ratio, window_count "
                    "FROM dwh.fact_congestion_episode WHERE run_id = :run"
                ),
                {"run": run_id},
            ).all()
        assert len(rows) == 1
        ended_at, peak, ratio, count = rows[0]
        assert ended_at.timestamp() * 1000 == ms(day, 300)  # le rejeu ne l'a pas rouvert
        assert (peak, float(ratio), count) == ("CONGESTED", 0.3, 4)  # définitif, rien ne le rouvre
    finally:
        clean_traces([run_id], day)


def test_un_episode_sur_un_troncon_inconnu_est_refuse():
    record = EpisodeRecord(
        str(uuid.uuid4()), "it-inconnu", "SIMULATED", "ROAD_999", ms(11, 0), None, "SLOW", 0.5, 2
    )

    with pytest.raises(StoreFailed):
        Warehouse(POSTGRES_URL).upsert(record)


# ----------------------------------------------------------------------------------- MongoDB


def test_les_rejets_et_les_statistiques_s_ecrivent_avec_les_droits_du_service():
    day, run_id = 12, f"it-mongo-{uuid.uuid4().hex[:8]}"
    store = MongoStore(MONGO_URL)
    document = {
        "_id": f"dlq:traitement:iot.raw:7:{run_id}",
        "source_topic": "iot.raw",
        "rejected_at": day_start(day),
        "reason": "essai",
        "reason_code": "LATE",
        "service": "traitement",
        "attempts": 1,
        "original_key": None,
        "intersection_id": None,
        "correlation_id": "corr-1",
        "event_id": f"dlq:{run_id}",
        "original_payload": {"data": {"provenance": {"run_id": run_id}}},
    }
    try:
        store.insert(document)
        store.insert(document)  # le rejeu : ignoré
        store.insert(
            {**document, "_id": document["_id"] + "-nul", "original_payload": {"a\x00b": 1}}
        )
        store.add("quality", day_start(day), "ROAD_001", {"accepted": 2})
        store.add("quality", day_start(day), "ROAD_001", {"accepted": 3, "duplicates": 1})
        store.add("rejects", day_start(day), None, {"UNREADABLE": 1, "total": 1})

        base = admin_mongo()
        assert base.rejects.count_documents({"event_id": f"dlq:{run_id}"}) == 2
        fallback = base.rejects.find_one({"_id": document["_id"] + "-nul"})
        assert isinstance(fallback["original_payload"], str)  # BSON refuse la clé : gardée en texte
        quality = base.processing_stats.find_one(
            {"kind": "quality", "window_start": day_start(day), "road_segment_id": "ROAD_001"}
        )
        assert quality["values"] == {"accepted": 5, "duplicates": 1}
        general = base.processing_stats.find_one(
            {"kind": "rejects", "window_start": day_start(day)}
        )
        assert "road_segment_id" not in general and general["values"]["total"] == 1
    finally:
        clean_traces([run_id], day)


# ---------------------------------------------------------------------------- de bout en bout


def slot(day, run, start_s, speed, count=5, sensor="SENSOR_001", road="ROAD_001"):
    return raw(
        message(
            sensor=sensor,
            road=road,
            time=at(day, start_s + 10),
            count=count,
            speed=speed if count else None,
            run=run,
        )
    )


def test_un_scenario_de_congestion_traverse_kafka_les_bases_et_se_rejoue_sans_doublon():
    day, run_id = 15, f"it-e2e-{uuid.uuid4().hex[:8]}"
    speeds = [45.0, 15.0, 15.0, 15.0, 15.0, 45.0, 45.0, 45.0, 45.0, 45.0]  # ratios 0,9 puis 0,3
    key = b"INT_01"
    items: list[tuple[bytes | None, bytes]] = [(key, b"pas du json " + run_id.encode())]
    items.append(
        (key, raw(message(sensor="SENSOR_999", road="ROAD_001", time=at(day, 30), run=run_id)))
    )
    first_of_minute: dict[int, int] = {}
    for minute, speed in enumerate(speeds):
        first_of_minute[minute] = len(items)
        for i in range(6):
            items.append((key, slot(day, run_id, minute * 60 + 10 * i, speed)))
            if minute == 0 and i == 0:  # doublon reçu aussitôt : la fenêtre est encore ouverte
                items.append((key, slot(day, run_id, 0, speed)))
    items.append((key, slot(day, run_id, 9 * 60 + 70, 45.0)))  # le temps avance : minute 9 fermée
    items.append((key, slot(day, run_id, 5, 45.0)))  # id nouveau, minute 0 : trop tardive
    future = message(sensor="SENSOR_001", road="ROAD_001", time="2030-01-01T00:00:10Z", run=run_id)
    items.append((key, raw(future)))

    clean_traces([run_id], day)
    try:
        with flux_worker() as worker:
            group = worker.group
            where = produce("iot.raw", items)
            partition = where[0][0]
            expected_commit = where[first_of_minute[5]][1]

            def mine(event: dict) -> bool:
                return event["data"]["provenance"]["run_id"] == run_id

            def indicators() -> list[dict]:
                return [e for e in read_topic("traffic.indicators") if mine(e)]

            wait_for(
                lambda: len([e for e in indicators() if e["data"]["window_size_s"] == 60]) >= 10,
                what="les 10 indicateurs d'une minute",
                worker=worker,
            )
            wait_for(
                lambda: committed_offsets(group, "iot.raw").get(partition) == expected_commit,
                what="la validation de l'offset sûr",
                worker=worker,
            )

        one_minute = sorted(
            (e["data"] for e in indicators() if e["data"]["window_size_s"] == 60),
            key=lambda d: d["window_start"],
        )
        assert [d["congestion_state"] for d in one_minute] == (
            ["FREE_FLOW"] * 2 + ["CONGESTED"] * 5 + ["FREE_FLOW"] * 3
        )
        assert {d["sample_count"] for d in one_minute} == {6}
        for event in indicators():
            assert_publication("traffic.indicators", event)

        rejected = [
            e for e in read_topic("errors.dlq") if run_id in str(e["data"]["original_payload"])
        ]
        assert sorted(e["data"]["reason_code"] for e in rejected) == [
            "FUTURE_TIMESTAMP",
            "LATE",
            "UNKNOWN_SENSOR",
            "UNREADABLE",
        ]
        for event in rejected:
            assert_publication("errors.dlq", event)

        with admin_engine().connect() as connection:
            episodes = connection.execute(
                text(
                    "SELECT started_at, ended_at, peak_state, min_speed_ratio, window_count "
                    "FROM dwh.fact_congestion_episode WHERE run_id = :run"
                ),
                {"run": run_id},
            ).all()
        assert len(episodes) == 1
        started, ended, peak, ratio, count = episodes[0]
        assert started.timestamp() * 1000 == ms(day, 60)  # première minute dégradée
        assert ended.timestamp() * 1000 == ms(day, 300)  # début du retour stable au fluide
        assert (peak, float(ratio), count) == ("CONGESTED", 0.3, 4)

        base = admin_mongo()
        archived = list(base.rejects.find({"service": "traitement"}))
        mine_archived = [d for d in archived if run_id in str(d["original_payload"])]
        assert sorted(d["reason_code"] for d in mine_archived) == [
            "FUTURE_TIMESTAMP",
            "LATE",
            "UNKNOWN_SENSOR",
            "UNREADABLE",
        ]
        stats = {
            (d["kind"], d["window_start"]): d["values"]
            for d in base.processing_stats.find({"road_segment_id": "ROAD_001"})
            if day_start(day)
            <= d["window_start"].replace(tzinfo=day_start(day).tzinfo)
            < day_start(day) + timedelta(hours=1)
        }
        first = day_start(day)
        quality = stats[("quality", first.replace(tzinfo=None))]
        assert quality["accepted"] == 6 and quality["duplicates"] == 1
        assert stats[("lateness", first.replace(tzinfo=None))]["late_rejected"] == 1

        # Redémarrage : le service relit depuis l'offset validé. Les puits sont idempotents.
        before = len(mine_archived)
        published = len(indicators())
        with flux_worker(group=group) as second:
            wait_for(
                lambda: len(indicators()) > published,
                what="la republication après redémarrage",
                worker=second,
            )
            wait_for(
                lambda: committed_offsets(group, "iot.raw").get(partition) == expected_commit,
                what="la validation après redémarrage",
                worker=second,
            )
        with admin_engine().connect() as connection:
            again = connection.execute(
                text(
                    "SELECT count(*), max(window_count) "
                    "FROM dwh.fact_congestion_episode WHERE run_id = :run"
                ),
                {"run": run_id},
            ).one()
        assert tuple(again) == (1, 4)
        assert (
            len(
                [
                    d
                    for d in admin_mongo().rejects.find({"service": "traitement"})
                    if run_id in str(d["original_payload"])
                ]
            )
            == before
        )
    finally:
        clean_traces([run_id], day)


def test_delai_entre_le_message_qui_ferme_la_fenetre_et_l_indicateur_publie(capsys):
    """Latence de traitement du service, hors délai de fenêtre (20 s au plus, temps d'événement)."""
    day, run_id = 16, f"it-lat-{uuid.uuid4().hex[:8]}"
    key = b"INT_01"
    clean_traces([run_id], day)
    try:
        with flux_worker() as worker:
            where = produce("iot.raw", [(key, slot(day, run_id, 10 * i, 45.0)) for i in range(6)])
            wait_for(
                lambda: committed_offsets(worker.group, "iot.raw").get(where[0][0]) is not None,
                what="le service au travail",
                worker=worker,
            )
            latencies = []
            with Probe("traffic.indicators") as probe:
                for minute in range(4):
                    closing = slot(day, run_id, minute * 60 + 70, 45.0)
                    started = produce_timed("iot.raw", key, closing)
                    event, arrived = probe.wait_for(
                        lambda e, m=minute: (
                            e["data"]["provenance"]["run_id"] == run_id
                            and e["data"]["window_size_s"] == 60
                            and e["data"]["window_start"] == at(day, m * 60)
                        ),
                        timeout_s=30,
                        worker=worker,
                    )
                    latencies.append(arrived - started)
                    produce(
                        "iot.raw",
                        [
                            (key, slot(day, run_id, (minute + 1) * 60 + 10 * i, 45.0))
                            for i in (0, 2, 3, 4, 5)  # le créneau 1 est le message fermant
                        ],
                    )
        shown = ", ".join(f"{value * 1000:.0f}" for value in latencies)
        with capsys.disabled():
            print(f"\nLatence message fermant la fenêtre -> indicateur publié (ms) : {shown}")
        assert max(latencies) < 5.0
    finally:
        clean_traces([run_id], day)


REPO = next(
    folder for folder in Path(__file__).resolve().parents if (folder / "simulator").is_dir()
)


def simulator_run(run_id: str, day: int) -> list[bytes]:
    """Un run du simulateur MS-07 avec cinq anomalies, dans l'ordre où la collecte le livrerait."""
    command = [
        sys.executable, str(REPO / "simulator" / "app.py"), "run",
        "--scenario", "incident-ponctuel", "--seed", "7", "--run-id", run_id,
        "--start", at(day, 0), "--duration", "10m", "--stdout", "--rate", "0",
        "--anomaly", "aberrante:sensor=SENSOR_003,at=+30,variant=vitesse",
        "--anomaly", "doublon:sensor=SENSOR_001,at=+20,copies=2",
        "--anomaly", "muet:sensor=SENSOR_007,at=+60,duration=5m",
        "--anomaly", "retard:sensor=SENSOR_010,at=+40,delay=45",
        "--anomaly", "retard:sensor=SENSOR_012,at=+40,delay=120",
    ]  # fmt: skip
    done = subprocess.run(command, capture_output=True, check=True, cwd=REPO)  # noqa: S603
    return [line for line in done.stdout.splitlines() if line.strip()]


def test_un_run_du_simulateur_avec_ses_anomalies_est_compte_et_trace_par_le_flux():
    """EXG-TRA-02 : tardif, aberrant, doublon et capteur muet sont comptés et tracés."""
    day, run_id = 17, f"it-sim-{uuid.uuid4().hex[:8]}"
    lines = simulator_run(run_id, day)
    messages = [json.loads(line) for line in lines]
    ids = [m["id"] for m in messages]
    duplicates = len(ids) - len(set(ids))
    suspect = sum(m["data"]["quality"]["status"] == "SUSPECT" for m in messages)
    assert (duplicates, suspect) == (2, 1)  # ce que les anomalies ont injecté

    def minute_of(message: dict) -> int:
        stamp = datetime.fromisoformat(message["time"].replace("Z", "+00:00"))
        start = stamp.timestamp() - message["data"]["interval_s"]
        return int((start - day_start(day).timestamp()) // 60)

    seen = {minute_of(m) for m in messages if m["data"]["road_segment_id"] == "ROAD_007"}
    silent = [minute for minute in range(9) if minute not in seen]  # fermées : minutes 0 à 8
    assert silent, "le scénario doit rendre ROAD_007 muet au moins une minute entière"

    clean_traces([run_id], day)
    try:
        with flux_worker() as worker:
            produce(
                "iot.raw",
                [(m["subject"].encode(), line) for m, line in zip(messages, lines, strict=True)],
            )
            accepted = len(messages) - duplicates - suspect - 1  # moins le retard refusé

            wait_for(
                lambda: stats_total("quality", "accepted", day) == accepted,
                timeout_s=90,
                what="le traitement des 1 412 messages",
                worker=worker,
            )
            wait_for(
                lambda: stats_total("lateness", "late_rejected", day) == 1,
                what="les statistiques de retard",
                worker=worker,
            )

        assert (
            stats_total("quality", "duplicates", day) == duplicates
        )  # compté, pas publié deux fois
        assert stats_total("quality", "excluded_suspect", day) == suspect  # exclu des indicateurs
        assert stats_total("lateness", "late_accepted", day) == 1  # 45 s : fenêtre corrigée
        assert stats_total("lateness", "late_rejected", day) == 1  # 120 s : refusé, tracé

        rejected = [
            e
            for e in read_topic("errors.dlq")
            if e["data"]["original_payload"] != ""
            and run_id in json.dumps(e["data"]["original_payload"])
        ]
        assert [e["data"]["reason_code"] for e in rejected] == ["LATE"]
        assert rejected[0]["data"]["original_payload"]["data"]["sensor_id"] == "SENSOR_012"
        assert_publication("errors.dlq", rejected[0])

        indicators = [
            e
            for e in read_topic("traffic.indicators")
            if e["data"]["provenance"]["run_id"] == run_id
        ]
        for event in indicators:
            assert_publication("traffic.indicators", event)
        by_window = {
            (e["data"]["road_segment_id"], e["data"]["window_start"], e["data"]["window_size_s"]): e
            for e in indicators
        }  # le dernier publié l'emporte, comme l'abonné qui écrase la ligne
        for minute in silent:
            muted = by_window[("ROAD_007", at(day, minute * 60), 60)]["data"]
            assert (muted["sample_count"], muted["congestion_state"]) == (0, "UNKNOWN")
        corrected = [e for e in indicators if e["data"]["road_segment_id"] == "ROAD_010"]
        ids_corrected = [e["id"] for e in corrected if e["data"]["window_size_s"] == 60]
        assert len(ids_corrected) > len(set(ids_corrected))  # la fenêtre corrigée est republiée
    finally:
        clean_traces([run_id], day)


# -------------------------------------------------------------------- pipeline d'écriture (MS-10)


def test_le_compte_de_lecture_lit_l_entrepot_et_ne_peut_rien_y_ecrire():
    """Séparation écriture/lecture avec les vrais rôles : l'API lit avec `svc_lecture`."""
    from sqlalchemy import create_engine
    from sqlalchemy.exc import ProgrammingError

    reader = create_engine(POSTGRES_READ_URL)
    try:
        with reader.connect() as connection:
            for query in (
                "SELECT count(*) FROM dwh.v_indicator",
                "SELECT count(*) FROM dwh.dim_road_segment",
                "SELECT count(*) FROM dwh.kpi_duree_episodes",
            ):
                assert connection.execute(text(query)).scalar_one() >= 0
        for statement in (
            "INSERT INTO dwh.dim_run (run_id, source_type, scenario_id, seed) "
            "VALUES ('x-lecture', 'SIMULATED', 'demo', 0)",
            "DELETE FROM dwh.fact_traffic_window",
            "UPDATE dwh.fact_traffic_window SET vehicle_count = 0",
        ):
            denied = pytest.raises(ProgrammingError, match="permission denied")
            with denied, reader.begin() as connection:
                connection.execute(text(statement))
    finally:
        reader.dispose()


def read_facts(reader) -> int:
    with reader.connect() as connection:
        return connection.execute(
            text("SELECT count(*) FROM dwh.v_indicator WHERE run_id = :r"), {"r": SCENARIO_RUN}
        ).scalar_one()


def test_de_kafka_a_l_entrepot_et_aux_recommandations_avec_les_vrais_comptes():
    """Mesures brutes -> flux -> indicateurs -> pipeline -> entrepôt lu par le compte de lecture."""
    from sqlalchemy import create_engine

    messages = scenario_messages()
    items = [(m["subject"].encode(), json.dumps(m).encode()) for m in messages]
    clean_warehouse([SCENARIO_RUN])
    reader = create_engine(POSTGRES_READ_URL)
    try:
        with flux_worker() as flux, pipeline_worker() as writer:
            produce("iot.raw", items)
            # 8 tronçons, minutes 0 à 37 au moins (moins les fenêtres retenues par le contrat)
            wait_for(
                lambda: read_facts(reader) >= 8 * 38,
                timeout_s=120,
                what="les faits de l'entrepôt",
                worker=flux,
            )
            time.sleep(3)  # laisse finir les dernières fenêtres fermées
            first = read_facts(reader)
            time.sleep(2)
            assert read_facts(reader) == first, "l'entrepôt ne se stabilise pas"
            assert not writer.failure

        recommendations = [
            e
            for e in read_topic("traffic.recommendations")
            if e["data"]["provenance"]["run_id"] == SCENARIO_RUN
        ]
        assert recommendations
        for event in recommendations:
            assert_publication("traffic.recommendations", event)
            assert event["data"]["cycle_s"] == sum(p["duration_s"] for p in event["data"]["phases"])

        published = {}
        for event in read_topic("traffic.indicators"):
            if event["data"]["provenance"]["run_id"] == SCENARIO_RUN:
                published[event["id"]] = event["data"]  # le dernier publié l'emporte
        with reader.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT indicator_id, vehicle_count, flow_veh_per_min, sample_count, "
                    "congestion_state FROM dwh.v_indicator WHERE run_id = :r"
                ),
                {"r": SCENARIO_RUN},
            ).all()
        assert len(rows) == len(published) == first
        for row in rows:
            event = published[row.indicator_id]
            assert row.vehicle_count == event["vehicle_count"]
            assert float(row.flow_veh_per_min) == event["flow_veh_per_min"]
            assert row.congestion_state == event["congestion_state"]
            assert row.sample_count == event["sample_count"]

        # Redémarrage du pipeline : il relit, écrit les mêmes clés, n'ajoute rien.
        with pipeline_worker(group=writer.group) as again:
            time.sleep(4)
            assert not again.failure
        assert read_facts(reader) == first
    finally:
        reader.dispose()
        clean_warehouse([SCENARIO_RUN])
