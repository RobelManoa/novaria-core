"""Données communes des tests du flux : référentiel minimal et fabrique de messages `iot.raw`."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from app.flux.model import Referential, SegmentRef, SensorRef

EXAMPLES = Path(__file__).resolve().parents[5] / "contracts" / "events" / "examples"


def epoch_ms(text: str) -> int:
    return int(
        datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC).timestamp() * 1000
    )


def referential() -> Referential:
    """Un carrefour, deux tronçons : ROAD_001 (deux capteurs de 10 s), ROAD_002 (un seul)."""
    return Referential(
        sensors={
            "SENSOR_001": SensorRef("SENSOR_001", "ROAD_001", "INT_01", 10),
            "SENSOR_002": SensorRef("SENSOR_002", "ROAD_001", "INT_01", 10),
            "SENSOR_003": SensorRef("SENSOR_003", "ROAD_002", "INT_01", 10),
        },
        segments={
            "ROAD_001": SegmentRef("ROAD_001", 1, "INT_01", 50.0),
            "ROAD_002": SegmentRef("ROAD_002", 2, "INT_01", 50.0),
        },
    )


def example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def message(
    *,
    sensor: str = "SENSOR_001",
    road: str = "ROAD_001",
    time: str = "2026-10-20T08:00:10Z",
    count: int = 4,
    speed: float | None = 38.5,
    occupancy: float | None = 0.31,
    status: str = "VALID",
    flags: list[str] | None = None,
    run: str = "run-demo-0001",
) -> dict:
    """Une mesure conforme, modifiable champ par champ."""
    document = copy.deepcopy(example("mesure-valide.json"))
    data = document["data"]
    document["time"] = time
    document["id"] = f"{run}:{sensor}:{epoch_ms(time)}"
    document["source"] = f"simulateur/{run}"
    document["correlation_id"] = f"corr-{epoch_ms(time)}"
    data.update(
        sensor_id=sensor,
        road_segment_id=road,
        vehicle_count=count,
        average_speed_kmh=speed,
        occupancy_rate=occupancy,
    )
    data["quality"] = {"status": status, **({"flags": flags} if flags else {})}
    data["provenance"]["run_id"] = run
    return document


def raw(document: dict) -> bytes:
    return json.dumps(document).encode("utf-8")


# ----------------------------------------------------------------------- doublures du processeur

T0 = epoch_ms("2026-10-20T08:00:00Z")


def iso(seconds: float) -> str:
    """Instant UTC à `seconds` secondes après 08:00:00."""
    return datetime.fromtimestamp((T0 + seconds * 1000) / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakePublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str | None, dict]] = []
        self.flushes = 0
        self.fail = False

    def publish(self, topic, key, value):
        if self.fail:
            from app.flux.ports import PublishFailed

            raise PublishFailed("broker indisponible")
        self.sent.append((topic, key, json.loads(value)))

    def flush(self):
        self.flushes += 1

    def on(self, topic: str) -> list[dict]:
        return [event for t, _, event in self.sent if t == topic]

    def keys_on(self, topic: str) -> list[str | None]:
        return [key for t, key, _ in self.sent if t == topic]


class FakeArchive:
    def __init__(self) -> None:
        self.documents: list[dict] = []

    def insert(self, document):
        self.documents.append(document)


class FakeEpisodes:
    def __init__(self) -> None:
        self.records: list = []

    def upsert(self, record):
        self.records.append(record)


class FakeStats:
    def __init__(self) -> None:
        self.rows: list[tuple[str, datetime, str | None, dict]] = []

    def add(self, kind, window_start, road_segment_id, counts):
        self.rows.append((kind, window_start, road_segment_id, dict(counts)))

    def total(self, kind: str, name: str) -> int:
        return sum(c.get(name, 0) for k, _, _, c in self.rows if k == kind)


class Clock:
    """Horloge monotone et horloge civile pilotées par le test."""

    def __init__(self, now_s: float = 3600.0) -> None:
        self.monotonic = 0.0
        self.civil = T0 / 1000 + now_s  # 09:00:00 par défaut : après toutes les mesures des tests

    def __call__(self) -> float:
        return self.monotonic

    def utc_now(self) -> datetime:
        return datetime.fromtimestamp(self.civil, UTC)


def slot(
    start_s: float,
    *,
    sensor: str = "SENSOR_003",
    road: str = "ROAD_002",
    speed: float | None = 40.0,
    count: int = 5,
    occupancy: float | None = 0.3,
) -> bytes:
    """La mesure de 10 s qui commence `start_s` secondes après 08:00:00."""
    return raw(
        message(
            sensor=sensor,
            road=road,
            time=iso(start_s + 10),
            count=count,
            speed=speed if count else None,
            occupancy=occupancy,
        )
    )


def minute_of(index: int, **kw) -> list[bytes]:
    """Les six mesures de 10 s de la minute `index` pour un capteur."""
    return [slot(index * 60 + 10 * i, **kw) for i in range(6)]
