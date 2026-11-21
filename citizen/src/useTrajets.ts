import { useCallback, useState } from "react";
import { effacer, ecrire, lire } from "./stockage";
import { MAX_TRAJETS, TRAJETS_PROPOSES, type Trajet } from "./trajets";

export interface TrajetsEtat {
  /** Les trajets que le citoyen a gardés. */
  trajets: readonly Trajet[];
  /** Vrai tant que rien n'a jamais été gardé : l'écran montre alors les trajets proposés. */
  premiereVisite: boolean;
  /** Faux si le navigateur refuse le stockage : l'application marche, sans mémoire (l'écran le dit). */
  memoire: boolean;
  proposes: readonly Trajet[];
  ajouter: (trajet: Trajet) => void;
  supprimer: (id: string) => void;
  basculerPrevenir: (id: string) => void;
  toutEffacer: () => void;
}

/**
 * Les trajets du citoyen, gardés sur son appareil (ADR-031, D3) à chaque changement. Les trajets proposés ne sont pas des trajets du
 * citoyen tant qu'il ne les a pas gardés : rien n'est écrit à l'ouverture.
 */
export function useTrajets(): TrajetsEtat {
  const [etat, setEtat] = useState(() => {
    const lecture = lire();
    return {
      trajets: lecture.trajets ?? [],
      gardes: lecture.trajets !== null,
      memoire: lecture.disponible,
    };
  });

  const changer = useCallback((suite: (avant: readonly Trajet[]) => readonly Trajet[]) => {
    setEtat((avant) => {
      const trajets = suite(avant.trajets).slice(0, MAX_TRAJETS);
      const ecrit = ecrire(trajets);
      return { trajets: [...trajets], gardes: true, memoire: ecrit };
    });
  }, []);

  return {
    trajets: etat.trajets,
    premiereVisite: !etat.gardes,
    memoire: etat.memoire,
    proposes: TRAJETS_PROPOSES.filter(
      (p) => !etat.trajets.some((t) => t.troncons.join() === p.troncons.join()),
    ),
    ajouter: (trajet) => changer((avant) => [...avant, trajet]),
    supprimer: (id) => changer((avant) => avant.filter((t) => t.id !== id)),
    basculerPrevenir: (id) =>
      changer((avant) => avant.map((t) => (t.id === id ? { ...t, prevenir: !t.prevenir } : t))),
    toutEffacer: () => {
      effacer();
      setEtat({ trajets: [], gardes: false, memoire: true });
    },
  };
}
