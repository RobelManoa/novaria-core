import { Navigate, Outlet, useLocation } from "react-router";
import { useAuth } from "./AuthContext";

export const LOGIN_PATH = "/connexion";

/**
 * Route de mise en page des pages protégées. Sans session, aucune page enfant n'est rendue : on renvoie
 * à la connexion en retenant l'adresse demandée, pour y revenir après la connexion.
 */
export default function RequireAuth() {
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  if (!isAuthenticated) {
    const from = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to={LOGIN_PATH} replace state={{ from }} />;
  }
  return <Outlet />;
}
