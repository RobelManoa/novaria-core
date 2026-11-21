import { nomDuTroncon } from "./lieux";
import type { CongestionState, SegmentState } from "./types";
import type { Trajet } from "./trajets";

/**
 * La décision de départ d'un trajet (ADR-031, D2) : une RÈGLE appliquée au pire état de ses tronçons, jamais une estimation.
 * Aucune durée de trajet n'est annoncée : aucune donnée ne le permet.
 */
export type Verdict = "LIBRE" | "RALENTI" | "BLOQUE" | "INCOMPLET" | "INDISPONIBLE";

export const VERDICT_TITRE: Record<Verdict, string> = {
  LIBRE: "Libre",
  RALENTI: "Ralenti",
  BLOQUE: "Bloqué",
  INCOMPLET: "Information incomplète",
  INDISPONIBLE: "Information indisponible",
};

export const VERDICT_PHRASE: Record<Verdict, string> = {
  LIBRE: "Vous pouvez partir.",
  RALENTI: "Partez si vous le pouvez : prévoyez un peu de retard.",
  BLOQUE: "Prévoyez beaucoup de retard. Si vous pouvez, attendez ou choisissez un autre trajet.",
  INCOMPLET:
    "Nous n'avons pas toutes les mesures de ce trajet : prenez cette information avec prudence.",
  INDISPONIBLE: "Nous n'avons pas assez de mesures : ne vous fiez pas à cette carte.",
};

/** L'état d'un tronçon qui donne sa forme et sa couleur à la carte (jamais la couleur seule : un mot et une forme l'accompagnent). */
export const VERDICT_ETAT: Record<Verdict, CongestionState> = {
  LIBRE: "FREE_FLOW",
  RALENTI: "SLOW",
  BLOQUE: "CONGESTED",
  INCOMPLET: "UNKNOWN",
  INDISPONIBLE: "UNKNOWN",
};

export interface LectureTroncon {
  id: string;
  nom: string;
  etat: CongestionState;
}

export interface VerdictDuTrajet {
  verdict: Verdict;
  troncons: LectureTroncon[];
  /** Les tronçons qui donnent le verdict : « où ça pose problème ». Vide si le trajet est libre. */
  critiques: LectureTroncon[];
  /** La mesure la plus récente parmi les tronçons, ou null s'il n'y en a aucune. */
  miseAJour: string | null;
}

/** Du plus grave au moins grave : l'ordre de « En ce moment : 1 bloqué, 1 ralenti, 1 libre ». */
export const VERDICTS_PAR_GRAVITE: readonly Verdict[] = [
  "BLOQUE",
  "RALENTI",
  "INCOMPLET",
  "INDISPONIBLE",
  "LIBRE",
];

/** Combien de trajets dans chaque verdict, sans les verdicts à zéro. */
export function resumeDesTrajets(
  trajets: readonly Pick<Trajet, "troncons">[],
  parId: ReadonlyMap<string, SegmentState>,
): { verdict: Verdict; n: number }[] {
  const verdicts = trajets.map((t) => verdictDuTrajet(t, parId).verdict);
  return VERDICTS_PAR_GRAVITE.map((verdict) => ({
    verdict,
    n: verdicts.filter((v) => v === verdict).length,
  })).filter(({ n }) => n > 0);
}

export function verdictDuTrajet(
  trajet: Pick<Trajet, "troncons">,
  parId: ReadonlyMap<string, SegmentState>,
): VerdictDuTrajet {
  const troncons = trajet.troncons.map((id) => ({
    id,
    nom: nomDuTroncon(id),
    etat: parId.get(id)?.state ?? ("UNKNOWN" as CongestionState),
  }));
  const a = (etat: CongestionState) => troncons.filter((t) => t.etat === etat);
  let verdict: Verdict;
  let critiques: LectureTroncon[] = [];
  if (a("CONGESTED").length > 0) {
    verdict = "BLOQUE";
    critiques = a("CONGESTED");
  } else if (a("SLOW").length > 0) {
    verdict = "RALENTI";
    critiques = a("SLOW");
  } else if (troncons.length > 0 && a("FREE_FLOW").length === troncons.length) {
    verdict = "LIBRE";
  } else if (a("FREE_FLOW").length === 0) {
    verdict = "INDISPONIBLE";
    critiques = a("UNKNOWN");
  } else {
    verdict = "INCOMPLET";
    critiques = a("UNKNOWN");
  }
  const dates = trajet.troncons
    .map((id) => parId.get(id)?.updated_at)
    .filter((d): d is string => !!d);
  const miseAJour =
    dates.length === 0 ? null : dates.reduce((meilleure, d) => (d > meilleure ? d : meilleure));
  return { verdict, troncons, critiques, miseAJour };
}
