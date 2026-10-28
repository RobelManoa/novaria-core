import { createBrowserRouter, type RouteObject } from "react-router";
import RequireAuth, { LOGIN_PATH } from "@/features/auth/RequireAuth";
import AlertsPage from "@/pages/AlertsPage";
import DashboardPage from "@/pages/DashboardPage";
import ForecastsPage from "@/pages/ForecastsPage";
import LoginPage from "@/pages/LoginPage";
import NotFoundPage from "@/pages/NotFoundPage";
import ReportsPage from "@/pages/ReportsPage";
import TrafficLightsPage from "@/pages/TrafficLightsPage";
import type { RouteHandle } from "@/types/route";
import AppShell from "./AppShell/AppShell";

const handle = (title: string): RouteHandle => ({ title });

/** Tableau de routes exporté : l'application utilise un routeur navigateur, les tests un routeur mémoire. */
export const routes: RouteObject[] = [
  { path: LOGIN_PATH, element: <LoginPage />, handle: handle("Connexion") },
  {
    // Tout le reste exige une session : sans elle, RequireAuth renvoie à la connexion.
    element: <RequireAuth />,
    children: [
      {
        path: "/",
        element: <AppShell />,
        children: [
          { index: true, element: <DashboardPage />, handle: handle("Tableau de bord") },
          { path: "alertes", element: <AlertsPage />, handle: handle("Alertes") },
          { path: "feux", element: <TrafficLightsPage />, handle: handle("Feux de circulation") },
          { path: "previsions", element: <ForecastsPage />, handle: handle("Prévisions") },
          { path: "rapports", element: <ReportsPage />, handle: handle("Rapports") },
          { path: "*", element: <NotFoundPage />, handle: handle("Page introuvable") },
        ],
      },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(routes);
}
