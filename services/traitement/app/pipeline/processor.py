"""Le pipeline d'écriture : un indicateur lu, un fait écrit, une recommandation publiée.

À chaque point de contrôle (`checkpoint`), dans cet ordre :

1. les faits en attente sont écrits dans l'entrepôt, en une transaction (`FactStore.load`) ;
2. les recommandations des carrefours devenus complets sont publiées ;
3. le broker accuse réception de tout ce qui a été publié ;
4. les offsets sont rendus : ils ne dépassent pas le plus ancien indicateur qui attend encore ses
   voisins pour une recommandation.

Un plantage entre deux étapes se rattrape en relisant : le fait a la même clé, la recommandation le
même identifiant (livraison au moins une fois, écritures idempotentes). Ce qui est refusé
(illisible, hors contrat, tronçon inconnu, ligne que la base refuse) part sur `errors.dlq`, copié
dans MongoDB `rejects`, et compté dans `processing_stats`.
"""

import json
import logging
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

from app.flux.model import Rejection
from app.flux.ports import EventPublisher, RejectArchive, StatsStore, StoreFailed
from app.flux.rejections import Rejector, dumps
from app.flux.windows import Emission  # noqa: F401 - documente la parenté avec le flux

from .facts import IndicatorFact, parse_indicator
from .ports import FactStore
from .recommender import Recommender

logger = logging.getLogger("app.pipeline")

TOPIC_INDICATORS = "traffic.indicators"
TOPIC_RECOMMENDATIONS = "traffic.recommendations"
STATS_FLUSH_S = 10.0
MINUTE_MS = 60_000


class Pipeline:
    def __init__(
        self,
        facts: FactStore,
        recommender: Recommender,
        publisher: EventPublisher,
        rejects: RejectArchive,
        stats: StatsStore,
        *,
        clock: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._facts = facts
        self._recommender = recommender
        self._publisher = publisher
        self._rejector = Rejector(publisher, rejects, TOPIC_INDICATORS)
        self._stats = stats
        self._clock = clock
        self._utc_now = utc_now
        self._pending: list[tuple[IndicatorFact, bytes]] = []
        self._next_offset: dict[int, int] = {}
        self._counts: dict[tuple[str, int, str | None], Counter[str]] = {}
        self._last_stats_flush = clock()
        self._seen_reco = Counter[str]()
        self.totals: Counter[str] = Counter()

    # ----------------------------------------------------------------------------- entrée

    def handle(
        self,
        raw: bytes,
        key: bytes | None = None,
        partition: int | None = None,
        offset: int | None = None,
    ) -> None:
        result = parse_indicator(raw, key=key, partition=partition, offset=offset)
        if isinstance(result, Rejection):
            self._reject(result)
        else:
            self._pending.append((result, raw))
        if partition is not None and offset is not None:
            self._next_offset[partition] = max(self._next_offset.get(partition, 0), offset + 1)

    def tick(self) -> None:
        if self._clock() - self._last_stats_flush >= STATS_FLUSH_S:
            self.flush_stats()

    # ------------------------------------------------------------------------- validation

    def checkpoint(self) -> dict[int, int]:
        pending, self._pending = self._pending, []
        facts = [fact for fact, _ in pending]
        try:
            failures = self._facts.load(facts) if facts else []
        except StoreFailed:
            self._pending = pending + self._pending  # rien n'est perdu : le service s'arrête
            raise
        failed = {id(f.fact): f for f in failures}
        raw_of = {id(fact): raw for fact, raw in pending}
        for failure in failures:
            self._reject_failure(failure, raw_of[id(failure.fact)])
        loaded = [fact for fact in facts if id(fact) not in failed]
        for fact in loaded:
            self._count(fact.window_start_ms, fact.road_segment_id, "facts_loaded")
        self.totals["facts_loaded"] += len(loaded)

        for event in self._recommender.feed(loaded):
            self._publisher.publish(TOPIC_RECOMMENDATIONS, event["subject"], dumps(event))
            self.totals["recommendations_published"] += 1
        self._publisher.flush()
        self._count_recommender_stats()
        self.flush_stats()
        retained = self._recommender.retained_offsets()
        return {
            partition: min(next_offset, retained.get(partition, next_offset))
            for partition, next_offset in self._next_offset.items()
        }

    # --------------------------------------------------------------------------- rejets

    def _reject(self, rejection: Rejection) -> None:
        now = self._utc_now()
        code = self._rejector.reject(rejection, now)
        self.totals["rejected"] += 1
        stamp = int(now.timestamp() * 1000)
        self._count(
            rejection.window_start_ms or stamp,
            rejection.road_segment_id,
            f"rejected_{code.lower()}",
            "facts_rejected",
        )

    def _reject_failure(self, failure, raw: bytes) -> None:
        fact = failure.fact
        self._reject(
            Rejection(
                reason_code=failure.reason_code,
                reason=failure.reason,
                original_payload=json.loads(raw),
                intersection_id=fact.intersection_id,
                original_key=fact.intersection_id,
                window_start_ms=fact.window_start_ms,
                road_segment_id=fact.road_segment_id,
                partition=fact.partition,
                offset=fact.offset,
            )
        )

    # ------------------------------------------------------------------- statistiques

    def _count(self, start_ms: int, segment: str | None, *names: str) -> None:
        minute = start_ms - start_ms % MINUTE_MS
        counter = self._counts.setdefault(("quality", minute, segment), Counter())
        for name in names:
            counter[name] += 1

    def _count_recommender_stats(self) -> None:
        """Compteurs du recommandeur depuis le dernier point de contrôle, à la minute courante."""
        now_ms = int(self._utc_now().timestamp() * 1000)
        for name, value in self._recommender.stats.items():
            delta = value - self._seen_reco[name]
            if delta:
                self._seen_reco[name] = value
                counter = self._counts.setdefault(
                    ("quality", now_ms - now_ms % MINUTE_MS, None), Counter()
                )
                counter[f"reco_{name}"] += delta

    def flush_stats(self) -> None:
        pending, self._counts = self._counts, {}
        self._last_stats_flush = self._clock()
        for (kind, minute, segment), counts in sorted(pending.items(), key=lambda i: i[0][1]):
            start = datetime.fromtimestamp(minute / 1000, UTC)
            try:
                self._stats.add(kind, start, segment, dict(counts))
            except StoreFailed:
                logger.error("statistiques non écrites", extra={"fields": {"kind": kind}})
