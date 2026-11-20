import { STATE_ORDER } from "../labels";
import type { Counts } from "../summary";
import type { CongestionState } from "../types";
import { StateIcon } from "./StateBadge";

const NOUN: Record<CongestionState, [string, string]> = {
  CONGESTED: ["tronçon congestionné", "tronçons congestionnés"],
  SLOW: ["tronçon ralenti", "tronçons ralentis"],
  FREE_FLOW: ["tronçon fluide", "tronçons fluides"],
  UNKNOWN: ["tronçon sans information", "tronçons sans information"],
};

/** Le coup d'œil : combien de tronçons dans chaque état. « Sans information » n'apparaît que s'il y en a. */
export function Summary({ counts }: { counts: Counts }) {
  return (
    <section aria-labelledby="titre-resume" className="bloc">
      <h2 id="titre-resume">En un coup d'œil</h2>
      <ul className="resume">
        {STATE_ORDER.filter((state) => state !== "UNKNOWN" || counts.UNKNOWN > 0).map((state) => (
          <li
            key={state}
            className={`resume__case resume__case--${state.toLowerCase().replace("_", "-")}`}
          >
            <StateIcon state={state} />
            <span className="resume__nombre">{counts[state]}</span>{" "}
            <span className="resume__texte">{NOUN[state][counts[state] === 1 ? 0 : 1]}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
