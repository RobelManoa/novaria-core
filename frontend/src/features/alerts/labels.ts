import type { Alert, AlertState } from "@/services/alerte";
import type { StreamStatus } from "@/services/alertStream";

export const STATE_LABELS: Record<AlertState, string> = {
  CREATED: "Créée",
  NOTIFIED: "Notifiée",
  ACKNOWLEDGED: "Acquittée",
  RESOLVED: "Résolue",
};

export const KIND_LABELS: Record<Alert["kind"], string> = {
  CONGESTION: "Congestion",
  TRAFFIC_ANOMALY: "Saturation",
  SENSOR_FAULT: "Capteur muet",
};

export const SEVERITY_LABELS: Record<Alert["severity"], string> = {
  INFO: "Information",
  WARNING: "Avertissement",
  CRITICAL: "Critique",
};

/** La cause n'est jamais affirmée sans événement confirmé : « Inconnue » est la règle (ADR-028). */
export const CAUSE_LABELS: Record<Alert["cause"], string> = {
  UNKNOWN: "Cause inconnue",
  CONFIRMED_INCIDENT: "Incident confirmé",
  ROADWORKS: "Travaux",
  SPECIAL_EVENT: "Événement",
  SENSOR_FAULT: "Défaut de capteur",
};

export const RESOLUTION_LABELS: Record<NonNullable<Alert["resolution"]>, string> = {
  AUTO: "automatique",
  MANUAL: "manuelle",
};

export const STREAM_LABELS: Record<StreamStatus, string> = {
  connecting: "Connexion au flux en direct…",
  live: "En direct",
  offline: "Flux interrompu : reconnexion en cours",
};
