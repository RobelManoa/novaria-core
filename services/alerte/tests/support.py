"""Indicateurs d'essai, faux bus, fausse base et canal de notification (tests d'alerte, MS-11).

`FakeStore` imite fidèlement ce que la base garantit : l'index unique partiel des alertes non
résolues, l'atomicité d'une transaction (tout est annulé si elle échoue), l'ordre de la boîte
d'envoi. Les tests du comportement réel de la base sont dans `tests/integration/`.
"""

import copy
import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain.model import Alert, HistoryEntry, Kind, Rule, State
from app.domain.rules import RuleEngine
from app.services.alerts import AlertService
from app.services.ingestion import IndicatorHandler
from app.services.notifier import Notifier
from app.services.ports import (
    AlertFilter,
    NotFound,
    NotificationFailed,
    OutboxRow,
    PublishFailed,
    StoreFailed,
)
from app.services.relay import OutboxRelay
from tests.contract.conftest import CONTRACTS

EXAMPLES = CONTRACTS / "events" / "examples"
BASE = datetime(2026, 10, 20, 8, 0, 0, tzinfo=UTC)
NOW = datetime(2026, 11, 5, 9, 30, 0, tzinfo=UTC)

# Les trois règles de la migration 0003.
SEED_RULES = [
    Rule("congestion.persistante", Kind.CONGESTION, True,
         {"state": "CONGESTED", "min_windows": 1}, 300, BASE),
    Rule("anomalie.circulation", Kind.TRAFFIC_ANOMALY, True, {"min_windows": 3}, 600, BASE),
    Rule("capteur.muet", Kind.SENSOR_FAULT, True, {"silence_s": 60}, 900, BASE),
]  # fmt: skip


def example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def indicator(
    minute: int,
    state: str = "FREE_FLOW",
    *,
    ratio: float | None = 0.9,
    samples: int = 6,
    occupancy: float | None = None,
    queue: float | None = None,
    run: str = "run-test",
    segment: str = "ROAD_001",
    intersection: str = "INT_01",
    size: int = 60,
) -> dict:
    """Un indicateur conforme, pour la fenêtre commençant à `BASE + minute` minutes."""
    start = BASE + timedelta(minutes=minute)
    event = example("indicateur-congestion.json")
    event["id"] = f"{run}:{segment}:{size}:{int(start.timestamp() * 1000)}"
    event["time"] = stamp(start + timedelta(seconds=size))
    event["subject"] = intersection
    event["correlation_id"] = f"corr-{int(start.timestamp() * 1000)}"
    data = event["data"]
    data.update(
        road_segment_id=segment,
        intersection_id=intersection,
        window_start=stamp(start),
        window_size_s=size,
        congestion_state=state,
        sample_count=samples,
        expected_sample_count=size // 10,
        occupancy_rate=occupancy,
        max_queue_length_m=queue,
    )
    data["provenance"]["run_id"] = run
    if samples == 0 or ratio is None:  # aucun véhicule observé : ni vitesse ni ratio
        data.update(vehicle_count=0, flow_veh_per_min=0.0, average_speed_kmh=None, speed_ratio=None)
    else:
        data.update(
            vehicle_count=9, flow_veh_per_min=9.0, average_speed_kmh=round(50 * ratio, 1),
            speed_ratio=ratio,
        )  # fmt: skip
    return event


def congested(minute: int, **changes: Any) -> dict:
    return indicator(minute, "CONGESTED", ratio=changes.pop("ratio", 0.2), **changes)


def silent(minute: int, **changes: Any) -> dict:
    """Une fenêtre vide : un capteur qui se tait (état UNKNOWN, aucune mesure)."""
    return indicator(minute, "UNKNOWN", ratio=None, samples=0, **changes)


def body(event: object) -> bytes:
    return json.dumps(event).encode("utf-8")


def assert_published_conforms(topic: str, event: dict) -> None:
    """Banc de conformité du dépôt : droit de publier, type du sujet, contrat respecté."""
    from conformance import assert_publication  # contracts/ est sur sys.path (tests/contract)

    assert_publication("alerte", topic, event)


def contract_errors(event: dict) -> list[str]:
    from validate_events import validate_event

    return validate_event(event)


# ---------------------------------------------------------------------------------------- horloge
class Clock:
    """Horloge réglable : `now()` ne bouge que si le test l'avance."""

    def __init__(self, start: datetime = NOW) -> None:
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


# ---------------------------------------------------------------------------------- faux bus, canal
class FakePublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str | None, dict]] = []
        self.fail = False
        self.flushes = 0

    def publish(self, topic: str, key: str | None, value: bytes) -> None:
        if self.fail:
            raise PublishFailed("panne simulée")
        self.sent.append((topic, key, json.loads(value)))

    def flush(self) -> None:
        self.flushes += 1

    def on(self, topic: str) -> list[dict]:
        return [event for t, _, event in self.sent if t == topic]


class FakeChannel:
    def __init__(self) -> None:
        self.delivered: list[Alert] = []
        self.fail = False

    def send(self, alert: Alert) -> None:
        if self.fail:
            raise NotificationFailed("canal en panne")
        self.delivered.append(alert)


# -------------------------------------------------------------------------------------- fausse base
@dataclass
class _Data:
    alerts: dict[str, Alert] = field(default_factory=dict)
    history: list[tuple[str, HistoryEntry]] = field(default_factory=list)
    outbox: list[dict[str, Any]] = field(default_factory=list)  # + published: bool
    rules: list[Rule] = field(default_factory=lambda: list(SEED_RULES))


class _Tx:
    def __init__(self, data: _Data, fail_outbox: bool) -> None:
        self._d = data
        self._fail_outbox = fail_outbox

    def _matching(self, kind: Kind, segment: str, run_id: str) -> list[Alert]:
        return [
            a for a in self._d.alerts.values()
            if (a.kind, a.road_segment_id, a.provenance.run_id) == (kind, segment, run_id)
        ]  # fmt: skip

    def last_alert(self, kind: Kind, segment: str, run_id: str) -> Alert | None:
        found = self._matching(kind, segment, run_id)
        return max(found, key=lambda a: a.opened_at, default=None)

    def open_alert(self, kind: Kind, segment: str, run_id: str, *, lock: bool) -> Alert | None:
        return next(
            (a for a in self._matching(kind, segment, run_id) if a.state != State.RESOLVED), None
        )

    def get(self, alert_id: str, *, lock: bool) -> Alert | None:
        return self._d.alerts.get(alert_id)

    def insert(self, alert: Alert) -> bool:
        if self.open_alert(alert.kind, alert.road_segment_id, alert.provenance.run_id, lock=False):
            return False  # l'index unique partiel refuse
        self._d.alerts[alert.alert_id] = alert
        return True

    def update(self, alert: Alert) -> None:
        self._d.alerts[alert.alert_id] = alert

    def add_history(self, alert_id: str, entry: HistoryEntry) -> None:
        self._d.history.append((alert_id, entry))

    def add_outbox(self, topic: str, key: str, event_id: str, payload: dict[str, Any]) -> None:
        if self._fail_outbox:
            raise StoreFailed("écriture de la boîte d'envoi refusée")
        if any(row["event_id"] == event_id for row in self._d.outbox):
            raise StoreFailed("event_id déjà présent (UNIQUE)")
        self._d.outbox.append(
            {"outbox_id": len(self._d.outbox) + 1, "topic": topic, "key": key,
             "event_id": event_id, "payload": payload, "published": False}
        )  # fmt: skip


class FakeStore:
    def __init__(self) -> None:
        self.data = _Data()
        self.fail_outbox = False
        self.down = False
        self.transactions = 0

    @contextmanager
    def transaction(self) -> Iterator[_Tx]:
        if self.down:
            raise StoreFailed("base indisponible")
        self.transactions += 1
        snapshot = copy.deepcopy(self.data)
        try:
            yield _Tx(self.data, self.fail_outbox)
        except BaseException:
            self.data = snapshot  # annulation : rien de la transaction n'a eu lieu
            raise

    # --- lectures / règles
    def rules(self) -> list[Rule]:
        if self.down:
            raise StoreFailed("base indisponible")
        return list(self.data.rules)

    def update_rule(self, rule_id: str, *, enabled, params, min_gap_s) -> Rule:
        for index, rule in enumerate(self.data.rules):
            if rule.rule_id == rule_id:
                changed = Rule(
                    rule_id, rule.kind, rule.enabled if enabled is None else enabled,
                    {**rule.params, **params} if params is not None else rule.params,
                    rule.min_gap_s if min_gap_s is None else min_gap_s, NOW,
                )  # fmt: skip
                self.data.rules[index] = changed
                return changed
        raise NotFound(rule_id)

    def pending_notification(self, limit: int) -> list[Alert]:
        found = [a for a in self.data.alerts.values() if a.state == State.CREATED]
        return sorted(found, key=lambda a: (a.opened_at, a.alert_id))[:limit]

    def list_alerts(self, filters: AlertFilter, *, after, limit: int) -> list[Alert]:
        def keep(a: Alert) -> bool:
            return all([
                filters.state is None or a.state == filters.state,
                filters.kind is None or a.kind == filters.kind,
                filters.severity is None or a.severity.value == filters.severity,
                filters.intersection_id is None or a.intersection_id == filters.intersection_id,
                filters.road_segment_id is None or a.road_segment_id == filters.road_segment_id,
                filters.opened_from is None or a.opened_at >= filters.opened_from,
                filters.opened_to is None or a.opened_at <= filters.opened_to,
            ])  # fmt: skip

        ordered = sorted(
            filter(keep, self.data.alerts.values()),
            key=lambda a: (a.opened_at, a.alert_id), reverse=True,
        )  # fmt: skip
        if after is not None:
            ordered = [a for a in ordered if (a.opened_at, a.alert_id) < after]
        return ordered[:limit]

    def get_alert(self, alert_id: str):
        alert = self.data.alerts.get(alert_id)
        if alert is None:
            return None
        return alert, [entry for aid, entry in self.data.history if aid == alert_id]

    def relay_outbox(self, publish: Callable[[OutboxRow], None], *, limit: int) -> int:
        done = 0
        for row in [r for r in self.data.outbox if not r["published"]][:limit]:
            publish(OutboxRow(row["outbox_id"], row["topic"], row["key"], row["event_id"],
                              row["payload"]))  # fmt: skip
            row["published"] = True
            done += 1
        return done

    # --- aides de test
    def alerts(self, kind: Kind | None = None) -> list[Alert]:
        found = list(self.data.alerts.values())
        return [a for a in found if kind is None or a.kind == kind]

    def states(self, alert_id: str) -> list[str]:
        return [e.to_state.value for aid, e in self.data.history if aid == alert_id]


# ------------------------------------------------------------------------------------- assemblage
class Rig:
    """Le service entier branché sur des faux : indicateurs en entrée, événements en sortie."""

    def __init__(self) -> None:
        self.clock = Clock()
        self.store = FakeStore()
        self.publisher = FakePublisher()
        self.channel = FakeChannel()
        ids = (f"00000000-0000-4000-8000-{n:012d}" for n in range(1, 1000))
        self.service = AlertService(self.store, clock=self.clock, new_id=lambda: next(ids))
        self.engine = RuleEngine()
        self.handler = IndicatorHandler(
            self.service, self.engine, self.store.rules, self.publisher, clock=self.clock
        )
        self.notifier = Notifier(
            self.store, self.service, self.channel, retry_after_s=5.0, monotonic=self.clock_s
        )
        self.relay = OutboxRelay(self.store, self.publisher)

    def clock_s(self) -> float:
        return self.clock.current.timestamp()

    def feed(self, *events: dict):
        """Envoie des indicateurs au traitement ; rend le résultat du dernier."""
        result = None
        for event in events:
            result = self.handler.handle(body(event), b"INT_01")
        return result

    def run(self, *events: dict) -> list[dict]:
        """Un lot d'indicateurs, puis notification et publication ; rend les événements publiés."""
        self.feed(*events)
        self.relay.run_once()
        self.notifier.run_once()
        self.relay.run_once()
        return self.publisher.on("alerts.events")

    def play(self, *events: dict) -> list[dict]:
        """Comme le travailleur qui reçoit les indicateurs un à un, au fil du temps."""
        for event in events:
            self.run(event)
        return self.publisher.on("alerts.events")


def new_uuid() -> str:
    return str(uuid.uuid4())
