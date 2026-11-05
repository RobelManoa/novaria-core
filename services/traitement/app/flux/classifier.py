"""État de congestion stabilisé d'un tronçon (ADR-028) : hystérésis sur le ratio de vitesse.

La fonction `advance` est pure : elle reçoit l'état précédent et la fenêtre d'une minute, et rend
l'état suivant. Chaque série de fenêtres consécutives (`slow`, `congested`, `mid`, `free`) ne
dépend que des ratios ; c'est l'état courant qui décide laquelle compte (un seuil franchi compte
pour chaque transition qu'il concerne, sans être « consommé » par une autre).

Choix d'interprétation, à confirmer par la relecture (docs/03-donnees/flux.md, section 6) :

- la première fenêtre complète sort de `UNKNOWN` et compte déjà dans les séries ;
- après un trou de données pendant un ralentissement ou une congestion, l'état n'est pas remis à
  `FREE_FLOW` : la première fenêtre complète est reclassée avec les seuils d'entrée (sous 0,35 :
  `CONGESTED`, sous 0,60 : `SLOW`, sinon `FREE_FLOW`), comme le propose le dictionnaire de données
  (section 12, « Retour de UNKNOWN et épisodes ») ;
- une fenêtre de complétude insuffisante donne `UNKNOWN` et interrompt toutes les séries ;
- une route vide (aucun véhicule) est fluide : elle compte pour la reprise, jamais pour la
  dégradation ; une vitesse absente malgré des véhicules n'apporte aucune preuve et interrompt
  les séries sans changer l'état.
"""

from dataclasses import dataclass, replace

from .rules import DEFAULT_THRESHOLDS, Thresholds

DEGRADED = ("SLOW", "CONGESTED")


@dataclass(frozen=True)
class Observation:
    """La fenêtre d'une minute vue par le classificateur."""

    start_ms: int
    completeness: float
    speed_ratio: float | None
    vehicle_count: int


@dataclass(frozen=True)
class Hysteresis:
    """L'état stabilisé et les séries en cours, avec ce qu'il faut pour dater les épisodes."""

    state: str = "UNKNOWN"
    slow: int = 0  # fenêtres consécutives sous le seuil de ralentissement
    slow_since: int | None = None  # début de la première fenêtre de cette série
    slow_min: float | None = None  # plus faible ratio de cette série
    congested: int = 0  # fenêtres consécutives sous le seuil de congestion
    mid: int = 0  # fenêtres consécutives au-dessus du seuil de reprise vers SLOW
    free: int = 0  # fenêtres consécutives au-dessus du seuil de retour au fluide
    free_since: int | None = None
    gap_since: int | None = None  # début de la première fenêtre UNKNOWN de la série en cours
    resume: str | None = None  # état stabilisé juste avant le trou (pendant UNKNOWN seulement)


def _streak(previous: int, holds: bool) -> int:
    return previous + 1 if holds else 0


def advance(
    h: Hysteresis, obs: Observation, thresholds: Thresholds = DEFAULT_THRESHOLDS
) -> Hysteresis:
    if obs.completeness < thresholds.min_completeness:
        if h.state == "UNKNOWN":
            return Hysteresis(state="UNKNOWN", gap_since=h.gap_since, resume=h.resume)
        return Hysteresis(state="UNKNOWN", gap_since=obs.start_ms, resume=h.state)

    if obs.speed_ratio is not None:
        ratio: float | None = obs.speed_ratio
    elif obs.vehicle_count == 0:
        ratio = float("inf")  # route vide : fluide
    else:
        ratio = None  # des véhicules sans vitesse : aucune preuve

    resuming = h.state == "UNKNOWN" and h.resume in DEGRADED
    if resuming and ratio is None:
        return replace(h, slow=0, congested=0, mid=0, free=0)  # pas de preuve : on attend
    if h.state == "UNKNOWN":
        entry = _entry_state(ratio, thresholds) if resuming else "FREE_FLOW"
        base = replace(h, state=entry, gap_since=None, resume=None)
    else:
        base = h
    if ratio is None:
        return Hysteresis(state=base.state)

    slow = _streak(base.slow, ratio < thresholds.slow_below)
    free = _streak(base.free, ratio > thresholds.free_above)
    current = replace(
        base,
        slow=slow,
        slow_since=(obs.start_ms if base.slow == 0 else base.slow_since) if slow else None,
        slow_min=(ratio if base.slow == 0 else min(base.slow_min or ratio, ratio))
        if slow
        else None,
        congested=_streak(base.congested, ratio < thresholds.congested_below),
        mid=_streak(base.mid, ratio > thresholds.recover_to_slow_above),
        free=free,
        free_since=(obs.start_ms if base.free == 0 else base.free_since) if free else None,
    )
    return replace(current, state=_next_state(current, thresholds))


def _entry_state(ratio: float | None, th: Thresholds) -> str:
    """Reclassement d'une fenêtre unique avec les seuils d'entrée (retour après un trou)."""
    if ratio is not None and ratio < th.congested_below:
        return "CONGESTED"
    if ratio is not None and ratio < th.slow_below:
        return "SLOW"
    return "FREE_FLOW"


def _next_state(h: Hysteresis, th: Thresholds) -> str:
    degrade, recover = th.degrade_windows, th.recover_windows
    if h.state == "FREE_FLOW":
        if h.congested >= degrade:
            return "CONGESTED"
        return "SLOW" if h.slow >= degrade else "FREE_FLOW"
    if h.state == "SLOW":
        if h.congested >= degrade:
            return "CONGESTED"
        return "FREE_FLOW" if h.free >= recover else "SLOW"
    if h.free >= recover:  # CONGESTED
        return "FREE_FLOW"
    return "SLOW" if h.mid >= recover else "CONGESTED"
