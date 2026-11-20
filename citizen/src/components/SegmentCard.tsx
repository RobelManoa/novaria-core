import { APPROACH_LABEL, STATE_HELP, STATE_LABEL } from "../labels";
import type { FollowState } from "../useFollow";
import type { SegmentState } from "../types";
import { FollowButton } from "./FollowButton";
import { StateBadge } from "./StateBadge";

export function SegmentCard({ segment, follow }: { segment: SegmentState; follow: FollowState }) {
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
        <FollowButton roadSegmentId={segment.road_segment_id} follow={follow} />
      </div>
      <StateBadge state={segment.state} />
    </li>
  );
}
