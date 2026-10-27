import { LOGIN_PATH } from "./RequireAuth";

/**
 * Adresse où aller après la connexion. Seul un chemin interne est accepté (pas d'adresse externe ni
 * de « //hote ») : une valeur douteuse renvoie au tableau de bord.
 */
export function redirectTarget(state: unknown): string {
  const from =
    typeof state === "object" && state !== null ? (state as { from?: unknown }).from : undefined;
  if (typeof from !== "string") return "/";
  if (!from.startsWith("/") || from.startsWith("//") || from.startsWith("/\\")) return "/";
  if (from === LOGIN_PATH || from.startsWith(`${LOGIN_PATH}?`)) return "/";
  return from;
}
