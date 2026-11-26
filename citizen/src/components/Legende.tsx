import { STATES } from "../types";
import { StateBadge } from "./StateBadge";

/** Ce que veulent dire les couleurs et les formes d'une croix : les quatre états, avec leur mot. */
export function Legende() {
  return (
    <ul className="legende" aria-label="Légende">
      {[...STATES].reverse().map((etat) => (
        <li key={etat}>
          <StateBadge state={etat} />
        </li>
      ))}
    </ul>
  );
}
