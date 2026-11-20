import type { Approach, CongestionState } from "./types";

/** Vocabulaire public de l'ADR-030 (section 4.2) : les mots de l'écran, jamais les codes techniques. */
export const STATE_LABEL: Record<CongestionState, string> = {
  FREE_FLOW: "Fluide",
  SLOW: "Ralenti",
  CONGESTED: "Congestionné",
  UNKNOWN: "Information indisponible",
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
