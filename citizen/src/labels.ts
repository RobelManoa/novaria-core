import type { Approach, CongestionState, Severity } from "./types";

/**
 * Les mots de l'écran pour l'état d'un tronçon, jamais les codes techniques. Ce sont ceux de la maquette (Libre, Ralenti, Bloqué, Sans mesure) :
 * ils remplacent « Fluide » et « Congestionné » de l'ADR-030 pour parler comme le verdict d'un trajet (ADR-031, section 3.3).
 */
export const STATE_LABEL: Record<CongestionState, string> = {
  FREE_FLOW: "Libre",
  SLOW: "Ralenti",
  CONGESTED: "Bloqué",
  UNKNOWN: "Sans mesure",
};

/** Une phrase pour un lecteur d'écran et pour l'infobulle : ce que l'état veut dire pour un trajet. */
export const STATE_HELP: Record<CongestionState, string> = {
  FREE_FLOW: "La circulation est normale.",
  SLOW: "La circulation est plus lente que d'habitude.",
  CONGESTED: "La circulation est très dense, prévoyez du retard.",
  UNKNOWN: "Nous n'avons pas assez de mesures pour ce tronçon.",
};

export const APPROACH_LABEL: Record<Approach, string> = {
  N: "Arrivée par le nord",
  E: "Arrivée par l'est",
  S: "Arrivée par le sud",
  W: "Arrivée par l'ouest",
};

/** Du plus grave au moins grave : l'ordre des compteurs du résumé. */
export const STATE_ORDER: readonly CongestionState[] = [
  "CONGESTED",
  "SLOW",
  "FREE_FLOW",
  "UNKNOWN",
];

/** Gravité d'une alerte, en mots du public (ADR-030, section 4.2). */
export const SEVERITY_LABEL: Record<Severity, string> = {
  INFO: "Information",
  WARNING: "Attention",
  CRITICAL: "Critique",
};

export const SEVERITY_HELP: Record<Severity, string> = {
  INFO: "À titre d'information.",
  WARNING: "La circulation est fortement perturbée : prévoyez du retard.",
  CRITICAL: "Situation très perturbée : évitez ce tronçon si vous le pouvez.",
};
