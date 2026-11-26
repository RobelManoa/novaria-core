import { etatDuTroncon } from "../carte";
import { STATE_LABEL } from "../labels";
import type { Lieu } from "../lieux";
import type { SegmentState } from "../types";
import { StateIcon } from "./StateBadge";

const COTE = { N: "n", E: "e", S: "s", W: "w" } as const;
const LETTRE = { N: "N", E: "E", S: "S", W: "O" } as const;

interface Props {
  lieu: Lieu;
  parId: ReadonlyMap<string, SegmentState>;
  /** Avec `onBasculer`, chaque côté est un bouton (on choisit ses endroits) ; sans, la croix est un dessin (la carte). */
  choisis?: readonly string[];
  onBasculer?: (id: string) => void;
}

/**
 * Une place vue d'en haut : un rond au centre et quatre côtés d'où arrive la circulation (nord, est, sud, ouest). Chaque côté dit son état par
 * une couleur, une forme et un contour (pointillé pour « ralenti ») : jamais la couleur seule. Un côté choisi est plein, avec une coche.
 */
export function Croix({ lieu, parId, choisis = [], onBasculer }: Props) {
  return (
    <div className="croix">
      <span className="croix__centre" aria-hidden="true" />
      {lieu.troncons.map((t) => {
        const etat = etatDuTroncon(t.id, parId);
        const classe = `croix__bras croix__bras--${COTE[t.approach]} croix__bras--${etat
          .toLowerCase()
          .replace("_", "-")}`;
        const choisi = choisis.includes(t.id);
        const contenu = (
          <>
            {onBasculer ? <span className="croix__lettre">{LETTRE[t.approach]}</span> : null}
            <StateIcon state={etat} />
            {choisi ? (
              <span className="croix__coche" aria-hidden="true">
                <svg viewBox="0 0 24 24" width="14" height="14" focusable="false">
                  <path
                    d="M5 12.5l4.5 4.5L19 7"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="3.2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
            ) : null}
          </>
        );
        return onBasculer ? (
          <button
            key={t.id}
            type="button"
            className={`${classe}${choisi ? " croix__bras--choisi" : ""}`}
            aria-pressed={choisi}
            aria-label={`${t.nom} : ${STATE_LABEL[etat].toLowerCase()}`}
            onClick={() => onBasculer(t.id)}
          >
            {contenu}
          </button>
        ) : (
          <span key={t.id} className={classe} aria-hidden="true">
            {contenu}
          </span>
        );
      })}
    </div>
  );
}
