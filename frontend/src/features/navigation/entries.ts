export interface NavEntry {
  path: string;
  label: string;
}

/** Entrées du menu principal, dans l'ordre d'affichage. */
export const NAV_ENTRIES: readonly NavEntry[] = [
  { path: "/", label: "Tableau de bord" },
  { path: "/alertes", label: "Alertes" },
  { path: "/feux", label: "Feux de circulation" },
  { path: "/previsions", label: "Prévisions" },
  { path: "/rapports", label: "Rapports" },
];

export interface ExternalNavEntry {
  href: string;
  label: string;
  /** Dit ce que le lien ouvre et ce qu'il faut avoir lancé : lu par les lecteurs d'écran et en infobulle. */
  hint: string;
}

/**
 * Outils locaux qui ne font pas partie de l'application : ils s'ouvrent dans un nouvel onglet.
 * L'observatoire (CLD-14, MS-16) est servi par `python3 scripts/dev/dev.py observatoire` sur 127.0.0.1 seulement ;
 * le lien ne marche donc que sur le poste où il tourne.
 */
export const EXTERNAL_ENTRIES: readonly ExternalNavEntry[] = [
  {
    href: "http://127.0.0.1:8090/",
    label: "Observatoire",
    hint: "s'ouvre dans un nouvel onglet ; lancer d'abord « dev.py observatoire » sur ce poste",
  },
];
