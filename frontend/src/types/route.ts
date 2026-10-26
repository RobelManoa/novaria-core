/** Données attachées à chaque route (propriété `handle` de react-router). */
export interface RouteHandle {
  /** Titre de la page, repris dans document.title. */
  title: string;
}

export function isRouteHandle(value: unknown): value is RouteHandle {
  return (
    typeof value === "object" && value !== null && typeof (value as RouteHandle).title === "string"
  );
}
