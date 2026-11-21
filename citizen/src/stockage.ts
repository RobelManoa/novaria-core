import { MAX_NOM, MAX_TRAJETS, MAX_TRONCONS, type Trajet } from "./trajets";

/**
 * LE SEUL fichier qui touche au stockage du navigateur (ADR-031, D3 ; la règle de lint qui l'interdit ailleurs a une exception pour lui).
 *
 * Ce qui est gardé : la liste des trajets du citoyen (nom, identifiants de tronçons, « Me prévenir »). Rien d'autre : ni date de visite, ni
 * identifiant de visiteur, ni position. Jamais envoyé au serveur, jamais dans un cookie. Une donnée illisible ou d'une autre version est
 * ignorée sans erreur : l'application repart des trajets proposés.
 */
export const CLE = "novaria-citoyen-trajets";
export const VERSION = 1;

export interface Lecture {
  /** `null` : rien de gardé (première visite, donnée illisible ou stockage absent). */
  trajets: Trajet[] | null;
  /** Faux si le navigateur refuse le stockage (mode privé…) : l'application marche, sans mémoire. */
  disponible: boolean;
}

function stockage(): Storage | null {
  try {
    const s = window.localStorage;
    const sonde = "novaria-citoyen-sonde";
    s.setItem(sonde, "1");
    s.removeItem(sonde);
    return s;
  } catch {
    return null;
  }
}

function estTrajet(valeur: unknown): valeur is Trajet {
  if (typeof valeur !== "object" || valeur === null) return false;
  const t = valeur as Record<string, unknown>;
  return (
    Object.keys(t).length === 4 &&
    typeof t.id === "string" &&
    t.id.length > 0 &&
    t.id.length <= 60 &&
    typeof t.nom === "string" &&
    t.nom.length > 0 &&
    t.nom.length <= MAX_NOM &&
    typeof t.prevenir === "boolean" &&
    Array.isArray(t.troncons) &&
    t.troncons.length >= 1 &&
    t.troncons.length <= MAX_TRONCONS &&
    t.troncons.every((id) => typeof id === "string" && /^ROAD_\d{3}$/.test(id))
  );
}

export function lire(): Lecture {
  const s = stockage();
  if (!s) return { trajets: null, disponible: false };
  try {
    const brut = s.getItem(CLE);
    if (brut === null) return { trajets: null, disponible: true };
    const corps: unknown = JSON.parse(brut);
    if (typeof corps !== "object" || corps === null) return { trajets: null, disponible: true };
    const { version, trajets } = corps as { version?: unknown; trajets?: unknown };
    if (version !== VERSION || !Array.isArray(trajets) || trajets.length > MAX_TRAJETS) {
      return { trajets: null, disponible: true };
    }
    return { trajets: trajets.every(estTrajet) ? (trajets as Trajet[]) : null, disponible: true };
  } catch {
    return { trajets: null, disponible: true };
  }
}

/** Vrai si c'est écrit. Une liste vide est gardée telle quelle : « j'ai supprimé tous mes trajets » n'est pas « première visite ». */
export function ecrire(trajets: readonly Trajet[]): boolean {
  const s = stockage();
  if (!s) return false;
  try {
    s.setItem(CLE, JSON.stringify({ version: VERSION, trajets }));
    return true;
  } catch {
    return false;
  }
}

/** Tout part : le citoyen retrouve l'application comme à sa première visite. */
export function effacer(): void {
  try {
    stockage()?.removeItem(CLE);
  } catch {
    /* rien à effacer */
  }
}
