/** Un trajet : une liste de 1 à 4 tronçons que le citoyen suit ensemble (ADR-031, D1). Le réseau n'a pas de carte : aucun itinéraire n'est calculé. */
export interface Trajet {
  id: string;
  nom: string;
  troncons: string[];
  /** « Me prévenir » : un message s'affiche ici quand une alerte s'ouvre sur ce trajet. Simulé : rien n'est envoyé. */
  prevenir: boolean;
}

export const MAX_TRONCONS = 4;
export const MAX_TRAJETS = 12;
export const MAX_NOM = 40;

/** Montrés à la première ouverture, pour qu'un écran vide n'arrête personne. Ils ne sont gardés que si le citoyen les garde. */
export const TRAJETS_PROPOSES: readonly Trajet[] = [
  {
    id: "propose-gare",
    nom: "Aller à la gare",
    troncons: ["ROAD_001", "ROAD_004"],
    prevenir: false,
  },
  {
    id: "propose-marche",
    nom: "Aller au marché",
    troncons: ["ROAD_009", "ROAD_010"],
    prevenir: false,
  },
  {
    id: "propose-ecoles",
    nom: "Déposer les enfants à l'école",
    troncons: ["ROAD_019", "ROAD_020"],
    prevenir: false,
  },
];

export function nouvelIdentifiant(): string {
  return `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}
