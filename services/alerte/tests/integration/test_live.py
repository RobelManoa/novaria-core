"""Du tableau de bord à la base : le flux en direct, l'API et le délai mesuré (MS-11).

Le critère de MS-11 : « une congestion simulée déclenche une seule alerte, visible au tableau de
bord dans un délai mesuré et documenté, puis résolue automatiquement ». Ces tests branchent un
client du flux SSE (ce que lit le tableau de bord) sur l'API réelle, authentification comprise,
derrière le vrai Kafka et le vrai PostgreSQL, et mesurent le délai.

Le rapport de délai est écrit dans le fichier nommé par `NOVARIA_ALERTE_REPORT` s'il est défini.
"""

import json
import os
import statistics
import time
from pathlib import Path

import httpx
import pytest

from tests.integration import stack
from tests.integration.stack import needs_stack, rows, send, wait_until
from tests.support import congested, indicator

pytestmark = needs_stack

MEASURES = 30  # congestions mesurées une à une : de quoi lire un p95
SEGMENT0 = 100  # ROAD_101 à ROAD_130 : un tronçon par congestion


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(share * len(ordered)) - 1))]


def summary(values: list[float]) -> dict:
    return {
        "n": len(values),
        "min_ms": round(min(values) * 1000, 1),
        "median_ms": round(statistics.median(values) * 1000, 1),
        "p95_ms": round(percentile(values, 0.95) * 1000, 1),
        "max_ms": round(max(values) * 1000, 1),
    }


def count_alerts(run_id: str) -> int:
    found = rows("SELECT count(*) AS n FROM alertes.alert WHERE run_id = %s", run_id)
    return found[0]["n"]


def alert_of(run_id: str, segment: str) -> dict | None:
    found = rows(
        "SELECT alert_id::text, state FROM alertes.alert WHERE run_id = %s AND road_segment_id = "
        "%s",
        run_id, segment,
    )  # fmt: skip
    return found[0] if found else None


# ------------------------------------------------------------------------------------ le flux
def test_the_stream_needs_a_valid_token(api):
    url = api.url + "/api/v1/events/stream"
    assert httpx.get(url, timeout=10).status_code == 401
    assert (
        httpx.get(url, headers={"Authorization": "Bearer pas-un-jeton"}, timeout=10).status_code
        == 401
    )
    refused = httpx.get(url, params={"types": "inconnu"}, headers=api.headers(), timeout=10)
    assert refused.status_code == 422 and refused.json()["errors"][0]["field"] == "query.types"


def test_a_congestion_appears_in_the_dashboard_stream_once_then_resolves(
    run_id, kafka, api, start_client, start_worker
):
    """Le critère, de bout en bout : une alerte visible en direct, puis résolue, sans doublon."""
    client = start_client()
    start_worker()
    for minute in range(2):
        send(kafka, indicator(minute, "FREE_FLOW", run=run_id))
    sent_at = {}
    for minute in range(2, 7):
        event = congested(minute, run=run_id)
        sent_at[minute] = send(kafka, event)
    mine_ = lambda r: r.data.get("provenance", {}).get("run_id") == run_id  # noqa: E731
    wait_until(
        lambda: [r for r in client.received if mine_(r) and r.data["state"] == "NOTIFIED"], 60
    )
    for minute in range(7, 10):  # le retour au fluide, une fois l'alerte notifiée
        send(kafka, indicator(minute, "FREE_FLOW", run=run_id))

    mine = lambda r: r.data.get("provenance", {}).get("run_id") == run_id  # noqa: E731
    wait_until(
        lambda: [r for r in client.received if mine(r) and r.data["state"] == "RESOLVED"], 60
    )
    received = [r for r in client.received if mine(r)]
    assert [r.data["state"] for r in received] == ["CREATED", "NOTIFIED", "RESOLVED"]
    assert {r.event for r in received} == {"alert.state_changed"}
    assert len({r.data["alert_id"] for r in received}) == 1  # une seule alerte
    assert received[0].data["cause"] == "UNKNOWN" and received[-1].data["resolution"] == "AUTO"
    assert received[0].event_id.startswith("alerte-")
    # visible dans un délai court après l'indicateur déclenchant (le premier CONGESTED)
    assert received[0].at - sent_at[2] < 10


def test_every_client_connected_receives_the_alert(run_id, kafka, start_client, start_worker):
    clients = [start_client(), start_client("operator"), start_client("admin")]
    start_worker()
    send(kafka, congested(0, run=run_id))
    for client in clients:
        wait_until(
            lambda c=client: [
                r for r in c.received if r.data.get("provenance", {}).get("run_id") == run_id
            ],
            60,
        )


def test_the_type_filter_and_the_heartbeat(monkeypatch, run_id, kafka, start_worker):
    from tests.integration.harness import Api, SseClient

    api = Api(monkeypatch, heartbeat_s=1.0).start()
    try:
        signals_only = SseClient(api, types="signal.status").start()
        everything = SseClient(api).start()
        start_worker()
        send(kafka, congested(0, run=run_id))
        wait_until(lambda: [r for r in everything.received if r.event == "alert.state_changed"], 60)
        wait_until(lambda: [r for r in signals_only.received if r.event == "heartbeat"], 10)
        assert [r for r in signals_only.received if r.event == "alert.state_changed"] == []
        beat = wait_until(
            lambda: next((r for r in everything.received if r.event == "heartbeat"), None), 10
        )
        assert beat.data["time"].endswith("Z")
        signals_only.close()
        everything.close()
    finally:
        api.close()


# ----------------------------------------------------------------------------- API et opérateur
def test_an_operator_acknowledges_and_the_dashboard_sees_it_in_the_stream(
    run_id, kafka, api, start_client, start_worker
):
    client = start_client()
    worker = start_worker()
    send(kafka, congested(0, run=run_id))
    alert = wait_until(lambda: alert_of(run_id, "ROAD_001"), 60)
    wait_until(lambda: client.first(alert["alert_id"], "NOTIFIED"), 30)

    listed = api.get("/api/v1/alerts", state="NOTIFIED", road_segment_id="ROAD_001").json()
    assert alert["alert_id"] in [a["alert_id"] for a in listed["items"]]
    assert (
        api.post(f"/api/v1/alerts/{alert['alert_id']}/acknowledge", role="viewer").status_code
        == 403
    )

    reply = api.post(f"/api/v1/alerts/{alert['alert_id']}/acknowledge", sub="operateur-7")
    assert reply.status_code == 200 and reply.json()["acknowledged_by"] == "operateur-7"
    wait_until(
        lambda: client.first(alert["alert_id"], "ACKNOWLEDGED"),
        30,
        why=lambda: (
            f"travailleur : {worker.diagnose()} ; reçus par le client : "
            f"{[(r.event, r.data.get('state')) for r in client.received]}"
        ),
    )  # publié par le relais du travailleur
    assert (
        api.post(f"/api/v1/alerts/{alert['alert_id']}/acknowledge", sub="autre").json()[
            "acknowledged_by"
        ]
        == "operateur-7"
    )

    resolved = api.post(
        f"/api/v1/alerts/{alert['alert_id']}/resolve", json={"comment": "agents sur place"}
    )
    assert resolved.status_code == 200 and resolved.json()["resolution"] == "MANUAL"
    wait_until(lambda: client.first(alert["alert_id"], "RESOLVED"), 30)
    assert api.post(f"/api/v1/alerts/{alert['alert_id']}/resolve").status_code == 409
    assert api.post(f"/api/v1/alerts/{alert['alert_id']}/acknowledge").status_code == 409

    detail = api.get(f"/api/v1/alerts/{alert['alert_id']}").json()
    assert [h["to_state"] for h in detail["history"]] == [
        "CREATED",
        "NOTIFIED",
        "ACKNOWLEDGED",
        "RESOLVED",
    ]
    assert detail["history"][-1]["comment"] == "agents sur place"
    assert client.states_of(alert["alert_id"]) == [
        "CREATED",
        "NOTIFIED",
        "ACKNOWLEDGED",
        "RESOLVED",
    ]


def test_a_rule_change_through_the_api_reaches_the_running_worker(run_id, kafka, api, start_worker):
    worker = start_worker(rules_ttl_s=0.2)
    try:
        reply = httpx.patch(
            api.url + "/api/v1/alert-rules/congestion.persistante", json={"enabled": False},
            headers=api.headers("admin"), timeout=10,
        )  # fmt: skip
        assert reply.status_code == 200 and reply.json()["enabled"] is False
        forbidden = httpx.patch(
            api.url + "/api/v1/alert-rules/congestion.persistante",
            json={"enabled": True},
            headers=api.headers("operator"),
            timeout=10,
        )
        assert forbidden.status_code == 403
        time.sleep(0.5)  # plus que la durée de vie des règles en mémoire
        send(kafka, congested(0, run=run_id))
        wait_until(lambda: worker.timeline.handled.get(congested(0, run=run_id)["id"]), 30)
        assert alert_of(run_id, "ROAD_001") is None
    finally:
        httpx.patch(api.url + "/api/v1/alert-rules/congestion.persistante", json={"enabled": True},
                    headers=api.headers("admin"), timeout=10)  # fmt: skip
    time.sleep(0.5)
    send(kafka, congested(10, run=run_id))
    wait_until(lambda: alert_of(run_id, "ROAD_001"), 30)


def test_the_api_lists_alerts_page_by_page_from_the_real_database(run_id, kafka, api, start_worker):
    start_worker()
    for n in range(5):
        send(kafka, congested(n, run=run_id, segment=f"ROAD_{SEGMENT0 + 50 + n}"))
    wait_until(lambda: len(rows("SELECT 1 FROM alertes.alert WHERE run_id = %s", run_id)) == 5, 60)
    seen, cursor = [], None
    for _ in range(10):
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = api.get("/api/v1/alerts", **params).json()
        seen += [a["alert_id"] for a in page["items"] if a["provenance"]["run_id"] == run_id]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 5 == len(set(seen))


# -------------------------------------------------------------------------- le délai mesuré
def test_the_delay_from_the_triggering_indicator_to_the_dashboard_is_measured(
    run_id, kafka, api, start_client, start_worker
):
    """EXG-NFR-03 : p95 du délai entre l'indicateur déclenchant et l'alerte visible ; objectif 10 s.

    Trente congestions sur trente tronçons, une à la fois. Pour chacune : t0 = accusé du broker pour
    l'indicateur CONGESTED ; puis les instants où le travailleur le reçoit, où l'alerte est validée
    en base, où l'événement est accusé par Kafka, où le client du flux le reçoit.
    """
    client = start_client()
    worker = start_worker()
    # échauffement : première connexion à la base, premier envoi (non compté)
    send(kafka, congested(0, run=run_id, segment="ROAD_099"))
    wait_until(lambda: alert_of(run_id, "ROAD_099"), 60)
    wait_until(lambda: client.first(alert_of(run_id, "ROAD_099")["alert_id"], "CREATED"), 30)

    stages: dict[str, list[float]] = {
        k: [] for k in ("to_worker", "to_database", "to_kafka", "to_dashboard", "total")
    }
    notified: list[float] = []
    for n in range(MEASURES):
        segment = f"ROAD_{SEGMENT0 + 1 + n}"
        trigger = congested(1, run=run_id, segment=segment)
        t0 = send(kafka, trigger)
        alert = wait_until(lambda s=segment: alert_of(run_id, s), 30)
        created = wait_until(lambda a=alert: client.first(a["alert_id"], "CREATED"), 30)
        event_id = f"alerte-{alert['alert_id']}-created"
        wait_until(lambda e=event_id: e in worker.timeline.published, 30)
        t = worker.timeline
        stages["to_worker"].append(t.consumed[trigger["id"]] - t0)
        stages["to_database"].append(t.handled[trigger["id"]] - t.consumed[trigger["id"]])
        stages["to_kafka"].append(t.published[event_id] - t.handled[trigger["id"]])
        stages["to_dashboard"].append(created.at - t.published[event_id])
        stages["total"].append(created.at - t0)
        notified_id = f"alerte-{alert['alert_id']}-notified"

        def why(a=alert, e=notified_id, count=n) -> str:
            return (
                f"mesure n°{count} : publié par le relais {e in worker.timeline.published}, "
                f"lu par le lecteur de l'API {e in api.bus_seen} "
                f"(fil vivant {api.reader_alive()}), "
                f"états reçus par le client {client.states_of(a['alert_id'])}"
            )

        seen = wait_until(lambda a=alert: client.first(a["alert_id"], "NOTIFIED"), 30, why=why)
        notified.append(seen.at - t0)
        time.sleep(0.05)

    report = {
        "measures": MEASURES,
        "objective_p95_s": 10,
        "created_visible": summary(stages["total"]),
        "notified_visible": summary(notified),
        "stages_ms": {name: summary(values) for name, values in stages.items() if name != "total"},
    }
    print("\nDÉLAI MESURÉ :", json.dumps(report, indent=1))
    target = os.environ.get("NOVARIA_ALERTE_REPORT")
    if target:
        Path(target).write_text(json.dumps(report, indent=1), encoding="utf-8")
    assert report["created_visible"]["p95_ms"] < 10_000  # objectif de EXG-NFR-03
    assert report["created_visible"]["max_ms"] < 30_000
    # une seule alerte par tronçon malgré les indicateurs répétés
    assert len(rows("SELECT 1 FROM alertes.alert WHERE run_id = %s", run_id)) == MEASURES + 1


def test_a_burst_of_congestions_is_all_delivered_and_the_delay_is_reported(
    run_id, kafka, api, start_client, start_worker
):
    """100 congestions d'un coup (une heure de pointe sur tout le réseau) : aucune perte, aucun "
    "doublon."""
    client = start_client()
    worker = start_worker()
    total = 100
    t0 = time.perf_counter()
    for n in range(total):
        kafka.send("traffic.indicators", key=b"INT_01", value=json.dumps(
            congested(1, run=run_id, segment=f"ROAD_{300 + n}")).encode())  # fmt: skip
    kafka.flush()
    sent = time.perf_counter() - t0
    mine = lambda r: r.data.get("provenance", {}).get("run_id") == run_id  # noqa: E731
    wait_until(
        lambda: (
            len([r for r in client.received if mine(r) and r.data["state"] == "NOTIFIED"]) == total
        ),
        120,
        why=lambda: (
            f"alertes en base : {count_alerts(run_id)} ; "
            f"reçus par le client : {len([r for r in client.received if mine(r)])} ; "
            f"travailleur : {worker.diagnose()[:300]}"
        ),
    )
    done = time.perf_counter() - t0
    created = [r for r in client.received if mine(r) and r.data["state"] == "CREATED"]
    assert len(created) == total and len({r.data["alert_id"] for r in created}) == total
    assert len(rows("SELECT 1 FROM alertes.alert WHERE run_id = %s", run_id)) == total
    delays = [r.at - t0 for r in created]
    print(
        f"\nRAFALE : {total} alertes en {done:.2f} s (envoi {sent:.2f} s) ; dernier CREATED à "
        f"{max(delays):.2f} s"
    )
    assert done < 60


def test_the_stream_survives_a_client_that_leaves(run_id, kafka, api, start_client, start_worker):
    gone = start_client()
    stay = start_client()
    gone.close()
    start_worker()
    send(kafka, congested(0, run=run_id))
    wait_until(
        lambda: [r for r in stay.received if r.data.get("provenance", {}).get("run_id") == run_id],
        60,
    )
    assert stack.rows("SELECT 1 AS ok")[0]["ok"] == 1


@pytest.mark.parametrize("role", ["viewer", "operator", "admin"])
def test_every_role_can_read_the_alerts(api, role):
    assert api.get("/api/v1/alerts", role=role).status_code == 200
    assert api.get("/api/v1/alert-rules", role=role).status_code == 200
