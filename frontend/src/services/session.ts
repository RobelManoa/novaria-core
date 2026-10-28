// Jeton d'accès de la session, avec sa date d'expiration.
//
// Stockage : `sessionStorage`, propre à l'onglet et vidé à sa fermeture. Un rechargement de la page garde
// la session, et un autre onglet doit se reconnecter. On n'utilise jamais `localStorage` : il survivrait à
// la fermeture du navigateur. Un script injecté pourrait lire le jeton ; ce risque est limité par la durée
// de vie courte (1800 s par défaut, voir contracts/openapi/README.md) et l'absence de jeton de
// renouvellement. Si le stockage est indisponible (navigation privée, accès refusé), le jeton reste en
// mémoire et la session ne survit pas à un rechargement.

const STORAGE_KEY = "novaria-session";

interface StoredSession {
  token: string;
  /** Instant d'expiration en millisecondes, ou null si l'API n'a pas donné de durée. */
  expiresAt: number | null;
}

let memory: StoredSession | null = null;
const listeners = new Set<() => void>();

function storage(): Storage | null {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    return null;
  }
}

function isStoredSession(value: unknown): value is StoredSession {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.token === "string" &&
    candidate.token !== "" &&
    (candidate.expiresAt === null || typeof candidate.expiresAt === "number")
  );
}

function read(): StoredSession | null {
  const store = storage();
  if (!store) return memory;
  try {
    const raw = store.getItem(STORAGE_KEY);
    if (raw === null) return memory;
    const parsed: unknown = JSON.parse(raw);
    return isStoredSession(parsed) ? parsed : null;
  } catch {
    return memory;
  }
}

function write(session: StoredSession | null): void {
  memory = session;
  const store = storage();
  if (!store) return;
  try {
    if (session) store.setItem(STORAGE_KEY, JSON.stringify(session));
    else store.removeItem(STORAGE_KEY);
  } catch {
    // quota ou accès refusé : le jeton reste en mémoire
  }
}

function notify(): void {
  listeners.forEach((listener) => listener());
}

function isExpired(session: StoredSession): boolean {
  return session.expiresAt !== null && Date.now() >= session.expiresAt;
}

/** Jeton valide, ou null sans session ou si elle a expiré. Sans effet de bord : utilisable pendant un rendu. */
export function peekAccessToken(): string | null {
  const session = read();
  return session && !isExpired(session) ? session.token : null;
}

/** Jeton à envoyer, ou null. Une session expirée est effacée et signalée aux abonnés. */
export function getAccessToken(): string | null {
  const token = peekAccessToken();
  if (token === null && read() !== null) clearSession();
  return token;
}

/** Instant d'expiration de la session en millisecondes, ou null (pas de session, ou durée inconnue). */
export function getSessionExpiry(): number | null {
  return read()?.expiresAt ?? null;
}

/** Ouvre la session avec le jeton reçu de `POST /api/v1/auth/login` ; `null` la ferme. */
export function setAccessToken(token: string | null, expiresInSeconds?: number): void {
  if (token === null) {
    write(null);
  } else {
    const expiresAt = expiresInSeconds === undefined ? null : Date.now() + expiresInSeconds * 1000;
    write({ token, expiresAt });
  }
  notify();
}

export function clearSession(): void {
  setAccessToken(null);
}

/** Appelle `listener` à chaque ouverture ou fermeture de session ; renvoie la fonction qui se désabonne. */
export function subscribeToSession(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
