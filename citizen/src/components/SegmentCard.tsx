import { APPROACH_LABEL, STATE_HELP, STATE_LABEL } from "../labels";
import type { SegmentState } from "../types";
import { StateBadge } from "./StateBadge";

export function SegmentCard({ segment }: { segment: SegmentState }) {
  return (
    <li className={`carte carte--${segment.state.toLowerCase().replace("_", "-")}`}>
      <div className="carte__texte">
        <p className="carte__titre">{APPROACH_LABEL[segment.approach]}</p>
        <p className="carte__detail">
          Tronçon {segment.road_segment_id}
          {segment.simulated ? <span className="etiquette"> · Simulé</span> : null}
        </p>
        <p className="visuellement-cache">
          {STATE_LABEL[segment.state]}. {STATE_HELP[segment.state]}
        </p>
      </div>
      <StateBadge state={segment.state} />
    </li>
  );
}
