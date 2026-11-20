import type { ErrorKind } from "./api";

/** Ce que lit un citoyen quand ça ne marche pas : une cause en mots simples et quoi faire, jamais un code technique. */
export const ERROR_MESSAGE: Record<ErrorKind, string> = {
  reseau: "Impossible de joindre le service. Vérifiez votre connexion, puis réessayez.",
  limite: "Trop de demandes en peu de temps. Patientez quelques secondes, puis réessayez.",
  indisponible:
    "Le service de circulation est momentanément indisponible. Réessayez dans un instant.",
  inattendue: "L'information reçue n'est pas exploitable. Réessayez dans un instant.",
  format: "L'information reçue n'est pas exploitable. Réessayez dans un instant.",
};
