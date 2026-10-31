// Toutes les valeurs affichées passent par ici : nombres à la française, heures en UTC comme l'API.

const LOCALE = "fr-FR";

const formatters = new Map<number, Intl.NumberFormat>();

function numberFormat(digits: number): Intl.NumberFormat {
  let format = formatters.get(digits);
  if (!format) {
    format = new Intl.NumberFormat(LOCALE, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    formatters.set(digits, format);
  }
  return format;
}

/** Valeur absente (aucune fenêtre avec véhicule, par exemple) : un tiret, jamais un zéro inventé. */
export const MISSING = "—";

export function formatNumber(value: number | null, digits: number): string {
  return value === null ? MISSING : numberFormat(digits).format(value);
}

const time = new Intl.DateTimeFormat(LOCALE, {
  timeZone: "UTC",
  hour: "2-digit",
  minute: "2-digit",
});
const dateTime = new Intl.DateTimeFormat(LOCALE, {
  timeZone: "UTC",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

/** Heure UTC d'un instant en millisecondes, par exemple « 08:55 ». */
export function formatTime(milliseconds: number): string {
  return time.format(milliseconds);
}

/** Date et heure UTC, par exemple « 30/10/2026 08:55 ». */
export function formatDateTime(milliseconds: number): string {
  return dateTime.format(milliseconds).replace(",", "");
}

/** Date UTC au format du contrat (`2026-10-30T08:55:00Z`), sans fraction de seconde. */
export function toApiDateTime(milliseconds: number): string {
  return new Date(milliseconds).toISOString().replace(".000Z", "Z");
}
