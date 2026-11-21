import { useEffect, useState } from "react";

/**
 * Deux écrans, sans bibliothèque de routage : l'accueil et le détail d'un trajet. L'adresse est un fragment (`#/trajet/<id>`), donc le bouton
 * « retour » du navigateur marche et rien n'est demandé au serveur. L'identifiant est celui d'un trajet gardé sur l'appareil : il ne
 * quitte jamais l'appareil (le fragment n'est pas envoyé dans une requête).
 */
export type Route = { nom: "accueil" } | { nom: "detail"; id: string };

export const ACCUEIL = "#/";

export function lienDetail(id: string): string {
  return `#/trajet/${id}`;
}

export function lireRoute(fragment: string): Route {
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
