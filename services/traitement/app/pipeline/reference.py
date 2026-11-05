"""Ce que le recommandeur sait du réseau : à quel carrefour, de quel côté, sur combien de voies."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SegmentPlanInfo:
    road_segment_id: str
    intersection_id: str
    approach: str  # N, E, S ou W
    lanes: int


@dataclass(frozen=True)
class PlanReference:
    segments: dict[str, SegmentPlanInfo] = field(default_factory=dict)

    def segments_of(self, intersection_id: str) -> list[SegmentPlanInfo]:
        return [s for s in self.segments.values() if s.intersection_id == intersection_id]
