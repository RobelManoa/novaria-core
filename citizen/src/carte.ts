import { TRONCONS, tousLesLieux } from "./lieux";
import type { CongestionState, SegmentState } from "./types";

/** L'état d'un tronçon ; « sans mesure » s'il n'est pas dans la réponse de l'API (aucune mesure récente). */
export function etatDuTroncon(
  id: string,
  parId: ReadonlyMap<string, SegmentState>,
): CongestionState {
  return parId.get(id)?.state ?? "UNKNOWN";
}

/** Combien d'endroits dans chaque état, sur les 24 du réseau (un endroit absent de l'API compte « sans mesure »). */
export function compterEndroits(
  parId: ReadonlyMap<string, SegmentState>,
): Record<CongestionState, number> {
  const n: Record<CongestionState, number> = { FREE_FLOW: 0, SLOW: 0, CONGESTED: 0, UNKNOWN: 0 };
  for (const id of TRONCONS) n[etatDuTroncon(id, parId)] += 1;
  return n;
}

const GRAVITE: Record<CongestionState, number> = {
  FREE_FLOW: 0,
  UNKNOWN: 1,
  SLOW: 2,
  CONGESTED: 3,
};

/** La première place où l'état est le plus grave : celle que la carte met en avant à l'ouverture. */
export function lieuLePlusGrave(parId: ReadonlyMap<string, SegmentState>): number {
  let meilleur = 0;
  let note = -1;
  tousLesLieux().forEach((lieu, i) => {
    const pire = Math.max(...lieu.troncons.map((t) => GRAVITE[etatDuTroncon(t.id, parId)]));
    if (pire > note) {
      note = pire;
      meilleur = i;
    }
  });
  return meilleur;
}
