"""Épisodes de congestion (ADR-028, dictionnaire de données 7.2) : ouverture, suivi, clôture.

Un épisode s'ouvre quand l'état stabilisé quitte le fluide pour SLOW ou CONGESTED, et se ferme au
retour à FREE_FLOW. Il est daté de la **première fenêtre dégradée** (début de la série qui a
déclenché la transition), pas de la fenêtre où l'état change : le délai de confirmation ne
décale pas l'épisode. L'identifiant dérive du run, du tronçon et du début : un rejeu retombe sur
le même épisode (clé d'unicité `road_segment_key, run_id, started_at`).

Choix pour un trou de données (à confirmer, docs/03-donnees/flux.md, section 6) : l'état devient
UNKNOWN, l'épisode reste ouvert (on ne sait pas s'il continue) et n'est pas prolongé. Au retour
des données, l'épisode est clos au début du trou ; si la dégradation continue, un nouvel épisode
s'ouvre après sa propre confirmation.
"""

import uuid
from dataclasses import dataclass, replace

from .classifier import DEGRADED, Hysteresis, Observation

WINDOW_MS = 60_000
_NAMESPACE = uuid.UUID(
    "5d3c6e0a-8b1c-5f7e-9a44-0b9f2d6c1e73"
)  # constante du projet, fixée une fois


@dataclass(frozen=True)
class EpisodeRecord:
    """Ce qu'il faut écrire dans `dwh.fact_congestion_episode` (écriture idempotente)."""

    episode_id: str
    run_id: str
    source_type: str
    road_segment_id: str
    started_at_ms: int
    ended_at_ms: int | None
    peak_state: str
    min_speed_ratio: float | None
    window_count: int


class EpisodeTracker:
    """Suit l'épisode d'un tronçon d'un run. Une instance par (run, tronçon)."""

    def __init__(self, run_id: str, source_type: str, road_segment_id: str) -> None:
        self._run_id = run_id
        self._source_type = source_type
        self._road_segment_id = road_segment_id
        self._open: EpisodeRecord | None = None

    @property
    def current(self) -> EpisodeRecord | None:
        return self._open

    def observe(
        self, before: Hysteresis, after: Hysteresis, obs: Observation
    ) -> EpisodeRecord | None:
        """Rend l'enregistrement à écrire, ou `None` quand rien ne change."""
        current = self._open
        if current is None:
            if after.state in DEGRADED:
                return self._begin(after)
            return None
        if after.state in DEGRADED:
            return self._extend(current, after, obs)
        if after.state == "FREE_FLOW":
            return self._finish(current, before, after)
        return None  # UNKNOWN : l'épisode reste ouvert, sans être prolongé

    def _begin(self, after: Hysteresis) -> EpisodeRecord:
        started = after.slow_since if after.slow_since is not None else 0
        key = f"episode:{self._run_id}:{self._road_segment_id}:{started}"
        self._open = EpisodeRecord(
            episode_id=str(uuid.uuid5(_NAMESPACE, key)),
            run_id=self._run_id,
            source_type=self._source_type,
            road_segment_id=self._road_segment_id,
            started_at_ms=started,
            ended_at_ms=None,
            peak_state=after.state,
            min_speed_ratio=after.slow_min,
            window_count=after.slow,
        )
        return self._open

    def _extend(self, current: EpisodeRecord, after: Hysteresis, obs: Observation) -> EpisodeRecord:
        ratios = [r for r in (current.min_speed_ratio, obs.speed_ratio) if r is not None]
        self._open = replace(
            current,
            peak_state="CONGESTED" if after.state == "CONGESTED" else current.peak_state,
            min_speed_ratio=min(ratios) if ratios else None,
            window_count=current.window_count + 1,
        )
        return self._open

    def _finish(
        self, current: EpisodeRecord, before: Hysteresis, after: Hysteresis
    ) -> EpisodeRecord:
        # après un trou, on ne sait rien de ce qui s'est passé : la fin est le début du trou
        ended = before.gap_since if before.state == "UNKNOWN" else after.free_since
        ended = current.started_at_ms if ended is None else max(ended, current.started_at_ms)
        closed = replace(
            current,
            ended_at_ms=ended,
            window_count=max(1, (ended - current.started_at_ms) // WINDOW_MS),
        )
        self._open = None
        return closed
