"""Le travailleur sur Kafka et PostgreSQL réels : de `traffic.indicators` à `alerts.events`.

Critère de MS-11 : une congestion simulée déclenche **une seule** alerte, résolue automatiquement ;
tous les événements publiés respectent le contrat ; rien n'est perdu ni doublé à l'arrêt, au
redémarrage ni au rejeu.
"""

import http.server
import json
import threading
import time

from tests.integration import stack
from tests.integration.stack import needs_stack, read_topic, rows, send, wait_until
from tests.support import (
    assert_published_conforms,
    congested,
    indicator,
    silent,
)

pytestmark = needs_stack


def mine(event: dict, run_id: str) -> bool:
    return event["data"]["provenance"]["run_id"] == run_id


def alert_events(run_id: str) -> list[dict]:
    records = read_topic("alerts.events", lambda r: mine(r.event, run_id))
    return [r.event for r in records]


def alerts_of(run_id: str, kind: str | None = None) -> list[dict]:
    query = "SELECT * FROM alertes.alert WHERE run_id = %s"
    if kind:
        query += " AND kind = %s"
    return rows(query, run_id, *([kind] if kind else []))


def scenario(run_id: str) -> list[dict]:
    """Fluide, puis une congestion de cinq minutes, puis le retour au fluide (comme "
    "`traitement`)."""
    series = [indicator(m, "FREE_FLOW", run=run_id) for m in range(2)]
    series += [congested(m, run=run_id) for m in range(2, 7)]
    series += [indicator(m, "FREE_FLOW", run=run_id) for m in range(7, 10)]
    return series


def play(kafka, run_id: str) -> None:
    """Le scénario, au rythme du travailleur : la résolution part une fois l'alerte notifiée.

    Une alerte déjà résolue quand le notificateur passe n'est plus notifiée (rien à signaler à
    l'usager) : en réalité les indicateurs arrivent à une minute d'intervalle, jamais en rafale.
    """
    series = scenario(run_id)
    for event in series[:4]:  # fluide, fluide, première congestion (déclenchante), deuxième
        send(kafka, event)
    wait_until(lambda: any(a["state"] == "NOTIFIED" for a in alerts_of(run_id)), 60)
    for event in series[4:]:
        send(kafka, event)


def test_one_congestion_raises_one_alert_notified_then_resolved_automatically(
    run_id, kafka, start_worker
):
    start_worker()
    play(kafka, run_id)
    wait_until(lambda: [a for a in alerts_of(run_id) if a["state"] == "RESOLVED"], 60)

    (alert,) = alerts_of(run_id)
    assert (alert["kind"], alert["state"], alert["resolution"], alert["cause"]) == (
        "CONGESTION", "RESOLVED", "AUTO", "UNKNOWN",
    )  # fmt: skip
    assert alert["notified_at"] is not None and alert["resolved_at"] >= alert["opened_at"]
    assert alert["opened_at"].isoformat().startswith("2026-10-20T08:03:00")  # temps d'événement
    assert (alert["scenario_id"], alert["seed"]) == ("heure-de-pointe", 42)

    history = rows(
        "SELECT from_state, to_state, actor FROM alertes.alert_history WHERE alert_id = %s "
        "ORDER BY history_id", alert["alert_id"],
    )  # fmt: skip
    assert [(h["from_state"], h["to_state"]) for h in history] == [
        (None, "CREATED"), ("CREATED", "NOTIFIED"), ("NOTIFIED", "RESOLVED"),
    ]  # fmt: skip

    events = wait_until(lambda: (e := alert_events(run_id)) and len(e) == 3 and e, 60)
    assert [e["data"]["state"] for e in events] == ["CREATED", "NOTIFIED", "RESOLVED"]
    assert {e["data"]["alert_id"] for e in events} == {str(alert["alert_id"])}
    assert len({e["id"] for e in events}) == 3
    for event in events:
        assert_published_conforms("alerts.events", event)
    assert events[-1]["data"]["resolution"] == "AUTO"
    unpublished = rows(
        "SELECT count(*) AS n FROM alertes.outbox_event WHERE published_at IS NULL "
        "AND payload->'data'->'provenance'->>'run_id' = %s", run_id,
    )  # fmt: skip
    assert unpublished[0]["n"] == 0
    assert read_topic("errors.dlq", lambda r: run_id in r.value.decode()) == []


def test_a_long_congestion_stays_one_alert_however_many_indicators_arrive(
    run_id, kafka, start_worker
):
    start_worker()
    for minute in range(40):
        send(kafka, congested(minute, run=run_id))
    wait_until(lambda: alerts_of(run_id), 60)
    send(kafka, indicator(40, "FREE_FLOW", run=run_id))
    wait_until(lambda: alerts_of(run_id)[0]["state"] == "RESOLVED", 60)
    assert len(alerts_of(run_id)) == 1
    assert (
        len(
            rows(
                "SELECT 1 FROM alertes.outbox_event WHERE "
                "payload->'data'->'provenance'->>'run_id' = %s",
                run_id,
            )
        )
        == 3
    )  # créée, notifiée, résolue : 40 indicateurs, 3 événements


def test_a_mute_sensor_raises_a_sensor_fault_distinct_from_a_congestion(
    run_id, kafka, start_worker
):
    start_worker()
    for event in (indicator(0, run=run_id), silent(1, run=run_id), silent(2, run=run_id)):
        send(kafka, event)
    wait_until(lambda: alerts_of(run_id, "SENSOR_FAULT"), 60)
    assert alerts_of(run_id, "CONGESTION") == []
    send(kafka, indicator(3, run=run_id))  # les mesures reviennent
    wait_until(lambda: alerts_of(run_id, "SENSOR_FAULT")[0]["state"] == "RESOLVED", 60)
    assert alerts_of(run_id, "SENSOR_FAULT")[0]["rule_id"] == "capteur.muet"


def test_an_invalid_indicator_goes_to_the_error_topic_and_never_creates_an_alert(
    run_id, kafka, start_worker
):
    worker = start_worker()
    bad = congested(0, run=run_id)
    bad["data"]["window_size_s"] = 120
    send(kafka, bad)
    send(kafka, congested(1, run=run_id))  # un message valide derrière : le flux continue
    wait_until(lambda: alerts_of(run_id), 60)
    rejected = wait_until(
        lambda: read_topic("errors.dlq", lambda r: run_id in r.value.decode()), 30
    )
    (event,) = [r.event for r in rejected]
    assert event["data"]["reason_code"] == "CONTRACT_VIOLATION"
    assert event["data"]["reason"].startswith("data/window_size_s")
    assert event["source"] == "alerte" and event["data"]["source_topic"] == "traffic.indicators"
    assert_published_conforms("errors.dlq", event)
    assert worker.error is None and len(alerts_of(run_id)) == 1


def test_a_stopped_service_catches_up_without_loss_or_duplicate(run_id, kafka, start_worker):
    """EXG-NFR-05 : le service d'alerte arrêté, le reste continue ; au redémarrage il rattrape."""
    group = f"alerte-it-{run_id}"
    first = start_worker(group)
    send(kafka, congested(0, run=run_id))
    wait_until(lambda: alerts_of(run_id), 60)
    first.close()  # le service d'alerte s'arrête
    for minute in range(1, 6):  # la chaîne continue de produire des indicateurs
        send(kafka, congested(minute, run=run_id, segment="ROAD_002"))
    send(kafka, indicator(6, "FREE_FLOW", run=run_id))
    assert len(alerts_of(run_id)) == 1  # rien n'est traité pendant l'arrêt
    start_worker(group)  # même groupe : reprise au dernier offset validé
    wait_until(lambda: len(alerts_of(run_id)) == 2, 60)
    wait_until(lambda: [a for a in alerts_of(run_id) if a["state"] == "RESOLVED"], 60)
    by_segment = {a["road_segment_id"]: a for a in alerts_of(run_id)}
    assert set(by_segment) == {"ROAD_001", "ROAD_002"}
    assert by_segment["ROAD_001"]["state"] == "RESOLVED"  # son retour au fluide a été rattrapé
    assert by_segment["ROAD_002"]["state"] != "RESOLVED"  # sa congestion dure encore
    events = wait_until(lambda: (e := alert_events(run_id)) and len(e) >= 4 and e, 60)
    assert len({e["id"] for e in events}) == len(events)  # aucun doublon sur le bus


def test_replaying_every_indicator_changes_nothing(run_id, kafka, start_worker):
    """Un groupe neuf relit tout le sujet (reprise après perte d'offsets) : même résultat, rien "
    "en double."""
    start_worker()
    series = scenario(run_id)
    play(kafka, run_id)
    wait_until(lambda: [a for a in alerts_of(run_id) if a["state"] == "RESOLVED"], 60)
    wait_until(lambda: len(alert_events(run_id)) == 3, 60)
    before = (
        alerts_of(run_id),
        len(
            rows(
                "SELECT 1 FROM alertes.outbox_event WHERE "
                "payload->'data'->'provenance'->>'run_id' = %s",
                run_id,
            )
        ),
    )
    replay = start_worker(from_start=True)  # relit tous les indicateurs de tous les essais
    try:
        wait_until(lambda: replay.timeline.handled.get(series[-1]["id"]), 120)
        after = (
            alerts_of(run_id),
            len(
                rows(
                    "SELECT 1 FROM alertes.outbox_event WHERE "
                    "payload->'data'->'provenance'->>'run_id' = %s",
                    run_id,
                )
            ),
        )
        assert before == after
        assert len(alert_events(run_id)) == 3
    finally:
        replay.close()  # le rejeu a aussi retraité les essais précédents : on efface leurs traces
        for other in rows("SELECT DISTINCT run_id FROM alertes.alert WHERE run_id LIKE 'it-%%'"):
            if other["run_id"] != run_id:
                stack.erase(other["run_id"])


def test_two_runs_of_the_same_segment_are_independent(kafka, start_worker, run_id):
    other = f"{run_id}-b"
    try:
        start_worker()
        send(kafka, congested(0, run=run_id))
        send(kafka, congested(0, run=other))
        wait_until(lambda: alerts_of(run_id) and alerts_of(other), 60)
        assert len(alerts_of(run_id)) == len(alerts_of(other)) == 1
    finally:
        stack.erase(other)


def test_rules_changed_in_the_database_reach_the_running_worker(run_id, kafka, start_worker):
    worker = start_worker(rules_ttl_s=0.2)
    with stack.admin() as connection:
        connection.execute(
            "UPDATE alertes.alert_rule SET enabled = false WHERE rule_id = 'congestion.persistante'"
        )
    try:
        send(kafka, congested(0, run=run_id))
        wait_until(lambda: worker.timeline.handled.get(congested(0, run=run_id)["id"]), 30)
        assert alerts_of(run_id) == []  # règle désactivée : aucune alerte
    finally:
        with stack.admin() as connection:
            connection.execute(
                "UPDATE alertes.alert_rule SET enabled = true "
                "WHERE rule_id = 'congestion.persistante'"
            )
    time.sleep(0.5)  # plus que la durée de vie des règles en mémoire (0,2 s dans ce test)
    send(kafka, congested(5, run=run_id))
    wait_until(lambda: alerts_of(run_id), 30)


class Hook(http.server.BaseHTTPRequestHandler):
    bodies: list = []

    def do_POST(self):  # noqa: N802
        Hook.bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_the_webhook_receives_one_notification_per_alert_before_the_state_becomes_notified(
    run_id, kafka, start_worker
):
    from app.adapters.channels import WebhookChannel

    Hook.bodies = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hook)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        start_worker(channel=WebhookChannel(f"http://127.0.0.1:{server.server_port}/notify"))
        send(kafka, congested(0, run=run_id))
        send(kafka, congested(1, run=run_id))
        wait_until(lambda: alerts_of(run_id) and alerts_of(run_id)[0]["state"] == "NOTIFIED", 60)
    finally:
        server.shutdown()
        server.server_close()
    mine_ = [b for b in Hook.bodies if b["alert_id"] == str(alerts_of(run_id)[0]["alert_id"])]
    assert len(mine_) == 1
    assert (mine_[0]["kind"], mine_[0]["severity"], mine_[0]["source_type"]) == (
        "CONGESTION",
        "WARNING",
        "SIMULATED",
    )
    assert "acknowledged_by" not in mine_[0]  # aucune donnée de personne
