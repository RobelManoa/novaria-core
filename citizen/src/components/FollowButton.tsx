import type { FollowState } from "../useFollow";

/** Suivre ou ne plus suivre un tronçon. Inactif tant que le consentement n'est pas donné (voir `FollowPanel`). */
export function FollowButton({
  roadSegmentId,
  follow,
}: {
  roadSegmentId: string;
  follow: FollowState;
}) {
  const on = follow.isFollowed(roadSegmentId);
  return (
    <button
      type="button"
      className="bouton bouton--discret bouton--petit"
      aria-pressed={on}
      aria-label={`${on ? "Ne plus suivre" : "Suivre"} le tronçon ${roadSegmentId}`}
      disabled={!follow.consent && !on}
      onClick={() => (on ? follow.unfollow(roadSegmentId) : follow.follow(roadSegmentId))}
    >
      {on ? "Suivi : arrêter" : "Suivre ce tronçon"}
    </button>
  );
}
