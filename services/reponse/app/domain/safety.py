"""Garde-fous de sécurité des feux : le domaine pur, sans horloge ni bus ni base (EXG-REP-02).

Une recommandation du traitement et une commande d'un opérateur passent par **les mêmes règles**
avant d'atteindre le contrôleur. La liste complète, avec leur raison, est dans
`docs/03-donnees/feux.md`
(section 3) ; chaque règle porte ici un code stable, repris par `signal.status` (`refusal_reason`)
et par le journal d'audit.

| Code | Règle |
|---|---|
| `CONFLICTING_GREENS` | Deux approches qui se croisent ne sont jamais au vert ensemble |
| `PHASE_LAYOUT_MISMATCH` | Les phases d'un plan sont celles du carrefour (ids, approches) |
| `PHASE_TOO_SHORT` / `PHASE_TOO_LONG` | Une phase dure entre `MIN_PHASE_S` et `MAX_PHASE_S` |
| `CYCLE_OUT_OF_BOUNDS` / `CYCLE_MISMATCH` | Le cycle, somme des phases, reste dans ses bornes |

Les règles qui dépendent de l'état du contrôleur (durée minimale écoulée, dégagement en cours,
commande déjà en cours) sont dans `controller.py`.
"""

from collections.abc import Sequence
from dataclasses import dataclass

# Durées en secondes. `MIN_PHASE_S` = 6 s de vert minimal + `ALL_RED_S` de dégagement : ce sont les
# valeurs de départ du calcul de Webster du traitement (`webster.py`), qu'on ne peut donc pas
# contredire. Elles sont à valider (points ouverts S2 et S3).
ALL_RED_S = 4  # fin de chaque phase : tout est au rouge, le temps que le carrefour se vide
MIN_PHASE_S = 10
MAX_PHASE_S = 90
MIN_CYCLE_S = 30
MAX_CYCLE_S = 120

APPROACHES = ("N", "E", "S", "W")
# Les approches qui se croisent : l'axe nord-sud croise l'axe est-ouest. Deux approches d'un même
# axe (N et S, E et W) peuvent être vertes ensemble.
CONFLICTS = frozenset(frozenset((a, b)) for a in "NS" for b in "EW")

CONFLICTING_GREENS = "CONFLICTING_GREENS"
PHASE_LAYOUT_MISMATCH = "PHASE_LAYOUT_MISMATCH"
PHASE_TOO_SHORT = "PHASE_TOO_SHORT"
PHASE_TOO_LONG = "PHASE_TOO_LONG"
CYCLE_OUT_OF_BOUNDS = "CYCLE_OUT_OF_BOUNDS"
CYCLE_MISMATCH = "CYCLE_MISMATCH"


@dataclass(frozen=True)
class Phase:
    phase_id: str
    green_approaches: tuple[str, ...]
    duration_s: int


@dataclass(frozen=True)
class Violation:
    code: str
    message: str


# La structure d'un carrefour : ses phases dans l'ordre, avec les approches de chacune.
Layout = tuple[tuple[str, tuple[str, ...]], ...]
DEFAULT_LAYOUT: Layout = (("P1", ("N", "S")), ("P2", ("E", "W")))


def conflicting_pairs(approaches: Sequence[str]) -> list[tuple[str, str]]:
    found = []
    for i, a in enumerate(approaches):
        for b in approaches[i + 1 :]:
            if frozenset((a, b)) in CONFLICTS:
                found.append((a, b))
    return found


def validate_layout(layout: Layout) -> None:
    """Refuse au démarrage une structure de carrefour qui serait elle-même dangereuse."""
    ids = [phase_id for phase_id, _ in layout]
    if len(layout) < 2 or len(set(ids)) != len(ids):
        raise ValueError("un carrefour a au moins deux phases, d'identifiants distincts")
    served: set[str] = set()
    for phase_id, approaches in layout:
        if not approaches or not set(approaches) <= set(APPROACHES):
            raise ValueError(f"phase {phase_id} : approches inconnues ou absentes")
        if conflicting_pairs(approaches):
            raise ValueError(f"phase {phase_id} : des approches qui se croisent sont au vert")
        served |= set(approaches)
    if served != set(APPROACHES):
        raise ValueError("toute approche doit être servie par une phase")


def check_duration(duration_s: int) -> Violation | None:
    if duration_s < MIN_PHASE_S:
        return Violation(
            PHASE_TOO_SHORT, f"durée de phase {duration_s} s sous le minimum de {MIN_PHASE_S} s"
        )
    if duration_s > MAX_PHASE_S:
        return Violation(
            PHASE_TOO_LONG, f"durée de phase {duration_s} s au-dessus du maximum de {MAX_PHASE_S} s"
        )
    return None


def check_plan(phases: Sequence[Phase], cycle_s: int, layout: Layout) -> list[Violation]:
    """Tous les défauts d'un plan proposé, le plus grave d'abord ; vide si le plan est sûr."""
    violations: list[Violation] = []
    for phase in phases:
        pairs = conflicting_pairs(phase.green_approaches)
        if pairs:
            crossing = ", ".join(f"{a}/{b}" for a, b in pairs)
            violations.append(
                Violation(
                    CONFLICTING_GREENS,
                    f"phase {phase.phase_id} : approches qui se croisent au vert ({crossing})",
                )
            )
    proposed = tuple((p.phase_id, tuple(sorted(p.green_approaches))) for p in phases)
    expected = tuple((phase_id, tuple(sorted(approaches))) for phase_id, approaches in layout)
    if proposed != expected:
        violations.append(
            Violation(
                PHASE_LAYOUT_MISMATCH,
                "les phases ne sont pas celles du carrefour (identifiants, approches ou ordre)",
            )
        )
    for phase in phases:
        problem = check_duration(phase.duration_s)
        if problem:
            violations.append(
                Violation(problem.code, f"phase {phase.phase_id} : {problem.message}")
            )
    total = sum(p.duration_s for p in phases)
    if total != cycle_s:
        violations.append(
            Violation(
                CYCLE_MISMATCH,
                f"le cycle annoncé ({cycle_s} s) n'est pas la somme des phases ({total} s)",
            )
        )
    if not MIN_CYCLE_S <= total <= MAX_CYCLE_S:
        violations.append(
            Violation(
                CYCLE_OUT_OF_BOUNDS, f"cycle de {total} s hors de {MIN_CYCLE_S} à {MAX_CYCLE_S} s"
            )
        )
    return violations
