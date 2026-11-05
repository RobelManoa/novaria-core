"""De la fenêtre à l'événement `novaria.traffic.indicator.v1` (dictionnaire de données, section 6).

Rien n'est publié qui ne soit conforme au contrat. Une fenêtre qui ne peut pas l'être est
**retenue** (`Withheld`) avec son motif : le processeur la compte et la trace. Cas connu : une
route vide (pas de vitesse, donc pas de ratio) pendant que l'état stabilisé est encore SLOW ou
CONGESTED, car le contrat exige un ratio pour ces deux états et la règle d'ADR-028 compte la route
vide comme fluide. On n'invente pas de ratio : point ouvert pour la relecture croisée.

Arrondis : ceux des colonnes de `dwh.fact_traffic_window`, moitié vers le haut comme PostgreSQL,
sur des cumuls décimaux exacts : débit au centième, vitesse au dixième, occupation au millième, file
au dixième, ratio au millième (plafonné à 9,999, calculé sur la vitesse non arrondie). L'événement
publié, la ligne de l'entrepôt et l'API portent ainsi la même valeur, sans second arrondi, et un
recalcul SQL sur les mêmes mesures la retrouve exactement.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from pydantic import ValidationError

from app.schemas.events import IndicatorEvent

from .classifier import DEGRADED, Observation
from .model import Referential
from .rules import CLASSIFIER_VERSION
from .windows import Window

SOURCE = "traitement"
RATIO_MAX = Decimal("9.999")
MAX_REASON_ERRORS = 3


@dataclass(frozen=True)
class Indicator:
    key: str  # identifiant de l'événement : sert de clé d'idempotence
    event: dict
    window: Window


@dataclass(frozen=True)
class Withheld:
    reason_code: str
    reason: str
    window: Window


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def expected_samples(window: Window, referential: Referential) -> int:
    return referential.expected_samples(window.road_segment_id, window.size_s)


def completeness(window: Window, referential: Referential) -> float:
    return min(1.0, window.sample_count / expected_samples(window, referential))


def _round(value: Decimal | None, places: int) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def speed_ratio(window: Window, referential: Referential) -> float | None:
    segment = referential.segments.get(window.road_segment_id)
    speed = window.exact_average_speed
    if segment is None or speed is None:
        return None
    ratio = speed / Decimal(repr(segment.free_flow_speed_kmh))
    return _round(min(RATIO_MAX, ratio.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)), 3)


def observation(window: Window, referential: Referential) -> Observation:
    """Ce que le classificateur voit d'une fenêtre d'une minute."""
    return Observation(
        start_ms=window.start_ms,
        completeness=completeness(window, referential),
        speed_ratio=speed_ratio(window, referential),
        vehicle_count=window.vehicle_count,
    )


def build(window: Window, referential: Referential, state: str) -> Indicator | Withheld:
    if window.road_segment_id not in referential.segments:
        return Withheld("UNKNOWN_SEGMENT", "tronçon absent du référentiel", window)
    expected = expected_samples(window, referential)
    if window.sample_count > 2 * expected:
        reason = f"{window.sample_count} mesures pour {expected} attendues (au plus le double)"
        return Withheld("SAMPLE_OVERFLOW", reason, window)
    ratio = speed_ratio(window, referential)
    if state in DEGRADED and ratio is None:
        reason = (
            f"état {state} publié sans vitesse : le contrat exige un ratio, aucun n'est inventé"
        )
        return Withheld("DEGRADED_WITHOUT_RATIO", reason, window)

    identifier = f"{window.run_id}:{window.road_segment_id}:{window.size_s}:{window.start_ms}"
    event = {
        "id": identifier,
        "source": SOURCE,
        "type": "novaria.traffic.indicator.v1",
        "time": _iso(window.end_ms),
        "subject": window.intersection_id,
        "schema_version": "1.0",
        "correlation_id": f"corr-{window.start_ms}",
        "domain": "traffic",
        "data": {
            "road_segment_id": window.road_segment_id,
            "intersection_id": window.intersection_id,
            "window_start": _iso(window.start_ms),
            "window_size_s": window.size_s,
            "vehicle_count": window.vehicle_count,
            "flow_veh_per_min": _round(Decimal(window.vehicle_count) * 60 / window.size_s, 2),
            "average_speed_kmh": _round(window.exact_average_speed, 1),
            "occupancy_rate": _round(window.exact_occupancy, 3),
            "max_queue_length_m": _round(window.exact_max_queue, 1),
            "speed_ratio": ratio,
            "sample_count": window.sample_count,
            "expected_sample_count": expected,
            "congestion_state": state,
            "classifier_version": CLASSIFIER_VERSION,
            "provenance": window.provenance,
        },
    }
    try:
        IndicatorEvent.model_validate(event)
    except ValidationError as error:
        shown = [
            f"{'/'.join(str(p) for p in item['loc'])} : {item['msg']}"
            for item in error.errors(include_input=False)[:MAX_REASON_ERRORS]
        ]
        return Withheld("INDICATOR_INVALID", "; ".join(shown), window)
    return Indicator(identifier, event, window)
