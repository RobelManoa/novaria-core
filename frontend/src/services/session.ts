// Jeton d'accès de la session. Gardé en mémoire seulement : jamais dans localStorage, qu'un script
// injecté pourrait lire. Un rechargement de la page demande donc de se reconnecter (pas de jeton de
// renouvellement en v1, voir contracts/openapi/README.md).
let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}
