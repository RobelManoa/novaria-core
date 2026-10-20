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
