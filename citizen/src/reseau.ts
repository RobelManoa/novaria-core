import reseau from "./reseau.json";
import { intersectionDuTroncon } from "./lieux";

/**
 * Les faits fixes d'un endroit, dits en mots simples : « Grand axe · 2 voies · 300 m · limité à 50 km/h ».
 * Ils ne viennent pas de l'API publique (qui ne donne que six champs, ADR-030) mais du réseau de démonstration, qui est fixe et fictif :
 * `reseau.json` en est une copie, et un test Python la compare à `scripts/dev/gen_reseau.py`, qui a produit la base.
 */
interface Faits {
  type: string;
  voies: number;
  longueur_m: number;
  limite_kmh: number;
}

const FAITS: Readonly<Record<string, Faits>> = reseau;

export const TYPE_DE_ROUTE: Readonly<Record<string, string>> = {
  MOTORWAY: "Autoroute",
  ARTERIAL: "Grand axe",
  COLLECTOR: "Rue de liaison",
  LOCAL: "Rue de quartier",
};

/** Vide si le tronçon est inconnu : l'écran ne montre alors aucun fait plutôt qu'un fait inventé. */
export function faitsDuTroncon(id: string): string {
  const intersection = intersectionDuTroncon(id);
  const faits = intersection ? FAITS[intersection] : undefined;
  if (!faits) return "";
  const route = TYPE_DE_ROUTE[faits.type] ?? "Route";
  const voies = `${faits.voies} ${faits.voies > 1 ? "voies" : "voie"}`;
  return `${route} · ${voies} · ${faits.longueur_m} m · limité à ${faits.limite_kmh} km/h`;
}
