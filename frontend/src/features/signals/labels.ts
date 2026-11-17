import type { Approach, SignalCommand, SignalDecision, SignalMode } from "@/services/reponse";

export const MODE_LABELS: Record<SignalMode, string> = {
  AUTOMATIC: "Automatique",
  MANUAL: "Manuel",
  DEGRADED_FIXED_PLAN: "Plan fixe (mode dégradé)",
};

export const MODE_HINTS: Record<SignalMode, string> = {
  AUTOMATIC: "Le carrefour suit les recommandations.",
  MANUAL: "Une commande d'opérateur tient la phase en cours.",
  DEGRADED_FIXED_PLAN: "Aucune recommandation reçue : le plan à durées fixes s'applique.",
};

export const APPROACH_LABELS: Record<Approach, string> = {
  N: "Nord",
  E: "Est",
  S: "Sud",
  W: "Ouest",
};

export const ORIGIN_LABELS: Record<SignalDecision["origin"], string> = {
  RECOMMENDATION: "Recommandation",
  MANUAL_COMMAND: "Commande manuelle",
  FIXED_PLAN_FALLBACK: "Retour au plan fixe",
  STARTUP: "Démarrage",
};

export const ACTION_LABELS: Record<SignalCommand["action"], string> = {
  SET_PHASE: "Imposer une phase",
  RESUME_AUTOMATIC: "Rendre la main",
};

export const STATUS_LABELS: Record<SignalCommand["status"], string> = {
  ACCEPTED: "Acceptée",
  APPLIED: "Appliquée",
  REFUSED: "Refusée",
  EXPIRED: "Expirée",
};

/** Motifs de refus des garde-fous (services/reponse, domain/safety.py). Un code inconnu est montré tel quel. */
export const REFUSAL_LABELS: Record<string, string> = {
  PHASE_TOO_SHORT: "Durée sous le minimum de sécurité (10 s)",
  PHASE_TOO_LONG: "Durée au-dessus du maximum (90 s)",
  CONFLICTING_GREENS: "Deux approches en conflit seraient au vert",
  CYCLE_OUT_OF_BOUNDS: "Cycle hors des bornes (30 à 120 s)",
  CYCLE_MISMATCH: "Cycle incohérent avec le plan",
  PHASE_LAYOUT_MISMATCH: "Phase absente du plan du carrefour",
  UNKNOWN_PHASE: "Phase inconnue de ce carrefour",
  MIN_DURATION_NOT_ELAPSED: "La phase en cours n'a pas encore duré 10 s",
  CLEARANCE_IN_PROGRESS: "Dégagement en cours : réessayer à la phase suivante",
  COMMAND_IN_PROGRESS: "Une commande manuelle est déjà en cours",
};

export function refusalLabel(code: string | null | undefined): string {
  if (!code) return "";
  return REFUSAL_LABELS[code] ?? code;
}

/** Durée limite de la commande, en secondes (contrat : 10 à 90 s). */
export const MIN_COMMAND_S = 10;
export const MAX_COMMAND_S = 90;
export const MIN_REASON_LENGTH = 3;
export const MAX_REASON_LENGTH = 500;
