"""Le seuil d'acceptation du cadrage ML (section 6), fixé avant l'entraînement : cinq conditions sur l'ensemble de test.

Les valeurs ne se changent pas ici : un changement est un avenant du cadrage (section 12), daté et commité avant
l'évaluation qu'il concerne.
"""

from dataclasses import dataclass

from mesures.metriques import Mesures

MARGE = 0.01  # A1 et A2 : le modèle bat la référence d'au moins 0,01
BORNE_FAUSSES_ALERTES = 0.10  # A5 : par tronçon et par jour
ECART_D_EGALITE = 0.002  # entre deux candidats, en dessous : le plus simple (cadrage, section 7)
EPSILON = 1e-9  # tolérance de comparaison de flottants, pas une marge de jugement


@dataclass(frozen=True)
class Condition:
    numero: str
    libelle: str
    modele: float | None
    exige: str
    remplie: bool

    def en_dict(self) -> dict:
        return {"condition": self.numero, "libelle": self.libelle, "modele": None if self.modele is None else round(self.modele, 4),
                "exige": self.exige, "remplie": self.remplie}


def conditions(modele: Mesures, reference: Mesures) -> list[Condition]:
    """A1 à A5 du modèle face à la référence, mesurés sur le même ensemble."""
    a, r = modele.alertes, reference.alertes
    seuil_f1 = reference.f1_macro + MARGE
    seuil_rappel = reference.rappel_congested + MARGE
    delai_ok = a.delai_median is not None and (r.delai_median is None or a.delai_median <= r.delai_median)
    return [
        Condition("A1", "F1 macro ≥ référence + 0,01", modele.f1_macro, f"≥ {seuil_f1:.4f}", modele.f1_macro >= seuil_f1 - EPSILON),
        Condition("A2", "rappel de CONGESTED ≥ référence + 0,01", modele.rappel_congested, f"≥ {seuil_rappel:.4f}",
                  modele.rappel_congested >= seuil_rappel - EPSILON),
        Condition("A3", "délai médian ≤ référence", a.delai_median, f"≤ {r.delai_median} min", delai_ok),
        Condition("A4", "aucun épisode manqué", float(a.manques), "0", a.manques == 0),
        Condition("A5", "fausses alertes ≤ 0,10 par tronçon et par jour", a.fausses_par_troncon_et_jour,
                  f"≤ {BORNE_FAUSSES_ALERTES}", a.fausses_par_troncon_et_jour <= BORNE_FAUSSES_ALERTES + EPSILON),
    ]


def eligible(mesures: Mesures) -> bool:
    """Condition A5 seule : un candidat qui clignote n'est pas éligible, quel que soit son F1 (cadrage, section 7)."""
    return mesures.alertes.fausses_par_troncon_et_jour <= BORNE_FAUSSES_ALERTES + EPSILON


def accepte(liste: list[Condition]) -> bool:
    return all(c.remplie for c in liste)
