import type { PublicAlert, SegmentState } from "../src/types";

/** Un tronçon au format du contrat (traitement.openapi.yaml, PublicSegmentState), modifiable champ par champ. */
export function segment(changes: Partial<SegmentState> = {}): SegmentState {
  return {
    road_segment_id: "ROAD_001",
    intersection_id: "INT_01",
    approach: "N",
    state: "FREE_FLOW",
    updated_at: "2026-11-20T09:10:00Z",
    simulated: true,
    ...changes,
  };
}

/** Quatre tronçons de INT_01 et deux de INT_02, dans les trois états et un tronçon sans information. */
export function network(): SegmentState[] {
  return [
    segment({ road_segment_id: "ROAD_001", approach: "N", state: "CONGESTED" }),
    segment({ road_segment_id: "ROAD_002", approach: "E", state: "SLOW" }),
    segment({ road_segment_id: "ROAD_003", approach: "S", state: "FREE_FLOW" }),
    segment({ road_segment_id: "ROAD_004", approach: "W", state: "FREE_FLOW" }),
    segment({
      road_segment_id: "ROAD_005",
      intersection_id: "INT_02",
      approach: "N",
      state: "UNKNOWN",
    }),
    segment({
      road_segment_id: "ROAD_006",
      intersection_id: "INT_02",
      approach: "E",
      state: "FREE_FLOW",
    }),
  ];
}

/** Une alerte au format du contrat (alerte.openapi.yaml, PublicAlert), modifiable champ par champ. */
export function alert(changes: Partial<PublicAlert> = {}): PublicAlert {
  return {
    alert_id: "3f0c1f0e-8a52-4d3c-9d58-1b9a3e5c7a10",
    road_segment_id: "ROAD_002",
    intersection_id: "INT_01",
    severity: "WARNING",
    opened_at: "2026-11-20T09:08:30Z",
    simulated: true,
    ...changes,
  };
}
