"""Mesures d'essai et faux bus / fausse base pour les tests de la collecte (MS-08)."""

import copy
import json
import threading
import time
from datetime import UTC, datetime, timedelta

from app.services.ingestion import IngestionService, PublishFailed, StoreFailed
from tests.contract.conftest import CONTRACTS

EXAMPLES = CONTRACTS / "events" / "examples"
ORIGIN = datetime(2026, 10, 20, 8, 0, 10, tzinfo=UTC)
FIXED_NOW = datetime(2026, 11, 5, 9, 30, 0, tzinfo=UTC)


def example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def measurement(n: int = 0, sensor: int = 1, *, run_id: str = "run-test", **data_changes) -> dict:
    """Une mesure conforme (valeurs de `mesure-valide.json`), unique par (`n`, `sensor`)."""
    event = example("mesure-valide.json")
    moment = ORIGIN + timedelta(seconds=10 * n)
    sensor_id = f"SENSOR_{sensor:03d}"
    event["time"] = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    event["id"] = f"{run_id}:{sensor_id}:{int(moment.timestamp() * 1000)}"
    event["source"] = f"simulateur/{run_id}"
    event["data"]["sensor_id"] = sensor_id
    event["data"]["road_segment_id"] = f"ROAD_{sensor:03d}"
    event["data"]["provenance"]["run_id"] = run_id
    event["data"].update(data_changes)
    return event


def contract_errors(event: dict) -> list[str]:
    """Erreurs de `contracts/validate_events.py` (schéma JSON puis règles entre champs)."""
    from validate_events import (
        validate_event,
    )  # contracts/ est sur sys.path (tests/contract/conftest)

    return validate_event(event)


def assert_published_conforms(topic: str, event: dict) -> None:
    """Banc de conformité du dépôt (`contracts/conformance.py`) : droit de publier, type du sujet,
    contrat respecté, `errors.dlq` signé `collecte`."""
    from conformance import (
        assert_publication,
    )  # contracts/ est sur sys.path (tests/contract/conftest)

    assert_publication("collecte", topic, event)


def body(event: object) -> bytes:
    return json.dumps(event).encode("utf-8")


def without(event: dict, *path: str) -> dict:
    """Copie de `event` sans le champ désigné par `path` (par exemple `"data", "quality"`)."""
    clone = copy.deepcopy(event)
    node = clone
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return clone


def with_value(event: dict, path: tuple[str, ...], value: object) -> dict:
    clone = copy.deepcopy(event)
    node = clone
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return clone


class FakePublisher:
    def __init__(self, trace: list[str] | None = None) -> None:
        self.calls: list[tuple[str, str | None, bytes]] = []
        self.trace = trace if trace is not None else []
        self.fail_on: set[str] = set()  # sujets dont la publication échoue
        self.delay_s = 0.0  # durée de l'accusé du broker : de quoi laisser les fils se chevaucher
        self._lock = threading.Lock()

    def publish(self, topic: str, key: str | None, value: bytes) -> None:
        if topic in self.fail_on:
            raise PublishFailed("panne simulée")
        if self.delay_s:
            time.sleep(self.delay_s)
        with self._lock:
            self.calls.append((topic, key, value))
            self.trace.append(f"publish:{topic}")

    def events(self, topic: str) -> list[dict]:
        return [json.loads(value) for t, _, value in self.calls if t == topic]

    def keys(self, topic: str) -> list[str | None]:
        return [key for t, key, _ in self.calls if t == topic]

    def assert_all_conform(self) -> None:
        """Chaque message publié est conforme au contrat de son sujet ; la clé est son carrefour."""
        for topic, key, value in self.calls:
            event = json.loads(value)
            assert_published_conforms(topic, event)
            assert key == event["subject"]


class FakeRawStore:
    def __init__(self, trace: list[str] | None = None) -> None:
        self.documents: dict[str, dict] = {}
        self.trace = trace if trace is not None else []
        self.fail_exists = False
        self.fail_insert = False
        self._lock = threading.Lock()

    def exists(self, event_id: str) -> bool:
        if self.fail_exists:
            raise StoreFailed("panne simulée")
        return event_id in self.documents

    def insert(self, document: dict) -> bool:
        if self.fail_insert:
            raise StoreFailed("panne simulée")
        with self._lock:
            if document["id"] in self.documents:
                return False
            self.documents[document["id"]] = document
            self.trace.append("insert")
            return True


class FakeRejects:
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.fail = False

    def insert(self, document: dict) -> None:
        if self.fail:
            raise StoreFailed("panne simulée")
        self.documents.append(document)


class Rig:
    """Un service d'ingestion branché sur des faux, avec la trace de l'ordre des opérations."""

    def __init__(self, *, max_bytes: int = 65536) -> None:
        self.trace: list[str] = []
        self.publisher = FakePublisher(self.trace)
        self.raw = FakeRawStore(self.trace)
        self.rejects = FakeRejects()
        self.service = IngestionService(
            self.publisher,
            self.raw,
            self.rejects,
            max_bytes=max_bytes,
            clock=lambda: FIXED_NOW,
        )
