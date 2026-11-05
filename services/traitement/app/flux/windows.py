"""Fenêtres en temps d'événement : agrégation, filigrane, retard, fenêtres vides, inactivité.

Le moteur ne connaît ni Kafka ni les bases : il reçoit des mesures déjà nettoyées et rend les
fenêtres qui se ferment ou qui sont corrigées. Les règles (ADR-011, section 4.1) :

- une mesure appartient à la fenêtre qui contient le **début** de son intervalle ;
- le filigrane d'un (run, carrefour) est le plus grand début vu moins 10 s ; une fenêtre se ferme
  (et se publie) quand le filigrane atteint sa fin ;
- une fenêtre fermée reste corrigeable jusqu'à sa fin + 30 s de filigrane : un message tardif
  dans cette limite la met à jour (même identifiant, révision suivante) ; au-delà il est refusé
  (`LATE`, DQ-04) pour la minute **et** pour les cinq minutes qui la contiennent ;
- un tronçon déjà vu produit une fenêtre vide quand rien n'arrive : un capteur muet donne un
  état `UNKNOWN`, pas un silence ;
- sans message depuis 15 s (horloge), les fenêtres en cours sont publiées ; après 10 min, l'état
  du run est libéré.
"""

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from .model import Measurement
from .rules import (
    ALLOWED_LATENESS_S,
    IDLE_FLUSH_S,
    IDLE_RETIRE_S,
    OUT_OF_ORDERNESS_S,
    WINDOW_SIZES_S,
)

# Au plus ce nombre de fenêtres vides par tronçon et par taille lors d'un seul avancement du temps :
# un trou de plusieurs jours ne produit pas des milliers de lignes (le reste est compté).
MAX_CATCHUP_WINDOWS = 60


@dataclass
class Window:
    """Les cumuls d'un tronçon sur une fenêtre ; l'état publié est posé par le processeur."""

    run_id: str
    road_segment_id: str
    intersection_id: str
    size_s: int
    start_ms: int
    provenance: dict
    vehicle_count: int = 0
    sample_count: int = 0
    revision: int = -1  # -1 : pas encore publiée ; 0 : publiée ; 1 et plus : corrigée après coup
    state: str | None = None  # état stabilisé publié avec cette fenêtre
    speed_ratio: float | None = None  # idem, ratio publié
    ids: set[str] = field(default_factory=set, repr=False)
    offsets: dict[int, int] = field(
        default_factory=dict, repr=False
    )  # partition -> plus petit offset
    # Cumuls en décimaux exacts : l'arrondi final (moitié vers le haut, comme PostgreSQL)
    # donne alors exactement ce qu'un recalcul SQL donne sur les mêmes mesures.
    _speed_sum: Decimal = Decimal(0)
    _speed_weight: int = 0
    _occupancy_sum: Decimal = Decimal(0)
    _occupancy_count: int = 0
    _queue_max: Decimal | None = None

    @property
    def end_ms(self) -> int:
        return self.start_ms + self.size_s * 1000

    @property
    def exact_average_speed(self) -> Decimal | None:
        """Moyenne pondérée par les véhicules des mesures qui ont une vitesse ; `None` sinon."""
        return self._speed_sum / self._speed_weight if self._speed_weight else None

    @property
    def exact_occupancy(self) -> Decimal | None:
        """Moyenne des taux d'occupation renseignés ; `None` si aucun."""
        return self._occupancy_sum / self._occupancy_count if self._occupancy_count else None

    @property
    def exact_max_queue(self) -> Decimal | None:
        return self._queue_max

    @property
    def average_speed_kmh(self) -> float | None:
        exact = self.exact_average_speed
        return None if exact is None else float(exact)

    @property
    def occupancy_rate(self) -> float | None:
        exact = self.exact_occupancy
        return None if exact is None else float(exact)

    @property
    def max_queue_length_m(self) -> float | None:
        return None if self._queue_max is None else float(self._queue_max)

    def add(self, m: Measurement) -> None:
        self.vehicle_count += m.vehicle_count
        self.sample_count += 1
        if m.partition is not None and m.offset is not None:
            self.offsets[m.partition] = min(m.offset, self.offsets.get(m.partition, m.offset))
        if m.speed_kmh is not None and m.vehicle_count > 0:
            self._speed_sum += Decimal(repr(m.speed_kmh)) * m.vehicle_count
            self._speed_weight += m.vehicle_count
        if m.occupancy_rate is not None:
            self._occupancy_sum += Decimal(repr(m.occupancy_rate))
            self._occupancy_count += 1
        if m.queue_length_m is not None:
            queue = Decimal(repr(m.queue_length_m))
            self._queue_max = queue if self._queue_max is None else max(self._queue_max, queue)


@dataclass(frozen=True)
class Emission:
    """Une fenêtre à publier : première publication (révision 0) ou correction (révision ≥ 1)."""

    window: Window
    revision: int


@dataclass(frozen=True)
class AddResult:
    verdict: str  # ACCEPTED, DUPLICATE, EXCLUDED (mesure suspecte) ou LATE
    emissions: list[Emission] = field(default_factory=list)
    behind_ms: int | None = None  # LATE : de combien la fenêtre est dépassée par le filigrane


@dataclass(frozen=True)
class Flush:
    emissions: list[Emission]
    retired: list[str]


@dataclass
class _Track:
    """Un tronçon suivi : son identité, ses fenêtres encore corrigeables, la prochaine à fermer."""

    run_id: str
    road_segment_id: str
    intersection_id: str
    provenance: dict
    windows: dict[tuple[int, int], Window] = field(default_factory=dict)
    next_close: dict[int, int] = field(default_factory=dict)


@dataclass
class _Run:
    last_seen: float
    watermark: dict[str, int] = field(default_factory=dict)
    max_start: dict[str, int] = field(default_factory=dict)
    flushed: dict[str, bool] = field(default_factory=dict)
    segments: dict[str, _Track] = field(default_factory=dict)


def _align(ms: int, size_s: int) -> int:
    return ms - ms % (size_s * 1000)


class WindowEngine:
    def __init__(
        self,
        sizes: tuple[int, ...] = WINDOW_SIZES_S,
        out_of_orderness_s: float = OUT_OF_ORDERNESS_S,
        allowed_lateness_s: float = ALLOWED_LATENESS_S,
        max_catchup: int = MAX_CATCHUP_WINDOWS,
    ) -> None:
        self._sizes = tuple(sorted(sizes))
        self._ooo_ms = int(out_of_orderness_s * 1000)
        self._lateness_ms = int(allowed_lateness_s * 1000)
        self._max_catchup = max_catchup
        self._runs: dict[str, _Run] = {}
        self.stats: Counter[str] = Counter()

    # ------------------------------------------------------------------------------ ajout

    def add(self, m: Measurement, now: float) -> AddResult:
        """Range une mesure nettoyée. `now` : horloge monotone du consommateur, en secondes."""
        run = self._runs.setdefault(m.run_id, _Run(last_seen=now))
        run.last_seen = now
        smallest = self._sizes[0]
        first_start = _align(m.start_ms, smallest)
        watermark = run.watermark.get(m.intersection_id)

        if watermark is not None:
            behind = watermark - (first_start + smallest * 1000 + self._lateness_ms)
            if behind >= 0:
                self.stats["late"] += 1
                return AddResult("LATE", behind_ms=behind + self._lateness_ms)

        track = run.segments.setdefault(
            m.road_segment_id,
            _Track(m.run_id, m.road_segment_id, m.intersection_id, m.provenance),
        )
        emissions: list[Emission] = []
        verdict = "ACCEPTED"
        first = track.windows.get((smallest, first_start))
        if m.status == "SUSPECT":
            verdict = "EXCLUDED"
            self.stats["excluded"] += 1
        elif first is not None and m.id in first.ids:
            verdict = "DUPLICATE"
            self.stats["duplicates"] += 1
        else:
            self.stats["accepted"] += 1
            for size in self._sizes:
                window = self._window_for(m, track, size)
                window.add(m)
                if size == smallest:
                    window.ids.add(m.id)
                if window.revision >= 0:
                    window.revision += 1
                    self.stats["updated"] += 1
                    emissions.append(Emission(window, window.revision))

        candidate = m.start_ms - self._ooo_ms
        if watermark is None or candidate > watermark:
            run.watermark[m.intersection_id] = candidate
        run.max_start[m.intersection_id] = max(run.max_start.get(m.intersection_id, 0), m.start_ms)
        run.flushed[m.intersection_id] = False

        limit = run.watermark[m.intersection_id]
        emissions.extend(self._close(run, m.intersection_id, lambda size: limit))
        return AddResult(verdict, _ordered(emissions))

    def _window_for(self, m: Measurement, track: _Track, size: int) -> Window:
        start = _align(m.start_ms, size)
        key = (size, start)
        window = track.windows.get(key)
        if window is None:
            window = Window(
                m.run_id, m.road_segment_id, m.intersection_id, size, start, m.provenance
            )
            track.windows[key] = window
            expected = track.next_close.get(size)
            if expected is None or start < expected:
                # première mesure du tronçon, ou mesure plus ancienne arrivée en désordre
                track.next_close[size] = start
        return window

    # --------------------------------------------------------------------------- fermeture

    def _close(self, run: _Run, intersection_id: str, limit_for) -> list[Emission]:
        emissions: list[Emission] = []
        watermark = run.watermark[intersection_id]
        for track in run.segments.values():
            if track.intersection_id != intersection_id:
                continue
            for size in self._sizes:
                emissions.extend(self._close_track(track, size, limit_for(size)))
            for key, window in list(track.windows.items()):
                if window.revision >= 0 and window.end_ms + self._lateness_ms <= watermark:
                    del track.windows[key]  # définitive : plus aucune correction possible
        return emissions

    def _close_track(self, track: _Track, size: int, limit: int) -> list[Emission]:
        emissions: list[Emission] = []
        size_ms = size * 1000
        cursor = track.next_close.get(size)
        if cursor is None:
            return emissions
        pending = (limit - cursor) // size_ms
        if pending > self._max_catchup:
            skipped = pending - self._max_catchup
            for key in sorted(track.windows):
                window = track.windows[key]
                in_range = cursor <= window.start_ms < cursor + skipped * size_ms
                if key[0] == size and in_range and window.revision < 0:
                    window.revision = 0
                    emissions.append(Emission(window, 0))
            self.stats["skipped_windows"] += skipped
            cursor += skipped * size_ms
        while cursor + size_ms <= limit:
            window = track.windows.get((size, cursor))
            if window is None:
                window = Window(
                    track.run_id,
                    track.road_segment_id,
                    track.intersection_id,
                    size,
                    cursor,
                    track.provenance,
                )
                track.windows[(size, cursor)] = window
                self.stats["empty_windows"] += 1
            if window.revision < 0:
                window.revision = 0
                emissions.append(Emission(window, 0))
            cursor += size_ms
        track.next_close[size] = cursor
        return emissions

    def retained_offsets(self) -> dict[int, int]:
        """Par partition, le plus petit offset encore nécessaire pour refaire les fenêtres.

        Tant qu'une fenêtre n'est pas définitive (publiée ou non, corrigeable), ses messages ne
        peuvent pas être validés : après un redémarrage, ils sont relus et la fenêtre est refaite.
        """
        lowest: dict[int, int] = {}
        for run in self._runs.values():
            for track in run.segments.values():
                for window in track.windows.values():
                    for partition, offset in window.offsets.items():
                        lowest[partition] = min(offset, lowest.get(partition, offset))
        return lowest

    # -------------------------------------------------------------------------- inactivité

    def flush_idle(self, now: float) -> Flush:
        """Publie les fenêtres en cours d'un flux silencieux ; libère les runs abandonnés."""
        emissions: list[Emission] = []
        retired: list[str] = []
        for run_id, run in list(self._runs.items()):
            silence = now - run.last_seen
            if silence >= IDLE_FLUSH_S:
                for intersection_id, latest in run.max_start.items():
                    if run.flushed.get(intersection_id):
                        continue
                    emissions.extend(
                        self._close(
                            run,
                            intersection_id,
                            lambda size, latest=latest: _align(latest, size) + size * 1000,
                        )
                    )
                    run.flushed[intersection_id] = True
            if silence >= IDLE_RETIRE_S:
                del self._runs[run_id]
                retired.append(run_id)
        return Flush(_ordered(emissions), retired)


def _ordered(emissions: list[Emission]) -> list[Emission]:
    """Par fin de fenêtre, puis par taille : la minute avant les cinq minutes qui la finissent."""
    return sorted(
        emissions,
        key=lambda e: (e.window.end_ms, e.window.size_s, e.window.road_segment_id, e.revision),
    )
