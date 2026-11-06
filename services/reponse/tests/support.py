"""Outils communs aux tests : horloge, constructeurs de recommandations et de commandes."""

import itertools
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta

from app.adapters.mongo_audit import InvalidCursor
from app.domain.controller import SignalController
from app.domain.model import Action, Command, Provenance, utc_stamp
from app.domain.safety import DEFAULT_LAYOUT, Phase
from app.services.ingestion import RecommendationHandler
from app.services.outbox import Outbox
from app.services.ports import AuditFailed, PublishFailed
from app.services.signals import SignalService
from app.worker.runtime import Dispatcher

T0 = datetime(2026, 10, 20, 8, 0, 0, tzinfo=UTC)
PROVENANCE = Provenance("SIMULATED", "run-1", "heure-de-pointe", 42)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


at_ = at  # alias pour les constructeurs dont un paramètre s'appelle `at`


class Clock:
    """Une horloge qu'on avance à la main ; `threading` pour les tests de concurrence."""

    def __init__(self, start: datetime = T0) -> None:
        self.now = start
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self.now

    def advance(self, seconds: float) -> datetime:
        with self._lock:
            self.now += timedelta(seconds=seconds)
            return self.now


def new_controller(*, fixed_s: int = 30, max_silence_s: int = 180, start: float = 0):
    return SignalController(
        "INT_01",
        DEFAULT_LAYOUT,
        fixed_s,
        at(start),
        PROVENANCE,
        max_silence_s=max_silence_s,
    )


def plan(p1: int = 40, p2: int = 20) -> list[Phase]:
    return [Phase("P1", ("N", "S"), p1), Phase("P2", ("E", "W"), p2)]


_ids = itertools.count(1)


def new_id() -> str:
    return str(uuid.UUID(int=next(_ids)))


def recommend(controller, now: float, phases=None, *, sequence: float | None = None, validity=300):
    """Soumet une recommandation reçue à `now` ; `sequence` : son instant d'événement."""
    phases = plan() if phases is None else phases
    return controller.on_recommendation(
        new_id(),
        at(now if sequence is None else sequence),
        phases,
        sum(p.duration_s for p in phases),
        validity,
        PROVENANCE,
        at(now),
    )


def set_phase(phase_id="P2", duration_s=30, actor="u-1", reason="essai") -> Command:
    return Command(new_id(), Action.SET_PHASE, actor, reason, phase_id, duration_s)


def resume(actor="u-1") -> Command:
    return Command(new_id(), Action.RESUME_AUTOMATIC, actor, "fin de l'essai")


# --------------------------------------------------------------------------- doubles de test
class FakeAudit:
    """Un journal en mémoire ; `down` simule MongoDB indisponible."""

    def __init__(self) -> None:
        self.entries: list[dict] = []
        self.down = False
        self.attempts = 0

    def record(self, entry: dict) -> None:
        self.attempts += 1
        if self.down:
            raise AuditFailed("ServerSelectionTimeoutError")
        self.entries.append(dict(entry))

    def history(self, intersection_id, limit, cursor):
        if self.down:
            raise AuditFailed("ServerSelectionTimeoutError")
        found = [
            e
            for e in reversed(self.entries)
            if e["action"].startswith("signal.command.")
            and e["details"]["intersection_id"] == intersection_id
        ]
        if cursor and not cursor.isdigit():
            raise InvalidCursor
        start = int(cursor) if cursor else 0
        page = found[start : start + limit]
        more = start + limit < len(found)
        return [{**e, "_id": i} for i, e in enumerate(page)], str(start + limit) if more else None

    def of(self, action_prefix: str) -> list[dict]:
        return [e for e in self.entries if e["action"].startswith(action_prefix)]


class FakePublisher:
    """Un bus en mémoire ; `down` simule Kafka indisponible."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str | None, dict]] = []
        self._staged: list = []
        self.down = False

    def publish(self, topic, key, value):
        if self.down:
            raise PublishFailed("KafkaTimeoutError")
        self._staged.append((topic, key, json.loads(value)))

    def flush(self):
        if self.down:
            self._staged = []
            raise PublishFailed("KafkaTimeoutError")
        self.sent.extend(self._staged)
        self._staged = []

    def on(self, topic: str) -> list[dict]:
        return [event for t, _, event in self.sent if t == topic]


class Rig:
    """Le service, ses faux et son horloge, assemblés comme en production."""

    def __init__(self, intersections=("INT_01", "INT_02"), *, fixed_s=30, max_silence_s=180):
        self.clock = Clock()
        self.audit = FakeAudit()
        self.publisher = FakePublisher()
        self.outbox = Outbox()
        controllers = {
            name: SignalController(
                name, DEFAULT_LAYOUT, fixed_s, self.clock(), PROVENANCE, max_silence_s=max_silence_s
            )
            for name in intersections
        }
        self.service = SignalService(controllers, self.audit, self.outbox, clock=self.clock)
        self.dispatcher = Dispatcher(self.outbox, self.publisher, self.audit, self.service)
        self.handler = RecommendationHandler(self.service, self.outbox, clock=self.clock)

    def advance(self, seconds: float) -> None:
        self.clock.advance(seconds)
        self.service.tick()

    def flush(self) -> bool:
        return self.dispatcher.drain()

    def status(self) -> list[dict]:
        return self.publisher.on("signal.status")


def recommendation_event(
    intersection="INT_01",
    phases=None,
    *,
    at: float = 0,
    validity: float = 300,
    recommendation_id: str | None = None,
    cycle: int | None = None,
) -> dict:
    phases = plan() if phases is None else phases
    rec_id = recommendation_id or new_id()
    return {
        "id": rec_id,
        "source": "traitement",
        "type": "novaria.traffic.recommendation.v1",
        "time": utc_stamp(at_(at)),
        "subject": intersection,
        "schema_version": "1.0",
        "domain": "traffic",
        "correlation_id": "corr-rec-1",
        "data": {
            "recommendation_id": rec_id,
            "intersection_id": intersection,
            "valid_until": utc_stamp(at_(at + validity)),
            "cycle_s": sum(p.duration_s for p in phases) if cycle is None else cycle,
            "phases": [
                {
                    "phase_id": p.phase_id,
                    "green_approaches": list(p.green_approaches),
                    "duration_s": p.duration_s,
                }
                for p in phases
            ],
            "method": {"kind": "WEBSTER_REFERENCE", "version": "webster-v0"},
            "model": None,
            "inputs": {
                "indicator_ids": ["ind-1"],
                "window_start": utc_stamp(at_(at - 60)),
                "window_size_s": 60,
                "congestion_state": "CONGESTED",
            },
            "provenance": {
                "source_type": "SIMULATED",
                "run_id": "run-1",
                "scenario_id": "heure-de-pointe",
                "seed": 42,
            },
        },
    }


def raw(event) -> bytes:
    return json.dumps(event).encode()
