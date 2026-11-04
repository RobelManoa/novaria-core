"""Un run : le réseau fixe, un scénario, une graine, des anomalies, déroulés intervalle par intervalle.

`Run.step()` calcule les mesures d'UN intervalle (24 capteurs) et rend, dans l'ordre de livraison, les messages qui sont
arrivés à la fin de cet intervalle, avec les lignes de vérité terrain. Un message en retard (ou un doublon décalé) attend
dans une file et sort à son heure de livraison : le flux livré n'est donc pas trié par instant d'événement, comme sur un
vrai bus. Même graine, même scénario, mêmes anomalies : mêmes messages, quelle que soit la vitesse d'exécution.
"""

import heapq
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from . import events, model
from .anomalies import TRUTH_NAMES, Anomaly, AnomalyError
from .network import INTERVAL_S, SEGMENTS
from .scenarios import SCENARIOS, Scenario

# Jamais un nom fait de points seuls (« . », « .. ») : le service écrit dans un dossier portant ce nom.
RUN_ID = re.compile(r"^(?!\.+$)[A-Za-z0-9._-]{1,80}$")
MAX_ANOMALIES = 1000  # au-delà, chaque intervalle parcourrait une liste démesurée
SCENARIO_ID = re.compile(r"^[a-z0-9_-]{1,60}$")


class Delivery(NamedTuple):
    """Un message tel qu'il est livré, avec l'instant simulé de sa livraison."""

    emit_at: datetime
    event: dict


class Tick(NamedTuple):
    instant: datetime  # fin de l'intervalle traité
    deliveries: list[Delivery]
    truth: list[dict]


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    scenario_id: str
    seed: int
    start: datetime
    end: datetime
    anomalies: tuple[Anomaly, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not RUN_ID.match(self.run_id):
            raise ValueError("run_id : de 1 à 80 caractères parmi lettres, chiffres, point, tiret et souligné, sans être fait de points seuls")
        if not SCENARIO_ID.match(self.scenario_id) or self.scenario_id not in SCENARIOS:
            raise ValueError(f"scénario inconnu : {self.scenario_id!r} (attendus : {', '.join(SCENARIOS)})")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0:
            raise ValueError("la graine est un entier positif ou nul")
        for name in ("start", "end"):
            moment = getattr(self, name)
            if moment.tzinfo is None or int(moment.timestamp()) % INTERVAL_S:
                raise ValueError(f"{name} : date UTC sur un multiple de {INTERVAL_S} s")
        if self.end <= self.start:
            raise ValueError("la fin doit suivre le début")

    @property
    def interval_count(self) -> int:
        return int((self.end - self.start).total_seconds()) // INTERVAL_S


class Run:
    def __init__(self, config: RunConfig):
        self.config = config
        self.scenario: Scenario = SCENARIOS[config.scenario_id]
        self.processed = 0
        self._anomalies: list[Anomaly] = []
        self._queue: list[tuple] = []
        self._order = 0
        self._lock = threading.Lock()
        for anomaly in config.anomalies:
            self._register(anomaly)

    # --- anomalies -----------------------------------------------------------------------------------------------
    def _register(self, anomaly: Anomaly) -> Anomaly:
        if anomaly.start is None:
            anomaly = anomaly.resolved(self.next_instant)
        elif anomaly.start < self.next_instant:
            raise AnomalyError(f"anomalie dans le passé : {anomaly.start:%Y-%m-%dT%H:%M:%SZ} (prochain intervalle : {self.next_instant:%Y-%m-%dT%H:%M:%SZ})")
        with self._lock:
            if len(self._anomalies) >= MAX_ANOMALIES:
                raise AnomalyError(f"au plus {MAX_ANOMALIES} anomalies par run")
            self._anomalies.append(anomaly)
        return anomaly

    def add_anomaly(self, anomaly: Anomaly) -> Anomaly:
        """Injection à la demande : sans date, elle touche le prochain intervalle ; elle ne change jamais le passé."""
        return self._register(anomaly)

    @property
    def anomalies(self) -> tuple[Anomaly, ...]:
        with self._lock:
            return tuple(self._anomalies)

    # --- déroulé ---------------------------------------------------------------------------------------------------
    @property
    def next_instant(self) -> datetime:
        return self.config.start + timedelta(seconds=INTERVAL_S * (self.processed + 1))

    @property
    def done(self) -> bool:
        return self.processed >= self.config.interval_count

    def _push(self, emit_at: datetime, sensor_index: int, copy_number: int, event: dict) -> None:
        self._order += 1
        heapq.heappush(self._queue, (events.instant_ms(emit_at), sensor_index, copy_number, self._order, emit_at, event))

    def _release(self, until: datetime | None) -> list[Delivery]:
        limit = None if until is None else events.instant_ms(until)
        released = []
        while self._queue and (limit is None or self._queue[0][0] <= limit):
            *_, emit_at, event = heapq.heappop(self._queue)
            released.append(Delivery(emit_at, event))
        return released

    def step(self) -> Tick:
        instant = self.next_instant
        self.processed += 1
        anomalies = self.anomalies
        previous = instant - timedelta(seconds=INTERVAL_S)
        truth: list[dict] = []
        for index, segment in enumerate(SEGMENTS):
            mine = [a for a in anomalies if a.sensor_id == segment.sensor_id]
            active = [a for a in mine if a.covers(instant)]
            reading = model.read(self.config.seed, self.scenario, segment, instant)
            event_id = events.event_id(self.config.run_id, segment.sensor_id, instant)
            row = {
                "event_id": event_id,
                "run_id": self.config.run_id,
                "scenario_id": self.config.scenario_id,
                "sensor_id": segment.sensor_id,
                "road_segment_id": segment.road_segment_id,
                "intersection_id": segment.intersection_id,
                "time": events.utc_text(instant),
                "label_state": reading.label_state,
            }
            if any(a.kind == "muet" for a in active):
                truth.append({**row, "emitted": False, "emit_at": None, "anomalies": [TRUTH_NAMES["muet"]]})
                continue

            count, speed, occupancy = reading.vehicle_count, reading.speed_kmh, reading.occupancy_rate
            status, flags = "VALID", []
            if any(a.kind == "muet" and a.covers(previous) for a in mine):
                flags.append("GAP_BEFORE")  # premier message après un silence : le trou est signalé
            outlier = next((a for a in active if a.kind == "aberrante"), None)
            if outlier is not None:
                count, speed = _corrupt(outlier.variant, segment, count, speed)
                occupancy = model.occupancy(count, speed, segment.lane_count)
                status, flags = "SUSPECT", [*flags, "IMPLAUSIBLE_VALUE"]
            event = events.build_event(
                run_id=self.config.run_id, scenario_id=self.config.scenario_id, seed=self.config.seed, segment=segment,
                instant=instant, vehicle_count=count, speed_kmh=speed, occupancy_rate=occupancy,
                queue_length_m=reading.queue_length_m, quality_block=events.quality(status, flags),
            )
            late = next((a for a in active if a.kind == "retard"), None)
            emit_at = instant + timedelta(seconds=late.delay_s if late else 0)
            self._push(emit_at, index, 0, event)
            duplicate = next((a for a in active if a.kind == "doublon"), None)
            if duplicate is not None:
                for copy in range(1, duplicate.copies + 1):
                    self._push(emit_at + timedelta(seconds=duplicate.lag_s), index, copy, event)
            names = [TRUTH_NAMES[a.kind] for a in (outlier, duplicate, late) if a is not None]
            truth.append({**row, "emitted": True, "emit_at": events.utc_text(emit_at), "anomalies": names})
        return Tick(instant, self._release(instant), truth)

    def finish(self) -> list[Delivery]:
        """Livre ce qui attend encore (messages en retard dont l'heure tombe après la fin du run)."""
        return self._release(None)


def _corrupt(variant: str, segment, count: int, speed: float) -> tuple[int, float]:
    """Valeurs qui déclenchent la règle DQ-05 (plausibles en forme, douteuses) sans sortir des bornes du contrat."""
    if variant == "vitesse":
        # Plus de 1,5 fois la vitesse fluide ; il faut au moins un véhicule, car le contrat impose une vitesse nulle sans véhicule
        return max(count, 1), min(200.0, round(segment.free_flow_speed_kmh * 1.8, 1))
    if variant == "debit":
        return segment.lane_count * 13, speed  # 78 véhicules par minute et par voie sur une voie, plus de 40
    return max(count, 1), 0.0  # vitesse nulle alors que des véhicules sont passés


def default_config(scenario_id: str, seed: int, run_id: str | None = None, start: datetime | None = None,
                   end: datetime | None = None, duration_s: int | None = None,
                   anomalies: tuple[Anomaly, ...] = ()) -> RunConfig:
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise ValueError(f"scénario inconnu : {scenario_id!r} (attendus : {', '.join(SCENARIOS)})")
    first = start or scenario.default_start()
    last = end or first + timedelta(seconds=duration_s or scenario.duration_s)
    return RunConfig(run_id or f"run-{scenario_id}-{seed}", scenario_id, seed, first.astimezone(UTC), last.astimezone(UTC), anomalies)
