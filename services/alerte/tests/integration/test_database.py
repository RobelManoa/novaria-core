"""PostgreSQL réel : ce que la base garantit et ce que le service lui demande (MS-11).

Compte `svc_alerte` (droits de production). Preuves : l'index unique d'une alerte par épisode,
l'atomicité d'un changement d'état avec son événement (RG-17), la boîte d'envoi sans doublon, la
migration 0008, l'isolation du schéma (ADR-008).
"""

import threading
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from app.adapters.postgres_store import PostgresAlertStore
from app.domain.model import Alert, HistoryEntry, Kind, Provenance, Severity, State
from app.services.alerts import AlertService
from app.services.events import build_event, event_id
from app.services.ports import PublishFailed, StoreFailed
from tests.integration import stack
from tests.integration.stack import needs_stack
from tests.support import FakePublisher

pytestmark = needs_stack

T0 = datetime(2026, 10, 20, 8, 1, tzinfo=UTC)


@pytest.fixture
def store():
    real = PostgresAlertStore(stack.PG_URL, timeout_s=15)
    yield real
    real.close()


def an_alert(run_id: str, n: int = 1, segment: str = "ROAD_001", kind=Kind.CONGESTION) -> Alert:
    return Alert(
        alert_id=f"00000000-0000-4000-8000-{n:012d}",
        rule_id="congestion.persistante",
        kind=kind,
        road_segment_id=segment,
        intersection_id="INT_01",
        provenance=Provenance("SIMULATED", run_id, "heure-de-pointe", 42),
        severity=Severity.WARNING,
        state=State.CREATED,
        opened_at=T0,
        correlation_id="corr-it",
        updated_at=T0,
    )


def test_the_three_rules_of_the_migration_are_there_and_readable(store):
    rules = {r.rule_id: r for r in store.rules()}
    assert set(rules) == {"congestion.persistante", "anomalie.circulation", "capteur.muet"}
    assert rules["congestion.persistante"].min_gap_s == 300
    assert rules["capteur.muet"].params == {"silence_s": 60}


def test_an_alert_is_written_and_read_back_with_its_full_provenance(store, run_id):
    alert = an_alert(run_id)
    with store.transaction() as tx:
        assert tx.insert(alert)
    found, history = store.get_alert(alert.alert_id)
    assert found.provenance == alert.provenance  # scenario_id et seed : migration 0008
    assert (found.cause, found.state, found.opened_at) == ("UNKNOWN", State.CREATED, T0)
    assert history == []


def test_the_database_refuses_a_negative_seed_and_a_malformed_scenario(run_id):
    """Les contraintes de la migration 0008 sont réelles."""
    with stack.admin() as connection:
        for column, value in (
            ("seed", -1),
            ("scenario_id", "Mauvais Scénario"),
            ("dataset_id", "A B"),
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "INSERT INTO alertes.alert (rule_id, kind, road_segment_id, intersection_id, "  # noqa: S608
                    f"run_id, source_type, severity, opened_at, {column}) VALUES "
                    "('congestion.persistante', 'CONGESTION', 'ROAD_009', 'INT_01', %s, "
                    "'SIMULATED', 'INFO', now(), %s)",
                    (run_id, value),
                )


def test_one_unresolved_alert_per_kind_segment_and_run_and_a_new_one_after_resolution(
    store, run_id
):
    """RG-16 / EXG-ALE-01 : l'index unique partiel, éprouvé dans la vraie base."""
    first = an_alert(run_id, 1)
    # même type, même tronçon, même run ; ouverte plus tard (après la résolution de la première)
    second = an_alert(run_id, 2).evolve(opened_at=T0 + timedelta(minutes=10))
    other_segment = an_alert(run_id, 3, segment="ROAD_002")
    other_kind = an_alert(run_id, 4, kind=Kind.SENSOR_FAULT)
    with store.transaction() as tx:
        assert tx.insert(first) is True
        assert tx.insert(second) is False
        assert tx.insert(other_segment) is True
        assert tx.insert(other_kind) is True
    with store.transaction() as tx:
        resolved = first.evolve(
            state=State.RESOLVED, resolved_at=T0 + timedelta(minutes=5), resolution="AUTO"
        )
        tx.update(resolved)
        assert tx.insert(second) is True  # l'épisode précédent est clos : un nouveau peut s'ouvrir
    with store.transaction() as tx:
        assert (
            tx.open_alert(Kind.CONGESTION, "ROAD_001", run_id, lock=False).alert_id
            == second.alert_id
        )
        assert tx.last_alert(Kind.CONGESTION, "ROAD_001", run_id).alert_id == second.alert_id


def test_a_failed_event_write_leaves_no_alert_and_no_history_in_the_real_database(store, run_id):
    """RG-17 : une seule transaction. L'événement refusé par la base (UNIQUE) annule aussi "
    "l'alerte."""
    alert = an_alert(run_id)
    event = build_event(alert, None, T0)
    with store.transaction() as tx:  # un premier événement avec cet identifiant existe déjà
        tx.add_outbox("alerts.events", "INT_01", event_id(alert.alert_id, State.CREATED), event)
    with pytest.raises(StoreFailed), store.transaction() as tx:
        tx.insert(alert)
        tx.add_history(alert.alert_id, HistoryEntry(None, State.CREATED, T0, "system"))
        tx.add_outbox("alerts.events", "INT_01", event_id(alert.alert_id, State.CREATED), event)
    assert store.get_alert(alert.alert_id) is None
    assert (
        stack.rows("SELECT 1 FROM alertes.alert_history WHERE alert_id = %s::uuid", alert.alert_id)
        == []
    )


def test_the_state_checks_of_the_database_catch_an_inconsistent_resolution(store, run_id):
    alert = an_alert(run_id)
    with store.transaction() as tx:
        tx.insert(alert)
    with pytest.raises(StoreFailed), store.transaction() as tx:
        tx.update(alert.evolve(state=State.RESOLVED))  # RESOLVED sans resolved_at ni resolution
    with pytest.raises(StoreFailed), store.transaction() as tx:
        tx.update(
            alert.evolve(
                state=State.RESOLVED, resolved_at=T0 - timedelta(hours=1), resolution="AUTO"
            )
        )  # resolved_at < opened_at
    assert store.get_alert(alert.alert_id)[0].state is State.CREATED


def test_the_service_account_cannot_read_the_warehouse_of_another_service(store):
    """ADR-008, règle 1 : un service n'écrit ni ne lit le schéma d'un autre."""
    with psycopg.connect(stack.PG_URL) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT 1 FROM dwh.fact_traffic_window LIMIT 1")


def test_the_outbox_publishes_each_event_exactly_once_even_with_two_relays(store, run_id):
    """`FOR UPDATE SKIP LOCKED` : deux relais en parallèle ne se marchent pas dessus."""
    with store.transaction() as tx:
        for n in range(1, 41):
            alert = an_alert(run_id, n, segment=f"ROAD_{n:03d}")
            tx.add_outbox(
                "alerts.events", "INT_01", f"it-{run_id}-{n}", build_event(alert, None, T0)
            )
    published: list[str] = []
    lock = threading.Lock()

    def relay():
        mine = PostgresAlertStore(stack.PG_URL, timeout_s=15)
        try:
            while True:

                def publish(row):
                    if row.event_id.startswith(f"it-{run_id}-"):
                        with lock:
                            published.append(row.event_id)

                if mine.relay_outbox(publish, limit=7) == 0:
                    return
        finally:
            mine.close()

    threads = [threading.Thread(target=relay) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert sorted(published) == sorted(f"it-{run_id}-{n}" for n in range(1, 41))
    assert (
        stack.rows(
            "SELECT count(*) AS n FROM alertes.outbox_event WHERE event_id LIKE %s AND "
            "published_at IS NULL",
            f"it-{run_id}-%",
        )[0]["n"]
        == 0
    )


def test_events_stay_in_the_database_while_the_bus_is_down_then_leave_in_order(store, run_id):
    """ADR-009 : si Kafka est en panne, rien n'est perdu ; au retour, l'ordre d'écriture est "
    "gardé."""
    service = AlertService(store)
    alert = an_alert(run_id)
    with store.transaction() as tx:
        tx.insert(alert)
        service._record(tx, alert, None, T0, "system", None)
    service.mark_notified(alert.alert_id)
    down, up = FakePublisher(), FakePublisher()
    down.fail = True
    from app.services.relay import OutboxRelay

    with pytest.raises(PublishFailed):
        OutboxRelay(store, down).run_once()
    mine = stack.rows(
        "SELECT published_at FROM alertes.outbox_event WHERE "
        "payload->'data'->'provenance'->>'run_id' = %s",
        run_id,
    )
    assert len(mine) == 2 and all(row["published_at"] is None for row in mine)
    OutboxRelay(store, up).run_once()
    assert [e["data"]["state"] for e in up.on("alerts.events")] == ["CREATED", "NOTIFIED"]
    assert all(
        row["published_at"] is not None
        for row in stack.rows(
            "SELECT published_at FROM alertes.outbox_event "
            "WHERE payload->'data'->'provenance'->>'run_id' = %s",
            run_id,
        )
    )


def test_a_rule_change_is_merged_in_the_database_and_stamped(store):
    before = {r.rule_id: r for r in store.rules()}["anomalie.circulation"]
    try:
        changed = store.update_rule(
            "anomalie.circulation", enabled=None, params={"queue_min_m": 99.5}, min_gap_s=None
        )
        assert changed.params == {"min_windows": 3, "queue_min_m": 99.5}  # fusion, pas remplacement
        assert changed.updated_at > before.updated_at
    finally:
        store.update_rule(
            "anomalie.circulation", enabled=before.enabled, params=None, min_gap_s=before.min_gap_s
        )
        with stack.admin() as connection:
            connection.execute(
                "UPDATE alertes.alert_rule SET params = %s::jsonb WHERE rule_id = "
                "'anomalie.circulation'",
                ('{"min_windows": 3}',),
            )


def test_listing_filters_and_keyset_pagination_on_the_real_database(store, run_id):
    from app.services.ports import AlertFilter

    with store.transaction() as tx:
        for n in range(1, 6):
            tx.insert(an_alert(run_id, n, segment=f"ROAD_{n:03d}").evolve(
                opened_at=T0 + timedelta(minutes=n)))  # fmt: skip
    mine = AlertFilter(road_segment_id=None, opened_from=T0, opened_to=T0 + timedelta(minutes=10))
    everything = [
        a for a in store.list_alerts(mine, after=None, limit=500) if a.provenance.run_id == run_id
    ]
    assert [a.road_segment_id for a in everything] == [f"ROAD_{n:03d}" for n in range(5, 0, -1)]
    page, after, seen = [], None, []
    while True:
        page = store.list_alerts(AlertFilter(road_segment_id="ROAD_003"), after=after, limit=1)
        seen += [a.alert_id for a in page if a.provenance.run_id == run_id]
        if len(page) < 1:
            break
        after = (page[-1].opened_at, page[-1].alert_id)
    assert len(seen) == 1
    first = store.list_alerts(AlertFilter(), after=None, limit=2)
    second = store.list_alerts(
        AlertFilter(), after=(first[-1].opened_at, first[-1].alert_id), limit=2
    )
    assert not {a.alert_id for a in first} & {a.alert_id for a in second}
