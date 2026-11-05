"""Types du flux : mesure nettoyée, rejet, référentiel des capteurs et des tronçons."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SensorRef:
    sensor_id: str
    road_segment_id: str
    intersection_id: str
    reporting_interval_s: int


@dataclass(frozen=True)
class SegmentRef:
    road_segment_id: str
    road_segment_key: int
    intersection_id: str
    free_flow_speed_kmh: float


@dataclass(frozen=True)
class Referential:
    """Référentiel des carrefours (`dwh.dim_*`) : reconnaître un capteur, calculer l'attendu."""

    sensors: dict[str, SensorRef] = field(default_factory=dict)
    segments: dict[str, SegmentRef] = field(default_factory=dict)

    def sensors_of(self, road_segment_id: str) -> list[SensorRef]:
        return [s for s in self.sensors.values() if s.road_segment_id == road_segment_id]

    def expected_samples(self, road_segment_id: str, window_size_s: int) -> int:
        """Mesures attendues dans une fenêtre (dictionnaire de données, section 6).

        (taille ÷ intervalle de rapport) × nombre de capteurs du tronçon.
        """
        total = sum(
            max(1, window_size_s // s.reporting_interval_s)
            for s in self.sensors_of(road_segment_id)
        )
        return max(1, total)


@dataclass(frozen=True)
class Measurement:
    """Une mesure acceptée par le nettoyage, prête à entrer dans une fenêtre."""

    id: str
    run_id: str
    source_type: str
    scenario_id: str | None
    seed: int | None
    dataset_id: str | None
    sensor_id: str
    road_segment_id: str
    intersection_id: str
    time_ms: int  # fin de l'intervalle mesuré
    interval_s: int
    vehicle_count: int
    speed_kmh: float | None
    occupancy_rate: float | None
    queue_length_m: float | None
    status: str  # VALID, PARTIAL ou SUSPECT
    flags: tuple[str, ...]
    correlation_id: str | None
    partition: int | None = None
    offset: int | None = None

    @property
    def start_ms(self) -> int:
        """Début de l'intervalle : une mesure appartient à la fenêtre qui contient ce début."""
        return self.time_ms - self.interval_s * 1000

    @property
    def provenance(self) -> dict[str, Any]:
        provenance: dict[str, Any] = {"source_type": self.source_type, "run_id": self.run_id}
        if self.scenario_id is not None:
            provenance["scenario_id"] = self.scenario_id
        if self.seed is not None:
            provenance["seed"] = self.seed
        if self.dataset_id is not None:
            provenance["dataset_id"] = self.dataset_id
        return provenance


@dataclass(frozen=True)
class Rejection:
    """Un message refusé : le motif et de quoi le tracer (jamais la valeur fautive)."""

    reason_code: str
    reason: str
    original_payload: Any  # le message tel que reçu : texte si illisible, sinon l'objet JSON
    intersection_id: str | None = None
    original_key: str | None = None
    window_start_ms: int | None = (
        None  # fenêtre d'une minute concernée, pour le compteur par fenêtre
    )
    road_segment_id: str | None = None
    partition: int | None = None
    offset: int | None = None
