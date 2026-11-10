"""MS-12 contre un vrai Kafka et un vrai MongoDB : garde-fous, mode dégradé, commande, audit.

Critères : aucune commande qui viole une règle de sécurité n'est appliquée ; la perte des
recommandations ramène au plan fixe.
"""

import secrets
import time
from datetime import UTC, datetime

import pytest
from conformance import assert_publication
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import OperationFailure

from app.api.deps import get_audit, get_service
from app.domain.model import Mode
from app.domain.safety import Phase
from app.main import app
from app.schemas.events import RecommendationEvent
from tests.integration import stack
from tests.integration.harness import Service, new_intersection
from tests.support import plan
from tests.tokens import bearer

pytestmark = stack.needs_stack

SECRET = stack.JWT_SECRET


def decisions(statuses: list[dict]) -> list[tuple[str, str, str | None]]:
    return [
        (
            s["data"]["decision"]["origin"],
            s["data"]["decision"]["outcome"],
            s["data"]["decision"]["refusal_reason"],
        )
        for s in statuses
    ]


def wait_status(service: Service, intersection: str, origin: str, outcome="APPLIED", seconds=30):
    def found():
        return [
            s
            for s in service.statuses(intersection)
            if s["data"]["decision"]["origin"] == origin
            and s["data"]["decision"]["outcome"] == outcome
        ]

    return stack.wait_until(
        found, seconds, why=lambda: f"statuts vus : {decisions(service.statuses(intersection))}"
    )


# =========================================================================== recommandations
def test_each_intersection_announces_its_fixed_plan_on_the_bus_at_startup(
    intersection, make_service
):
    service = make_service(intersection)
    [startup] = wait_status(service, intersection, "STARTUP")
    assert startup["data"]["mode"] == "DEGRADED_FIXED_PLAN"
    assert [p["duration_s"] for p in startup["data"]["phases"]] == [30, 30]
    assert_publication("reponse", "signal.status", startup)


def test_a_safe_recommendation_read_from_kafka_is_applied_and_announced(
    intersection, make_service, kafka
):
    service = make_service(intersection)
    event = service.recommendation(intersection, plan(40, 20))
    stack.send(kafka, event)
    [status] = wait_status(service, intersection, "RECOMMENDATION")
    assert status["data"]["decision"]["reference_id"] == event["data"]["recommendation_id"]
    assert (status["data"]["mode"], status["correlation_id"]) == ("AUTOMATIC", "corr-rec-1")
    assert [p["duration_s"] for p in status["data"]["phases"]] == [40, 20]
    assert_publication("reponse", "signal.status", status)
    assert service.service.view(intersection).mode is Mode.AUTOMATIC
    [record] = stack.on_subject("signal.status", intersection)[-1:]
    assert record.key == intersection.encode()  # clé de partition : l'ordre par carrefour
    entries = [
        e for e in stack.audit_entries(intersection) if e["action"] == "signal.recommendation"
    ]
    assert [(e["outcome"], e["actor"], e["service"]) for e in entries] == [
        ("ok", "reponse", "reponse")
    ]


@pytest.mark.parametrize(
    ("phases", "reason"),
    [
        ([Phase("P1", ("N", "E"), 30), Phase("P2", ("S", "W"), 30)], "CONFLICTING_GREENS"),
        (plan(5, 30), "PHASE_TOO_SHORT"),
        (plan(30, 200), "PHASE_TOO_LONG"),
    ],
)
def test_a_dangerous_recommendation_is_refused_announced_and_journaled_in_mongodb(
    intersection, make_service, kafka, phases, reason
):
    """Critère : rien de dangereux n'atteint le contrôleur, et la trace est dans la vraie base."""
    service = make_service(intersection)
    before = service.service.view(intersection)
    event = service.recommendation(intersection, phases)
    stack.send(kafka, event)
    [status] = wait_status(service, intersection, "RECOMMENDATION", "REFUSED")
    assert status["data"]["decision"]["refusal_reason"] == reason
    assert status["data"]["mode"] == "DEGRADED_FIXED_PLAN"
    assert_publication("reponse", "signal.status", status)
    after = service.service.view(intersection)
    assert (after.mode, after.phases) == (before.mode, before.phases)  # les phases tournent seules
    entries = stack.wait_until(
        lambda: [e for e in stack.audit_entries(intersection) if e["outcome"] == "denied"]
    )
    assert entries[0]["details"]["refusal_reason"] == reason
    assert entries[0]["details"]["reference_id"] == event["data"]["recommendation_id"]


def test_a_poison_message_goes_to_the_dead_letter_topic_and_the_next_one_is_still_read(
    intersection, make_service, kafka
):
    service = make_service(intersection)
    marker = f"pas-du-json-{secrets.token_hex(6)}"
    kafka.send("traffic.recommendations", key=intersection.encode(), value=marker.encode()).get(15)
    stack.send(kafka, service.recommendation(intersection))
    wait_status(service, intersection, "RECOMMENDATION")
    rejected = stack.wait_until(
        lambda: [
            r.event
            for r in stack.read_topic("errors.dlq")
            if r.event["data"].get("original_payload") == marker
        ]
    )
    assert rejected[0]["data"]["reason_code"] == "UNREADABLE"
    assert_publication("reponse", "errors.dlq", rejected[0])


# =========================================================================== mode dégradé
def test_losing_the_recommendations_returns_to_the_fixed_plan_and_publishes_it(
    intersection, make_service, kafka
):
    """Critère : la perte des recommandations ramène au plan fixe."""
    service = make_service(intersection, max_silence_s=180)  # 180 s simulées : ~9 s réelles
    stack.send(kafka, service.recommendation(intersection, plan(50, 30)))
    wait_status(service, intersection, "RECOMMENDATION")
    assert service.service.view(intersection).mode is Mode.AUTOMATIC
    started = time.monotonic()
    [fallback] = wait_status(service, intersection, "FIXED_PLAN_FALLBACK", seconds=60)
    elapsed = time.monotonic() - started
    assert fallback["data"]["mode"] == "DEGRADED_FIXED_PLAN"
    assert [p["duration_s"] for p in fallback["data"]["phases"]] == [30, 30]
    assert_publication("reponse", "signal.status", fallback)
    view = service.service.view(intersection)
    assert view.mode is Mode.DEGRADED_FIXED_PLAN and [p.duration_s for p in view.phases] == [30, 30]
    assert 1 < elapsed < 30 * service.clock.speed / 20 + 5  # ~9 s réelles pour 180 s simulées
    assert any(
        e["action"] == "signal.fixed_plan_fallback" for e in stack.audit_entries(intersection)
    )


def test_the_next_recommendation_after_the_loss_resumes_automatic_mode(
    intersection, make_service, kafka
):
    service = make_service(intersection, max_silence_s=30)
    stack.send(kafka, service.recommendation(intersection))
    wait_status(service, intersection, "FIXED_PLAN_FALLBACK", seconds=60)
    time.sleep(0.2)
    stack.send(kafka, service.recommendation(intersection, plan(45, 25)))
    stack.wait_until(lambda: service.service.view(intersection).mode is Mode.AUTOMATIC, 30)
    assert [p.duration_s for p in service.service.view(intersection).phases] == [45, 25]


def test_stopping_the_service_returns_the_signals_to_the_fixed_plan_and_says_so(
    intersection, make_service, kafka
):
    """Si le service s'arrête volontairement, les feux ne restent pas sur un plan périmé."""
    service = make_service(intersection)
    stack.send(kafka, service.recommendation(intersection))
    wait_status(service, intersection, "RECOMMENDATION")
    service.stop()
    shutdown = [
        s
        for s in service.statuses(intersection)
        if s["id"].startswith(f"reponse-shutdown-{intersection}")
    ]
    assert len(shutdown) == 1
    assert shutdown[0]["data"]["mode"] == "DEGRADED_FIXED_PLAN"
    assert_publication("reponse", "signal.status", shutdown[0])


def test_a_restarted_service_starts_at_the_fixed_plan_and_resumes_where_the_group_left_off(
    intersection, make_service, kafka
):
    group = f"reponse-it-{secrets.token_hex(4)}"
    first = make_service(intersection, group=group)
    one = first.recommendation(intersection, plan(40, 20))
    stack.send(kafka, one)
    wait_status(first, intersection, "RECOMMENDATION")
    time.sleep(1.0)  # laisse le consommateur valider l'offset
    first.stop()
    time.sleep(0.2)
    two = first.recommendation(intersection, plan(45, 25))  # arrive pendant l'arrêt
    stack.send(kafka, two)
    second = make_service(intersection, group=group, warm=False)
    stack.wait_until(
        lambda: second.service.view(intersection).mode is Mode.AUTOMATIC,
        90,
        why=lambda: "la recommandation arrivée pendant l'arrêt n'est pas appliquée",
    )
    assert [p.duration_s for p in second.service.view(intersection).phases] == [45, 25]
    references = [
        s["data"]["decision"]["reference_id"]
        for s in second.statuses(intersection)
        if s["data"]["decision"]["origin"] == "RECOMMENDATION"
    ]
    assert references.count(one["data"]["recommendation_id"]) == 1  # pas rejouée au redémarrage
    assert references.count(two["data"]["recommendation_id"]) == 1
    startups = [
        s for s in second.statuses(intersection) if s["data"]["decision"]["origin"] == "STARTUP"
    ]
    assert len(startups) == 2  # un par démarrage


def test_without_kafka_the_signals_still_fall_back_and_the_events_wait(intersection):
    """Le bus injoignable ne retient pas les feux : ils reviennent seuls au plan fixe."""
    service = Service(
        [intersection], bootstrap="127.0.0.1:1", speed=50.0, max_silence_s=30, publish_timeout_s=1.0
    )
    try:
        service.start()
        service.service.on_recommendation(
            RecommendationEvent.model_validate(service.recommendation(intersection))
        )
        assert service.service.view(intersection).mode is Mode.AUTOMATIC
        stack.wait_until(
            lambda: service.service.view(intersection).mode is Mode.DEGRADED_FIXED_PLAN, 30
        )
        assert len(service.outbox) >= 2  # le démarrage, la recommandation et le retour attendent
    finally:
        service.stop()
        service.publisher.close()
        service.audit.close()


# =========================================================================== commande manuelle
@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def attach(client, service: Service) -> TestClient:
    app.dependency_overrides[get_service] = lambda: service.service
    app.dependency_overrides[get_audit] = lambda: service.audit
    return client


def headers(role="operator", sub="op-1") -> dict:
    return bearer(role, sub=sub, key=SECRET)


SET_P2 = {"action": "SET_PHASE", "phase_id": "P2", "duration_s": 40, "reason": "Évacuation test"}


def when_phase_is_old_enough(service: Service, intersection: str) -> None:
    stack.wait_until(
        lambda: (
            (service.clock() - service.service.view(intersection).phase_started_at).total_seconds()
            >= 11
            and service.service.view(intersection).signal == "GREEN"
        ),
        30,
    )


def test_a_manual_command_is_journaled_in_mongodb_applied_and_published(
    intersection, make_service, client
):
    service = make_service(intersection)
    attach(client, service)
    when_phase_is_old_enough(service, intersection)
    sub = f"op-{secrets.token_hex(3)}"
    response = client.post(
        f"/api/v1/signals/{intersection}/commands", json=SET_P2, headers=headers(sub=sub)
    )
    assert response.status_code == 202 and response.json()["status"] == "APPLIED"
    command_id = response.json()["command_id"]
    [entry] = [
        e for e in stack.audit_entries(intersection) if e["action"].startswith("signal.command.")
    ]
    assert entry["actor"] == sub and entry["outcome"] == "ok" and entry["service"] == "reponse"
    for key, value in {
        "command_id": command_id,
        "intersection_id": intersection,
        "phase_id": "P2",
        "duration_s": 40,
        "reason": "Évacuation test",
        "role": "operator",
    }.items():
        assert entry["details"][key] == value
    [status] = wait_status(service, intersection, "MANUAL_COMMAND")[:1]
    assert (
        status["data"]["mode"] == "MANUAL"
        and status["data"]["decision"]["reference_id"] == command_id
    )
    assert_publication("reponse", "signal.status", status)
    state = client.get(f"/api/v1/signals/{intersection}", headers=headers("viewer")).json()
    assert state["mode"] == "MANUAL"


def test_a_second_command_during_the_first_is_409_and_a_recommendation_is_refused(
    intersection, make_service, client, kafka
):
    service = make_service(intersection)
    attach(client, service)
    when_phase_is_old_enough(service, intersection)
    assert (
        client.post(
            f"/api/v1/signals/{intersection}/commands", json=SET_P2, headers=headers()
        ).status_code
        == 202
    )
    second = client.post(f"/api/v1/signals/{intersection}/commands", json=SET_P2, headers=headers())
    assert second.status_code == 409 and second.json()["code"] == "COMMAND_IN_PROGRESS"
    stack.send(kafka, service.recommendation(intersection))
    [refused] = wait_status(service, intersection, "RECOMMENDATION", "REFUSED")
    assert refused["data"]["decision"]["refusal_reason"] == "MANUAL_OVERRIDE"
    assert service.service.view(intersection).mode is Mode.MANUAL


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ({**SET_P2, "duration_s": 9}, "PHASE_TOO_SHORT"),
        ({**SET_P2, "duration_s": 91}, "PHASE_TOO_LONG"),
        ({**SET_P2, "phase_id": "P7"}, "UNKNOWN_PHASE"),
    ],
)
def test_a_dangerous_manual_command_is_422_and_leaves_a_trace_in_mongodb_and_on_the_bus(
    intersection, make_service, client, body, reason
):
    """Critère : aucune commande qui viole une règle de sécurité n'est appliquée."""
    service = make_service(intersection)
    attach(client, service)
    when_phase_is_old_enough(service, intersection)
    before = client.get(f"/api/v1/signals/{intersection}", headers=headers("viewer")).json()
    response = client.post(f"/api/v1/signals/{intersection}/commands", json=body, headers=headers())
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "UNSAFE_COMMAND" and response.json()["detail"].startswith(
        reason
    )
    after = client.get(f"/api/v1/signals/{intersection}", headers=headers("viewer")).json()
    assert (after["mode"], after["phases"], after["decision"]) == (
        before["mode"],
        before["phases"],
        before["decision"],
    )
    [entry] = [
        e for e in stack.audit_entries(intersection) if e["action"].startswith("signal.command.")
    ]
    assert entry["outcome"] == "denied" and entry["details"]["refusal_reason"] == reason
    [status] = wait_status(service, intersection, "MANUAL_COMMAND", "REFUSED")
    assert status["data"]["decision"]["refusal_reason"] == reason
    assert status["data"]["mode"] == "DEGRADED_FIXED_PLAN"


def test_the_hold_ends_by_itself_and_resuming_is_journaled(intersection, make_service, client):
    service = make_service(intersection)
    attach(client, service)
    when_phase_is_old_enough(service, intersection)
    short = {**SET_P2, "duration_s": 12}
    assert (
        client.post(
            f"/api/v1/signals/{intersection}/commands", json=short, headers=headers()
        ).status_code
        == 202
    )
    stack.wait_until(lambda: service.service.view(intersection).mode is not Mode.MANUAL, 30)
    ended = wait_status(service, intersection, "FIXED_PLAN_FALLBACK")
    assert ended[0]["data"]["mode"] == "DEGRADED_FIXED_PLAN"
    resume = {"action": "RESUME_AUTOMATIC", "reason": "rien à reprendre"}
    reply = client.post(f"/api/v1/signals/{intersection}/commands", json=resume, headers=headers())
    assert reply.status_code == 202
    actions = [
        e["action"]
        for e in stack.audit_entries(intersection)
        if e["action"].startswith("signal.command.")
    ]
    assert actions == ["signal.command.SET_PHASE", "signal.command.RESUME_AUTOMATIC"]


def test_the_command_history_reads_the_real_journal_newest_first_page_by_page(
    intersection, make_service, client
):
    service = make_service(intersection)
    attach(client, service)
    when_phase_is_old_enough(service, intersection)
    for index in range(5):
        client.post(
            f"/api/v1/signals/{intersection}/commands",
            json={**SET_P2, "duration_s": 5 + index % 3, "reason": f"essai {index}"},
            headers=headers(sub=f"op-{index}"),
        )
        time.sleep(0.01)
    pages, cursor = [], None
    for _ in range(4):
        url = f"/api/v1/signals/{intersection}/commands?limit=2" + (
            f"&cursor={cursor}" if cursor else ""
        )
        body = client.get(url, headers=headers("viewer")).json()
        pages.append(body["items"])
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert [len(p) for p in pages] == [2, 2, 1]
    reasons = [item["reason"] for page in pages for item in page]
    assert reasons == [f"essai {i}" for i in (4, 3, 2, 1, 0)]
    assert {item["status"] for page in pages for item in page} == {"REFUSED"}
    assert (
        pages[0][0]["requested_by"] == "op-4" and pages[0][0]["refusal_reason"] == "PHASE_TOO_SHORT"
    )
    other = client.get(f"/api/v1/signals/{new_intersection()}/commands", headers=headers("viewer"))
    assert other.status_code == 404  # carrefour sans feux dans ce service


def test_without_a_journal_a_manual_command_is_not_applied(intersection, client):
    """MongoDB injoignable : pas de trace, pas d'effet. Les feux, eux, continuent de tourner."""
    service = Service(
        [intersection],
        mongo_url="mongodb://svc_reponse:x@127.0.0.1:1/novaria?authSource=novaria",
        mongo_timeout_ms=300,
    )
    try:
        attach(client, service.start())
        when_phase_is_old_enough(service, intersection)
        before = service.service.view(intersection)
        response = client.post(
            f"/api/v1/signals/{intersection}/commands", json=SET_P2, headers=headers()
        )
        assert response.status_code == 503 and response.json()["code"] == "UPSTREAM_UNAVAILABLE"
        after = service.service.view(intersection)
        assert after.mode is Mode.DEGRADED_FIXED_PLAN and after.phases == before.phases
        refused = client.post(
            f"/api/v1/signals/{intersection}/commands",
            json={**SET_P2, "duration_s": 9},
            headers=headers(),
        )
        assert refused.status_code == 422  # un refus reste un refus
    finally:
        service.close()


# =========================================================================== journal MongoDB
def test_the_service_account_can_append_and_read_but_never_rewrite_the_journal(intersection):
    client = MongoClient(stack.MONGO_URL, tz_aware=True, serverSelectionTimeoutMS=5000)
    try:
        logs = client[stack.database_name()]["audit_logs"]
        inserted = logs.insert_one(
            {
                "ts": datetime.now(UTC),
                "service": "reponse",
                "actor": "it",
                "action": "signal.command.SET_PHASE",
                "outcome": "ok",
                "details": {"intersection_id": intersection},
            }
        )
        assert logs.find_one({"_id": inserted.inserted_id}) is not None
        with pytest.raises(OperationFailure) as updated:
            logs.update_one({"_id": inserted.inserted_id}, {"$set": {"outcome": "denied"}})
        with pytest.raises(OperationFailure) as deleted:
            logs.delete_one({"_id": inserted.inserted_id})
        assert updated.value.code == 13 and deleted.value.code == 13  # non autorisé
        with pytest.raises(OperationFailure):
            client[stack.database_name()]["raw_events"].find_one()
    finally:
        client.close()


def test_a_malformed_journal_entry_is_refused_by_the_collection_validator(intersection):
    client = MongoClient(stack.MONGO_URL, tz_aware=True, serverSelectionTimeoutMS=5000)
    try:
        logs = client[stack.database_name()]["audit_logs"]
        with pytest.raises(OperationFailure) as refused:
            logs.insert_one({"service": "reponse", "details": {"intersection_id": intersection}})
        assert refused.value.code == 121  # échec de validation du document
    finally:
        client.close()


def test_the_journal_has_an_index_for_the_history_of_one_intersection():
    client, logs = stack.admin_logs()
    try:
        assert "intersection_ts" in logs.index_information()
    finally:
        client.close()


def test_a_burst_of_manual_commands_is_all_journaled_and_exactly_one_is_applied(
    intersection, make_service, client
):
    service = make_service(intersection)
    attach(client, service)
    when_phase_is_old_enough(service, intersection)
    replies = [
        client.post(
            f"/api/v1/signals/{intersection}/commands", json=SET_P2, headers=headers(sub=f"op-{i}")
        )
        for i in range(12)
    ]
    assert sorted(r.status_code for r in replies).count(202) == 1
    assert {r.status_code for r in replies} <= {202, 409}
    journal = [
        e for e in stack.audit_entries(intersection) if e["action"].startswith("signal.command.")
    ]
    assert len(journal) == 12
