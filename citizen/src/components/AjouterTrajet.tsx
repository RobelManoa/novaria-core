import { useId, useState } from "react";
import { nomDuLieu, tousLesLieux } from "../lieux";
import { MAX_NOM, MAX_TRONCONS, nouvelIdentifiant, type Trajet } from "../trajets";

/** Ajouter un trajet en trois gestes : cocher 1 à 4 tronçons, (facultatif) lui donner un nom, valider. */
export function AjouterTrajet({
  onAjouter,
  onFermer,
}: {
  onAjouter: (t: Trajet) => void;
  onFermer: () => void;
}) {
  const [choisis, setChoisis] = useState<string[]>([]);
  const [nom, setNom] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const idNom = useId();

  const basculer = (id: string) => {
    setErreur(null);
    setChoisis((liste) => (liste.includes(id) ? liste.filter((x) => x !== id) : [...liste, id]));
  };

  const valider = (evenement: React.FormEvent) => {
    evenement.preventDefault();
    if (choisis.length === 0) return setErreur("Choisissez au moins un tronçon.");
    if (choisis.length > MAX_TRONCONS)
      return setErreur(`Choisissez ${MAX_TRONCONS} tronçons au plus.`);
    const propre = nom.trim().slice(0, MAX_NOM);
    onAjouter({
      id: nouvelIdentifiant(),
      nom: propre || `Trajet par ${nomDuLieu(choisis[0])}`.slice(0, MAX_NOM),
      troncons: choisis,
      prevenir: false,
    });
  };

  return (
    <form className="ajout" onSubmit={valider} aria-labelledby="titre-ajout">
      <h3 id="titre-ajout">Ajouter un trajet</h3>
      <p className="ajout__aide">Cochez les endroits que vous traversez (de 1 à {MAX_TRONCONS}).</p>
      {tousLesLieux().map((lieu) => (
        <fieldset key={lieu.intersection} className="ajout__lieu">
          <legend>{lieu.nom}</legend>
          {lieu.troncons.map((t) => (
            <label key={t.id} className="ajout__choix">
              <input
                type="checkbox"
                checked={choisis.includes(t.id)}
                onChange={() => basculer(t.id)}
              />
              <span>{t.nom}</span>
            </label>
          ))}
        </fieldset>
      ))}
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
      </div>
      {erreur ? (
        <p className="avis avis--attention" role="alert">
          {erreur}
        </p>
      ) : null}
      <div className="ajout__actions">
        <button type="submit" className="bouton">
          Ajouter ce trajet
        </button>
        <button type="button" className="bouton bouton--discret" onClick={onFermer}>
          Annuler
        </button>
      </div>
    </form>
  );
}
