import { useEffect, useState } from "react";

/**
 * Six écrans, sans bibliothèque de routage : l'accueil, le détail d'un trajet, la carte, l'ajout d'un trajet, les messages et les réglages. L'adresse est un fragment (`#/trajet/<id>`), donc le bouton
 * « retour » du navigateur marche et rien n'est demandé au serveur. L'identifiant est celui d'un trajet gardé sur l'appareil : il ne
 * quitte jamais l'appareil (le fragment n'est pas envoyé dans une requête).
 */
export type Route =
  | { nom: "accueil" }
  | { nom: "detail"; id: string }
  | { nom: "messages" }
  | { nom: "reglages" }
  | { nom: "carte" }
  /** `lieu` : le rang (à partir de 0) d'une place à mettre en avant, quand on vient de la carte. */
  | { nom: "ajouter"; lieu?: number };

export const ACCUEIL = "#/";
export const MESSAGES = "#/messages";
export const REGLAGES = "#/reglages";
export const CARTE = "#/carte";

/** `#/ajouter?lieu=3` : la troisième place (à partir de 1, pour que l'adresse ne montre aucun code du système). */
export function lienAjouter(lieu?: number): string {
  return lieu === undefined ? "#/ajouter" : `#/ajouter?lieu=${lieu + 1}`;
}

export function lienDetail(id: string): string {
  return `#/trajet/${id}`;
}

export function lireRoute(fragment: string): Route {
  if (fragment === MESSAGES) return { nom: "messages" };
  if (fragment === REGLAGES) return { nom: "reglages" };
  if (fragment === CARTE) return { nom: "carte" };
  const ajout = /^#\/ajouter(?:\?lieu=(\d{1,2}))?$/.exec(fragment);
  if (ajout) return ajout[1] ? { nom: "ajouter", lieu: Number(ajout[1]) - 1 } : { nom: "ajouter" };
  const trouve = /^#\/trajet\/([\w-]+)$/.exec(fragment);
  return trouve?.[1] ? { nom: "detail", id: trouve[1] } : { nom: "accueil" };
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => lireRoute(window.location.hash));
  useEffect(() => {
    const suivre = () => setRoute(lireRoute(window.location.hash));
    window.addEventListener("hashchange", suivre);
    return () => window.removeEventListener("hashchange", suivre);
  }, []);
  return route;
}
