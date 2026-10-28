import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";
import { getCurrentUser, login as requestToken, type User } from "@/services/apiMetier";
import {
  clearSession,
  getAccessToken,
  getSessionExpiry,
  peekAccessToken,
  setAccessToken,
  subscribeToSession,
} from "@/services/session";
import { AuthContext } from "./AuthContext";

/** Plus grand délai accepté par `setTimeout` (au-delà, il se déclencherait aussitôt). */
const MAX_TIMEOUT_MS = 2 ** 31 - 1;

export default function AuthProvider({ children }: Readonly<{ children: ReactNode }>) {
  // Le jeton vit dans services/session.ts ; on s'y abonne pour réagir à une ouverture, une fermeture,
  // une expiration, ou un 401 reçu par n'importe quel appel d'API.
  const token = useSyncExternalStore(subscribeToSession, peekAccessToken);
  const [user, setUser] = useState<User | null>(null);

  // Profil du compte (nom, rôle). Un jeton que l'API refuse ferme la session dans le client d'API (401).
  useEffect(() => {
    if (token === null) {
      setUser(null);
      return;
    }
    let cancelled = false;
    getCurrentUser().then(
      (current) => {
        if (!cancelled) setUser(current);
      },
      () => {
        // 401 : session déjà fermée par le client. Autre erreur : le profil reste inconnu, la session demeure.
      },
    );
    return () => {
      cancelled = true;
    };
  }, [token]);

  // Un jeton expiré ferme la session sans attendre le prochain appel d'API.
  useEffect(() => {
    const expiry = getSessionExpiry();
    if (token === null || expiry === null) return;
    const delay = Math.min(Math.max(expiry - Date.now(), 0) + 50, MAX_TIMEOUT_MS);
    const timer = setTimeout(getAccessToken, delay);
    return () => clearTimeout(timer);
  }, [token]);

  const login = useCallback(async (username: string, password: string) => {
    const issued = await requestToken({ username, password });
    setAccessToken(issued.access_token, issued.expires_in);
  }, []);

  const logout = useCallback(() => clearSession(), []);

  const value = useMemo(
    () => ({ isAuthenticated: token !== null, user, login, logout }),
    [token, user, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
