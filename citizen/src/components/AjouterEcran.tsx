import { useEffect, useId, useRef, useState } from "react";
import { nomDuLieu, nomDuTroncon, tousLesLieux } from "../lieux";
import type { SegmentState } from "../types";
import { MAX_NOM, MAX_TRONCONS, nouvelIdentifiant, type Trajet } from "../trajets";
import { verdictDuTrajet } from "../verdict";
import { Croix } from "./Croix";
import { Legende } from "./Legende";
import { VerdictBadge } from "./VerdictBadge";

interface Props {
  parId: ReadonlyMap<string, SegmentState>;
  /** Le rang d'une place à montrer d'abord (quand on vient de la carte). */
  lieu?: number;
  onAjouter: (t: Trajet) => void;
}

/**
 * Ajouter un trajet (maquette C) : on touche les côtés des places que l'on traverse, de 1 à 4, les couleurs disent l'état en ce moment ;
 * le verdict du trajet se lit avant de le garder. Pas de carte et pas d'itinéraire : on choisit les endroits, l'application dit ce qu'il en est.
 */
export function AjouterEcran({ parId, lieu, onAjouter }: Props) {
  const [choisis, setChoisis] = useState<string[]>([]);
  const [nom, setNom] = useState("");
  const [prevenir, setPrevenir] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const idNom = useId();
  const lieux = tousLesLieux();
  const enAvant = useRef<HTMLFieldSetElement>(null);
  useEffect(() => enAvant.current?.scrollIntoView?.({ block: "center" }), [lieu]);

  const basculer = (id: string) => {
    setErreur(null);
    setChoisis((liste) => (liste.includes(id) ? liste.filter((x) => x !== id) : [...liste, id]));
  };

  const valider = (evenement: React.FormEvent) => {
    evenement.preventDefault();
    if (choisis.length === 0) return setErreur("Choisissez au moins un tronçon.");
    if (choisis.length > MAX_TRONCONS)
      return setErreur(`Choisissez ${MAX_TRONCONS} tronçons au plus.`);
    onAjouter({
      id: nouvelIdentifiant(),
      nom: nom.trim().slice(0, MAX_NOM) || `Trajet par ${nomDuLieu(choisis[0])}`.slice(0, MAX_NOM),
      troncons: choisis,
      prevenir,
    });
  };

  const lecture = choisis.length > 0 ? verdictDuTrajet({ troncons: choisis }, parId) : null;

  return (
    <form className="ajout" onSubmit={valider} aria-labelledby="titre-ajout">
      <p className="bloc__aide">
        Touchez les <strong>endroits que vous traversez</strong> (de 1 à {MAX_TRONCONS}). Les
        couleurs montrent l'état en ce moment.
      </p>
      <Legende />
      <div className="ajout__lieux">
        {lieux.map((l, i) => (
          <fieldset
            key={l.intersection}
            className="ajout__lieu"
            ref={i === lieu ? enAvant : undefined}
          >
            <legend>{l.nom}</legend>
            <Croix lieu={l} parId={parId} choisis={choisis} onBasculer={basculer} />
          </fieldset>
        ))}
      </div>
      <p className="trajet__meta">
        N, E, S, O : on arrive par le nord, l'est, le sud ou l'ouest. Plan schématique d'une ville
        fictive.
      </p>

      <section aria-labelledby="titre-ajout" className="ajout__votre">
        <h2 id="titre-ajout">
          Votre trajet : {choisis.length} endroit{choisis.length > 1 ? "s" : ""}
        </h2>
        {choisis.length === 0 ? (
          <p className="trajet__meta">Touchez un côté d'une place pour commencer.</p>
        ) : (
          <ul className="liste">
            {choisis.map((id) => (
              <li key={id} className="ligne ligne--carte">
                <span>{nomDuTroncon(id)}</span>
                <button
                  type="button"
                  className="bouton bouton--discret bouton--petit"
                  onClick={() => basculer(id)}
                >
                  Retirer<span className="visuellement-cache"> {nomDuTroncon(id)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {lecture ? (
          <div aria-live="polite" className="ajout__verdict">
            <span>Ce trajet est en ce moment</span>
            <VerdictBadge verdict={lecture.verdict} />
          </div>
        ) : null}
        <div className="ajout__nom">
          <label htmlFor={idNom}>Nom du trajet (facultatif)</label>
          <input
            id={idNom}
            type="text"
            value={nom}
            maxLength={MAX_NOM}
            onChange={(e) => setNom(e.target.value)}
            autoComplete="off"
          />
          <span className="trajet__meta">
            Sans nom, nous écrivons : « Trajet par {choisis[0] ? nomDuLieu(choisis[0]) : "…"} ».
          </span>
        </div>
        <label className="interrupteur">
          <input
            type="checkbox"
            checked={prevenir}
            onChange={(e) => setPrevenir(e.target.checked)}
          />
          <span>Me prévenir si ce trajet se bloque</span>
        </label>
        {erreur ? (
          <p className="avis avis--attention" role="alert">
            {erreur}
          </p>
        ) : null}
        <div className="ajout__actions">
          <button type="submit" className="bouton">
            Ajouter ce trajet
          </button>
        </div>
      </section>
    </form>
  );
}
