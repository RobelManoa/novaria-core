import type { SegmentState } from "../types";
import type { Trajet } from "../trajets";
import { VERDICT_ETAT, resumeDesTrajets } from "../verdict";
import { StateIcon } from "./StateBadge";

const MOT: Record<string, string> = {
  BLOQUE: "bloqué",
  RALENTI: "ralenti",
  INCOMPLET: "incomplet",
  INDISPONIBLE: "indisponible",
  LIBRE: "libre",
};

/** « En ce moment : 1 bloqué, 1 ralenti, 1 libre » : l'état de MES trajets d'un coup d'œil, le plus grave d'abord. Rien si aucun trajet n'est gardé. */
export function ResumeTrajets({
  trajets,
  parId,
}: {
  trajets: readonly Trajet[];
  parId: ReadonlyMap<string, SegmentState>;
}) {
  const resume = resumeDesTrajets(trajets, parId);
  if (resume.length === 0) return null;
  return (
    <section aria-label="En ce moment" className="resume-trajets">
      <span className="resume-trajets__titre">En ce moment :</span>
      <ul className="resume-trajets__liste">
        {resume.map(({ verdict, n }) => {
          const etat = VERDICT_ETAT[verdict];
          return (
            <li key={verdict} className={`badge badge--${etat.toLowerCase().replace("_", "-")}`}>
              <StateIcon state={etat} />
              <span>
                {n} {MOT[verdict]}
                {n > 1 ? "s" : ""}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
