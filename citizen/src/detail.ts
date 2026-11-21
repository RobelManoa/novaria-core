import type { PublicAlert, SegmentState } from "./types";
import type { Trajet } from "./trajets";
import { verdictDuTrajet, type Verdict } from "./verdict";

/**
 * Ce que le détail ajoute au verdict : des conseils tirés de RÈGLES sur l'état mesuré, jamais d'une durée ni d'une prévision
 * (ADR-031, phase 1 : aucune donnée ne permet de dire combien de temps ou quand ça se libère).
 */
export interface Conseil {
  maintenant: string;
  /** Null quand attendre n'a pas de sens (le trajet est libre). */
  attendre: string | null;
}

export const CONSEIL: Record<Verdict, Conseil> = {
  LIBRE: {
    maintenant: "Aucun endroit de ce trajet n'est ralenti : vous pouvez partir.",
    attendre: null,
  },
  RALENTI: {
    maintenant: "C'est possible : prévoyez un peu de retard.",
    attendre:
      "Nous ne pouvons pas prédire quand ça se libère. Revenez voir, ou laissez-nous vous prévenir.",
  },
  BLOQUE: {
    maintenant: "C'est possible, mais prévoyez beaucoup de retard.",
    attendre:
      "Nous ne pouvons pas prédire quand ça se libère. Revenez voir, ou laissez-nous vous prévenir.",
  },
  INCOMPLET: {
    maintenant: "Prudence : il manque des mesures sur ce trajet.",
    attendre: "Revenez voir dans quelques minutes : les mesures manquantes peuvent revenir.",
  },
  INDISPONIBLE: {
    maintenant: "Prudence : nous n'avons aucune mesure récente pour ce trajet.",
    attendre: "Revenez voir dans quelques minutes : les mesures peuvent revenir.",
  },
};

export interface AutreTrajet {
  id: string;
  nom: string;
  verdict: Verdict;
}

/** Les autres trajets gardés avec leur verdict : de quoi comparer sans quitter l'écran. Le trajet lui-même n'y est pas. */
export function autresTrajets(
  trajet: Pick<Trajet, "id">,
  trajets: readonly Trajet[],
  parId: ReadonlyMap<string, SegmentState>,
): AutreTrajet[] {
  return trajets
    .filter((t) => t.id !== trajet.id)
    .map((t) => ({ id: t.id, nom: t.nom, verdict: verdictDuTrajet(t, parId).verdict }));
}

/** Les alertes ouvertes sur un tronçon du trajet, la plus récente d'abord. */
export function alertesDuTrajet(
  trajet: Pick<Trajet, "troncons">,
  alertes: readonly PublicAlert[],
): PublicAlert[] {
  return alertes
    .filter((a) => trajet.troncons.includes(a.road_segment_id))
    .sort((a, b) => b.opened_at.localeCompare(a.opened_at));
}
