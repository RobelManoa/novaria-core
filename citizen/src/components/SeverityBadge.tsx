import { SEVERITY_LABEL } from "../labels";
import type { Severity } from "../types";

const ICON: Record<Severity, string> = {
  INFO: "M12 8v.01 M11 12h1v5h1", // « i »
  WARNING: "M12 4l9 16H3z M12 10v4 M12 17v.01", // triangle d'attention
  CRITICAL: "M8 3h8l5 5v8l-5 5H8l-5-5V8z M12 8v5 M12 16v.01", // panneau avec point d'exclamation
};

/** La gravité d'une alerte : un mot et une forme, jamais la couleur seule (WCAG 1.4.1). */
export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`badge badge--gravite-${severity.toLowerCase()}`}>
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
        <path
          d={ICON[severity]}
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span>{SEVERITY_LABEL[severity]}</span>
    </span>
  );
}
