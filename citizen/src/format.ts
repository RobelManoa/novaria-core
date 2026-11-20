/** Une date UTC du contrat (`2026-11-20T09:10:00Z`) vue de l'appareil : « 10:10 ». */
export function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "heure inconnue";
  return date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

/** « à l'instant », « il y a 3 min », « il y a 2 h », « il y a 3 j ». Jamais de valeur négative (horloge en avance). */
export function ago(now: number, then: number): string {
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 60) return "à l'instant";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `il y a ${hours} h`;
  return `il y a ${Math.floor(hours / 24)} j`;
}

/** Au-delà de ce délai, l'information n'est plus « en direct » : l'écran le dit. */
export const STALE_AFTER_MS = 10 * 60 * 1000;
