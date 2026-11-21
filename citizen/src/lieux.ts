import lieux from "./lieux.json";
import { APPROACHES, type Approach } from "./types";

/**
 * Les noms que lit un citoyen (ADR-031, D4) : jamais `ROAD_017` ni `INT_05`.
 * Le réseau est une démonstration fictive de six carrefours à quatre tronçons chacun : les noms sont fictifs aussi, et l'écran le dit
 * (« Données simulées »). `lieux.json` est la seule source : un test Python vérifie qu'aucun nom ne contient un code du système.
 */
export const LIEUX: Readonly<Record<string, string>> = lieux;

const COTE: Record<Approach, string> = {
  N: "en venant du nord",
  E: "en venant de l'est",
  S: "en venant du sud",
  W: "en venant de l'ouest",
};

/** Les tronçons du réseau de démonstration, dans l'ordre : `ROAD_001` à `ROAD_004` au carrefour 1, et ainsi de suite. */
export const TRONCONS: readonly string[] = Object.keys(LIEUX).flatMap((_, i) =>
  APPROACHES.map((__, j) => `ROAD_${String(i * APPROACHES.length + j + 1).padStart(3, "0")}`),
);

export interface Lieu {
  intersection: string;
  nom: string;
  troncons: { id: string; approach: Approach; nom: string }[];
}

function decrire(id: string): { intersection: string; approach: Approach } | null {
  const trouve = /^ROAD_(\d{3})$/.exec(id);
  if (!trouve) return null;
  const rang = Number(trouve[1]) - 1;
  const intersection = Object.keys(LIEUX)[Math.floor(rang / APPROACHES.length)];
  return intersection ? { intersection, approach: APPROACHES[rang % APPROACHES.length] } : null;
}

/** « Place de la Gare, en venant du nord ». Un tronçon inconnu n'est jamais montré par son code. */
export function nomDuTroncon(id: string): string {
  const d = decrire(id);
  return d ? `${LIEUX[d.intersection]}, ${COTE[d.approach]}` : "Un tronçon inconnu";
}

/** Le carrefour d'un tronçon (`INT_01`), ou null si le tronçon est inconnu. Sert aux faits fixes du réseau ; jamais montré à l'écran. */
export function intersectionDuTroncon(id: string): string | null {
  return decrire(id)?.intersection ?? null;
}

export function nomDuLieu(id: string): string {
  const d = decrire(id);
  return d ? LIEUX[d.intersection] : "Un lieu inconnu";
}

/** Tous les lieux avec leurs quatre tronçons : la liste du choix, même quand l'API n'a pas encore de mesure pour eux. */
export function tousLesLieux(): Lieu[] {
  return Object.entries(LIEUX).map(([intersection, nom], i) => ({
    intersection,
    nom,
    troncons: APPROACHES.map((approach, j) => ({
      id: `ROAD_${String(i * APPROACHES.length + j + 1).padStart(3, "0")}`,
      approach,
      nom: nomDuTroncon(`ROAD_${String(i * APPROACHES.length + j + 1).padStart(3, "0")}`),
    })),
  }));
}
