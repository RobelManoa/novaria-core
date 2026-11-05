"""Le service de traitement en flux : un message en entrée, des indicateurs, rejets, épisodes.

Enchaînement : nettoyage -> fenêtres -> (pour les minutes) hystérésis -> indicateur publié ;
l'épisode de congestion est écrit à chaque changement. Tout ce qui est écarté est compté et tracé :

| Cas                     | Où                                                        |
|-------------------------|-----------------------------------------------------------|
| message refusé          | `errors.dlq` + MongoDB `rejects` + `processing_stats`     |
| trop tardif (`LATE`)    | idem, motif `LATE`, compteur `lateness`                   |
| doublon, mesure suspecte| `processing_stats` (`quality`)                            |
| fenêtre non publiable   | `processing_stats` (`quality`, `withheld_*`) + journal    |

Livraison au moins une fois : `checkpoint()` rend les offsets qui peuvent être validés, après que
tout ce qui a été publié est accusé. Les indicateurs ont une clé d'idempotence (leur `id`) ; les
épisodes une clé d'unicité ; les rejets un `_id` fixe.
"""

import json
import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .classifier import Hysteresis, advance
from .cleaning import clean
from .episodes import EpisodeTracker
from .indicators import Indicator, Withheld, build, observation
from .model import Measurement, Referential, Rejection
from .ports import EpisodeStore, EventPublisher, RejectArchive, StatsStore, StoreFailed
from .rejections import Rejector, dumps
from .rules import DEFAULT_THRESHOLDS, STATE_WINDOW_S, Thresholds
from .windows import Emission, WindowEngine

logger = logging.getLogger("app.flux")

TOPIC_RAW = "iot.raw"
TOPIC_INDICATORS = "traffic.indicators"
SERVICE = "traitement"
STATS_FLUSH_S = 10.0
MINUTE_MS = STATE_WINDOW_S * 1000


@dataclass
class _Segment:
    hysteresis: Hysteresis
    tracker: EpisodeTracker


@dataclass
class Totals:
    """Compteurs du processus (journal, tests) ; les statistiques durables sont dans MongoDB."""

    counters: Counter[str] = field(default_factory=Counter)

    def __getitem__(self, name: str) -> int:
        return self.counters[name]


class Processor:
    def __init__(
        self,
        referential: Referential,
        publisher: EventPublisher,
        rejects: RejectArchive,
        episodes: EpisodeStore,
        stats: StatsStore,
        *,
        thresholds: Thresholds = DEFAULT_THRESHOLDS,
        replay: bool = False,
        clock: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ref = referential
        self._publisher = publisher
        self._rejector = Rejector(publisher, rejects, TOPIC_RAW)
        self._episodes = episodes
        self._stats = stats
        self._thresholds = thresholds
        self._replay = replay  # rejeu d'un jeu historique : pas de rejet FUTURE_TIMESTAMP
        self._clock = clock
        self._utc_now = utc_now
        self._engine = WindowEngine()
        self._segments: dict[tuple[str, str], _Segment] = {}
        self._pending: dict[tuple[str, int, str | None], Counter[str]] = {}
        self._next_offset: dict[int, int] = {}
        self._last_stats_flush = clock()
        self.totals = Totals()

    # ----------------------------------------------------------------------------- entrée

    def handle(
        self,
        raw: bytes,
        key: bytes | None = None,
        partition: int | None = None,
        offset: int | None = None,
    ) -> None:
        """Traite un message de `iot.raw`. Sur `PublishFailed`, ne pas valider l'offset."""
        now = self._utc_now()
        now_ms = None if self._replay else int(now.timestamp() * 1000)
        result = clean(raw, self._ref, key=key, now_ms=now_ms, partition=partition, offset=offset)
        if isinstance(result, Rejection):
            self._reject(result, now)
        else:
            self._accept(result, raw, now, key)
        if partition is not None and offset is not None:
            self._next_offset[partition] = max(self._next_offset.get(partition, 0), offset + 1)

    def _accept(self, m: Measurement, raw: bytes, now: datetime, key: bytes | None) -> None:
        verdict = self._engine.add(m, self._clock())
        minute = m.start_ms - m.start_ms % MINUTE_MS
        if verdict.verdict == "LATE":
            behind_s = (verdict.behind_ms or 0) // 1000
            reason = f"fenêtre dépassée de {behind_s} s par le filigrane (retard autorisé 30 s)"
            rejection = Rejection(
                reason_code="LATE",
                reason=reason,
                original_payload=json.loads(raw),
                intersection_id=m.intersection_id,
                original_key=None if key is None else key.decode("utf-8", errors="replace")[:200],
                window_start_ms=minute,
                road_segment_id=m.road_segment_id,
                partition=m.partition,
                offset=m.offset,
            )
            self._reject(rejection, now)
            self._count("lateness", minute, m.road_segment_id, "late_rejected")
            return
        names = {"ACCEPTED": "accepted", "DUPLICATE": "duplicates", "EXCLUDED": "excluded_suspect"}
        self._count("quality", minute, m.road_segment_id, names[verdict.verdict])
        if verdict.verdict == "ACCEPTED" and m.status == "PARTIAL":
            self._count("quality", minute, m.road_segment_id, "partial")
        self._emit(verdict.emissions)

    # ---------------------------------------------------------------------------- fenêtres

    def tick(self) -> None:
        """À appeler régulièrement, même sans message : publie les fenêtres d'un flux silencieux."""
        flush = self._engine.flush_idle(self._clock())
        self._emit(flush.emissions)
        for run_id in flush.retired:
            for key in [k for k in self._segments if k[0] == run_id]:
                del self._segments[key]
        if self._clock() - self._last_stats_flush >= STATS_FLUSH_S:
            self.flush_stats()

    def _segment(self, run_id: str, road_segment_id: str, source_type: str) -> _Segment:
        key = (run_id, road_segment_id)
        if key not in self._segments:
            tracker = EpisodeTracker(run_id, source_type, road_segment_id)
            self._segments[key] = _Segment(Hysteresis(), tracker)
        return self._segments[key]

    def _emit(self, emissions: list[Emission]) -> None:
        for emission in emissions:
            window = emission.window
            segment = self._segment(
                window.run_id, window.road_segment_id, window.provenance["source_type"]
            )
            if emission.revision == 0:
                if window.size_s == STATE_WINDOW_S:
                    self._classify(window, segment)
                else:
                    window.state = segment.hysteresis.state  # les cinq minutes reprennent l'état
            elif window.size_s == STATE_WINDOW_S:
                self._count("lateness", window.start_ms, window.road_segment_id, "late_accepted")
            self._publish(window, window.state or "UNKNOWN")

    def _classify(self, window, segment: _Segment) -> None:
        obs = observation(window, self._ref)
        after = advance(segment.hysteresis, obs, self._thresholds)
        record = segment.tracker.observe(segment.hysteresis, after, obs)
        segment.hysteresis = after
        window.state, window.speed_ratio = after.state, obs.speed_ratio
        if window.sample_count == 0:
            self._count("quality", window.start_ms, window.road_segment_id, "empty_windows")
        if record is not None:
            self._episodes.upsert(record)
            self.totals.counters["episode_writes"] += 1

    def _publish(self, window, state: str) -> None:
        result = build(window, self._ref, state)
        if isinstance(result, Withheld):
            self._withhold(result)
            return
        self._send_indicator(result)

    def _send_indicator(self, indicator: Indicator) -> None:
        event = indicator.event
        self._publisher.publish(TOPIC_INDICATORS, event["subject"], dumps(event))
        self.totals.counters["indicators_published"] += 1
        window = indicator.window
        if window.size_s == STATE_WINDOW_S:
            self._count("quality", window.start_ms, window.road_segment_id, "indicators_published")

    def _withhold(self, withheld: Withheld) -> None:
        window = withheld.window
        name = f"withheld_{withheld.reason_code.lower()}"
        self.totals.counters[name] += 1
        self._count("quality", window.start_ms, window.road_segment_id, name)
        logger.warning(
            "indicateur retenu",
            extra={
                "fields": {
                    "reason_code": withheld.reason_code,
                    "road_segment_id": window.road_segment_id,
                    "window_start_ms": window.start_ms,
                    "window_size_s": window.size_s,
                }
            },
        )

    # ------------------------------------------------------------------------------ rejets

    def _reject(self, rejection: Rejection, now: datetime) -> None:
        code = self._rejector.reject(rejection, now)
        self.totals.counters["rejected"] += 1
        self.totals.counters[f"rejected_{code.lower()}"] += 1
        minute = rejection.window_start_ms
        if minute is None:
            stamp_ms = int(now.timestamp() * 1000)
            minute = stamp_ms - stamp_ms % MINUTE_MS
        self._count("rejects", minute, rejection.road_segment_id, code, "total")

    # ---------------------------------------------------------------------------- statistiques

    def _count(self, kind: str, window_start_ms: int, segment: str | None, *names: str) -> None:
        minute = window_start_ms - window_start_ms % MINUTE_MS
        counter = self._pending.setdefault((kind, minute, segment), Counter())
        for name in names:
            counter[name] += 1

    def flush_stats(self) -> None:
        pending, self._pending = self._pending, {}
        self._last_stats_flush = self._clock()
        for (kind, minute, segment), counts in sorted(pending.items(), key=lambda i: i[0][1]):
            start = datetime.fromtimestamp(minute / 1000, UTC)
            try:
                self._stats.add(kind, start, segment, dict(counts))
            except StoreFailed:
                logger.error("statistiques non écrites", extra={"fields": {"kind": kind}})

    # ----------------------------------------------------------------------------- validation

    def checkpoint(self) -> dict[int, int]:
        """Attend les accusés du broker, écrit les statistiques, rend les offsets à valider.

        Pour chaque partition : le prochain message à lire, sans dépasser le plus ancien message
        d'une fenêtre encore corrigeable (elle serait perdue en cas de redémarrage).
        """
        self._publisher.flush()
        self.flush_stats()
        retained = self._engine.retained_offsets()
        return {
            partition: min(next_offset, retained.get(partition, next_offset))
            for partition, next_offset in self._next_offset.items()
        }
