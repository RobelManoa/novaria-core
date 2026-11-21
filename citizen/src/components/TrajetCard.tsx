import { ago, formatTime } from "../format";
import { lienDetail } from "../route";
import type { SegmentState } from "../types";
import type { Trajet } from "../trajets";
import { VERDICT_ETAT, VERDICT_PHRASE, verdictDuTrajet } from "../verdict";
import { VerdictBadge } from "./VerdictBadge";

interface Props {
  trajet: Trajet;
  parId: ReadonlyMap<string, SegmentState>;
  current: number;
  /** Un trajet proposé n'est pas encore gardé : il offre « Garder ce trajet ». Un trajet gardé est un lien vers son détail. */
  propose?: boolean;
  onGarder?: () => void;
}

/**
 * Un trajet sur l'accueil (ADR-031) : son nom, un mot et une forme, une phrase pour décider, où ça pose problème. Toute la carte d'un
 * trajet gardé ouvre son détail ; « Me prévenir » et « Supprimer » s'y règlent, pas ici.
 */
export function TrajetCard({ trajet, parId, current, propose, onGarder }: Props) {
  const lecture = verdictDuTrajet(trajet, parId);
  const titre = `titre-${trajet.id}`;
  const etat = VERDICT_ETAT[lecture.verdict].toLowerCase().replace("_", "-");
  return (
    <li
      className={`trajet trajet--${etat}${propose ? "" : " trajet--lien"}`}
      aria-labelledby={titre}
    >
      <h3 id={titre} className="trajet__nom">
        {propose ? (
          trajet.nom
        ) : (
          <a className="trajet__lien" href={lienDetail(trajet.id)}>
            {trajet.nom}
            <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" focusable="false">
              <path
                d="M9 6l6 6-6 6"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </a>
        )}
      </h3>
      <VerdictBadge verdict={lecture.verdict} />
      <p className="trajet__phrase">{VERDICT_PHRASE[lecture.verdict]}</p>
      {lecture.critiques.length > 0 && lecture.verdict !== "INDISPONIBLE" ? (
        <p className="trajet__ou">
          {lecture.verdict === "INCOMPLET" ? "Sans mesure : " : "Là où ça se passe : "}
          {lecture.critiques.map((t) => t.nom).join(" ; ")}.
        </p>
      ) : null}
      {!propose && trajet.prevenir ? (
        <p className="trajet__prevenu">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
            <path
              d="M6 16V11a6 6 0 1112 0v5l2 2H4z M10 21h4"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Je suis prévenu
        </p>
      ) : null}
      {lecture.miseAJour ? (
        <p className="trajet__meta">
          Mesure de <time dateTime={lecture.miseAJour}>{formatTime(lecture.miseAJour)}</time> (
          {ago(current, new Date(lecture.miseAJour).getTime())})
        </p>
      ) : null}
      {propose ? (
        <div className="trajet__actions">
          <button type="button" className="bouton" onClick={onGarder}>
            Garder ce trajet
          </button>
        </div>
      ) : null}
    </li>
  );
}
