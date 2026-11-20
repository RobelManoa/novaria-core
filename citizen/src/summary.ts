import { APPROACHES, STATES, type CongestionState, type SegmentState } from "./types";

export type Counts = Record<CongestionState, number>;

export function countByState(segments: readonly SegmentState[]): Counts {
  const counts = Object.fromEntries(STATES.map((state) => [state, 0])) as Counts;
  for (const segment of segments) counts[segment.state] += 1;
  return counts;
}

export interface Group {
  intersection: string;
  segments: SegmentState[];
}

/** Un groupe par carrefour (ordre des identifiants), les tronçons dans l'ordre nord, est, sud, ouest. */
export function groupByIntersection(segments: readonly SegmentState[]): Group[] {
  const groups = new Map<string, SegmentState[]>();
  for (const segment of segments) {
    groups.set(segment.intersection_id, [...(groups.get(segment.intersection_id) ?? []), segment]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b, "fr", { numeric: true }))
    .map(([intersection, list]) => ({
      intersection,
      segments: [...list].sort(
        (a, b) =>
          APPROACHES.indexOf(a.approach) - APPROACHES.indexOf(b.approach) ||
          a.road_segment_id.localeCompare(b.road_segment_id),
      ),
    }));
}

/** La mise à jour la plus récente : l'écran dit « données de HH:mm », pas l'heure de l'appel. */
export function latestUpdate(segments: readonly SegmentState[]): string | null {
  if (segments.length === 0) return null;
  return segments.reduce(
    (best, s) => (s.updated_at > best ? s.updated_at : best),
    segments[0].updated_at,
  );
}
