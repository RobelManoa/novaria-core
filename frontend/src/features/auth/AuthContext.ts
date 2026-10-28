import { createContext, useContext } from "react";
import type { Role, User } from "@/services/apiMetier";

export interface AuthContextValue {
  /** Vrai tant qu'un jeton non expiré est détenu. Les routes protégées ne dépendent que de cette valeur. */
  isAuthenticated: boolean;
  /** Compte connecté, une fois `GET /api/v1/auth/me` reçu ; null avant, et sans session. */
  user: User | null;
  /** Ouvre la session ; lève une `ApiError` si l'API refuse les identifiants. */
  login: (username: string, password: string) => Promise<void>;
  /** Ferme la session (jeton effacé) ; la route protégée renvoie alors à la connexion. */
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth doit être utilisé dans un AuthProvider");
  return value;
}

export const ROLE_LABELS: Record<Role, string> = {
  viewer: "Lecteur",
  operator: "Opérateur",
  admin: "Administrateur",
};
