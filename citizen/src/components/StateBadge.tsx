import { STATE_LABEL } from "../labels";
import type { CongestionState } from "../types";

const ICON: Record<CongestionState, string> = {
  FREE_FLOW: "M5 13l4 4L19 7", // coche
  SLOW: "M12 4l9 16H3z M12 10v4 M12 17v.01", // triangle d'attention
  CONGESTED: "M8 3h8l5 5v8l-5 5H8l-5-5V8z M8 12h8", // panneau « sens interdit »
  UNKNOWN: "M9.5 9a2.5 2.5 0 115 0c0 2-2.5 2-2.5 4 M12 17v.01", // point d'interrogation
};

export function StateIcon({ state }: { state: CongestionState }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
      <path
        d={ICON[state]}
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * L'état d'un tronçon : un **mot** et une **forme**, jamais la couleur seule (WCAG 1.4.1). La couleur renforce, elle ne porte
 * pas l'information : une personne qui ne distingue pas le vert du rouge lit « Libre » et voit une coche.
 */
export function StateBadge({ state }: { state: CongestionState }) {
  return (
    <span className={`badge badge--${state.toLowerCase().replace("_", "-")}`}>
      <StateIcon state={state} />
      <span>{STATE_LABEL[state]}</span>
    </span>
  );
}
