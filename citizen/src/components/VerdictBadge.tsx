import { VERDICT_ETAT, VERDICT_TITRE, type Verdict } from "../verdict";
import { StateIcon } from "./StateBadge";

/** Le verdict d'un trajet : un mot ET une forme, jamais la couleur seule (WCAG 1.4.1). Les couleurs sont celles des états (contrastes calculés). */
export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const etat = VERDICT_ETAT[verdict];
  return (
    <span className={`verdict verdict--${etat.toLowerCase().replace("_", "-")}`}>
      <StateIcon state={etat} />
      <span>{VERDICT_TITRE[verdict]}</span>
    </span>
  );
}
