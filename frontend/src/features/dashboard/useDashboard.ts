import { useCallback, useEffect, useState } from "react";
import type { Filters } from "./filters";
import { loadDashboard, type DashboardData } from "./load";

export type DashboardState =
  | { status: "loading" }
  | { status: "error"; error: unknown }
  | { status: "ready"; data: DashboardData };

type Outcome = { status: "error"; error: unknown } | { status: "ready"; data: DashboardData };

function sorted(zones: Iterable<string>): string[] {
  return [...zones].sort((a, b) => a.localeCompare(b));
}

/**
 * Charge le tableau de bord à chaque changement de filtre. Le résultat est rangé avec la clé des filtres
 * qui l'ont produit : tant qu'il ne correspond pas aux filtres courants, l'état est « chargement », et une
 * réponse tardive d'un ancien filtre ne s'affiche jamais.
 *
 * `zones` : les carrefours déjà vus dans une réponse. L'API n'a pas (encore) de liste de carrefours
 * utilisable ici ; tant qu'on regarde tout le réseau, chaque réponse enrichit la liste, et elle reste
 * disponible quand on choisit ensuite une zone.
 */
export function useDashboard(filters: Filters) {
  const { periodHours, windowSizeS, intersectionId } = filters;
  const [attempt, setAttempt] = useState(0);
  const [stored, setStored] = useState<{ key: string; outcome: Outcome } | null>(null);
  const [zones, setZones] = useState<string[]>([]);
  const key = `${periodHours}|${windowSizeS}|${intersectionId ?? ""}|${attempt}`;

  useEffect(() => {
    let current = true;
    loadDashboard({ periodHours, windowSizeS, intersectionId }).then(
      (data) => {
        if (!current) return;
        setStored({ key, outcome: { status: "ready", data } });
        if (intersectionId === null) {
          setZones((known) =>
            sorted(new Set([...known, ...data.indicators.map((item) => item.intersection_id)])),
          );
        }
      },
      (error: unknown) => {
        if (current) setStored({ key, outcome: { status: "error", error } });
      },
    );
    return () => {
      current = false;
    };
  }, [key, periodHours, windowSizeS, intersectionId]);

  const reload = useCallback(() => setAttempt((count) => count + 1), []);
  const state: DashboardState = stored?.key === key ? stored.outcome : { status: "loading" };
  return { state, zones, reload };
}
