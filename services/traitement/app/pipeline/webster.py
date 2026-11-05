"""Plan de feux de référence : formule de Webster, déterministe (ADR-015, cas 4 ; EXG-REP-01).

Un modèle ne commande jamais seul : la durée des phases vient de ce calcul, jamais d'un score. Le
calcul est exact (fractions) et ne dépend que des entrées : mêmes charges, même plan.

Méthode `webster-v0` :

1. Charge par voie d'une approche : y = q ÷ (s × voies), q en véhicules par heure, s = 1 800
   véhicules par heure et par voie (valeur de départ).
2. Deux phases au plus : P1 donne le vert aux approches nord et sud, P2 à l'est et à l'ouest. Une
   phase est « critique » par son approche la plus chargée : y(phase) = max des y de ses approches.
3. Y = somme des y de phase, plafonnée à 0,9 (au-delà le cycle n'a plus de sens).
4. Temps perdu L = 4 s par phase. Cycle C = (1,5 × L + 5) ÷ (1 − Y), arrondi à l'entier (moitié
   vers le haut), borné à 30–120 s et au moins L plus 6 s de vert par phase.
5. Vert utile G = C − L, réparti proportionnellement à y (plus forts restes, puis ordre des
   phases), chaque vert au moins 6 s. Durée de phase = vert + 4 s perdues : la somme vaut C.

Les constantes sont des valeurs de départ ; les bornes de sécurité définitives sont celles de MS-12.
"""

from dataclasses import dataclass
from fractions import Fraction

VERSION = "webster-v0"
AXES = (("P1", ("N", "S")), ("P2", ("E", "W")))


@dataclass(frozen=True)
class WebsterParams:
    saturation_flow_per_lane_veh_h: int = 1800
    lost_time_per_phase_s: int = 4
    min_green_s: int = 6
    min_cycle_s: int = 30
    max_cycle_s: int = 120
    max_flow_ratio: Fraction = Fraction(9, 10)


@dataclass(frozen=True)
class ApproachLoad:
    approach: str  # N, E, S ou W
    flow_veh_per_min: Fraction
    lanes: int


@dataclass(frozen=True)
class PhasePlan:
    phase_id: str
    green_approaches: tuple[str, ...]
    duration_s: int


@dataclass(frozen=True)
class SignalPlan:
    cycle_s: int
    phases: tuple[PhasePlan, ...]
    flow_ratio: Fraction  # Y avant plafonnement


def _round_half_up(value: Fraction) -> int:
    return (value + Fraction(1, 2)).__floor__()


def _split(total: int, weights: list[Fraction]) -> list[int]:
    """Répartit `total` unités entiers proportionnellement aux poids (plus forts restes)."""
    weight_sum = sum(weights)
    if weight_sum == 0:
        weights, weight_sum = [Fraction(1)] * len(weights), Fraction(len(weights))
    exact = [total * w / weight_sum for w in weights]
    parts = [e.__floor__() for e in exact]
    order = sorted(range(len(parts)), key=lambda i: (-(exact[i] - parts[i]), i))
    for index in order[: total - sum(parts)]:
        parts[index] += 1
    return parts


def webster_plan(loads: list[ApproachLoad], params: WebsterParams) -> SignalPlan | None:
    """Plan de feux pour les charges données ; `None` si un seul axe est présent (une phase)."""
    by_approach = {load.approach: load for load in loads}
    phases = [(pid, tuple(a for a in axis if a in by_approach)) for pid, axis in AXES]
    phases = [(pid, approaches) for pid, approaches in phases if approaches]
    if len(phases) < 2:
        return None

    def ratio(load: ApproachLoad) -> Fraction:
        hourly = load.flow_veh_per_min * 60
        return hourly / (params.saturation_flow_per_lane_veh_h * load.lanes)

    critical = [max(ratio(by_approach[a]) for a in approaches) for _, approaches in phases]
    total_ratio = sum(critical)
    lost = params.lost_time_per_phase_s * len(phases)
    capped = min(total_ratio, params.max_flow_ratio)
    cycle0 = (Fraction(3, 2) * lost + 5) / (1 - capped)
    floor = max(params.min_cycle_s, lost + len(phases) * params.min_green_s)
    cycle = min(params.max_cycle_s, max(floor, _round_half_up(cycle0)))

    greens = _split(cycle - lost, critical)
    for index in range(len(greens)):  # un vert trop court est complété aux dépens du plus long
        while greens[index] < params.min_green_s:
            donor = max(range(len(greens)), key=lambda i: (greens[i], -i))
            if greens[donor] <= params.min_green_s:
                break  # rien à prendre : le plancher du cycle l'évite pour des réglages sains
            greens[donor] -= 1
            greens[index] += 1
    plan = tuple(
        PhasePlan(pid, approaches, green + params.lost_time_per_phase_s)
        for (pid, approaches), green in zip(phases, greens, strict=True)
    )
    return SignalPlan(cycle, plan, total_ratio)
