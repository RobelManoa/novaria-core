"""Quelles colonnes du jeu v1 entrent dans un modèle, et lesquelles n'y entrent jamais (cadrage ML, section 3).

Chaque colonne du jeu est classée : variable d'un usage, cible, ou interdite avec sa raison. Une colonne ajoutée au jeu
sans être classée fait échouer les tests : il faut décider avant qu'elle n'entre dans un modèle.
"""

from collections.abc import Collection
from dataclasses import dataclass

from jeu_entrainement.lignes import GROUPES, HORIZONS, NOMS
from preparation.calendrier import NOMS as CALENDRIER_DERIVE

CLES = tuple(c.nom for c in GROUPES["clé"])
MESURES = tuple(c.nom for c in GROUPES["mesures"])
HISTORIQUE = tuple(c.nom for c in GROUPES["historique"])
CALENDRIER = tuple(c.nom for c in GROUPES["calendrier"])
TRONCON_NUMERIQUE = ("lane_count", "length_m", "free_flow_speed_kmh")
TRONCON_CATEGORIE = ("road_type",)
CIBLE_DETECTION = "label_state"
CIBLES_PREVISION = tuple(f"speed_ratio_h{h}" for h in HORIZONS)

RAISONS = {
    "cle": "identifiant : mémoriser un run ou une minute n'est pas apprendre la circulation",
    "calendrier": "calendrier constant (un seul jour) et révélateur du scénario dans le jeu v1 : interdit pour la détection",
    "futur": "contient l'avenir de la même série : fuite directe",
    "verite": "vérité terrain de la minute : indisponible en production",
}


@dataclass(frozen=True)
class Usage:
    nom: str
    numeriques: tuple[str, ...]
    categorielles: tuple[str, ...]
    cible: str
    interdites: dict[str, str]  # colonne -> raison
    calendrier: bool = False  # ajoute les variables calendaires calculées depuis `window_start`

    @property
    def variables(self) -> tuple[str, ...]:
        return self.numeriques + self.categorielles

    @property
    def colonnes_lues(self) -> tuple[str, ...]:
        """Les colonnes du jeu dont l'usage a besoin (variables et cible ; `window_start` pour le calendrier)."""
        lues = self.variables + (self.cible,)
        return lues + (("window_start",) if self.calendrier else ())


def _interdites(**groupes: tuple[str, ...]) -> dict[str, str]:
    return {colonne: RAISONS[raison] for raison, colonnes in groupes.items() for colonne in colonnes}


DETECTION = Usage(
    nom="detection",
    numeriques=MESURES + HISTORIQUE + TRONCON_NUMERIQUE,
    categorielles=TRONCON_CATEGORIE,
    cible=CIBLE_DETECTION,
    interdites=_interdites(cle=CLES, calendrier=CALENDRIER, futur=CIBLES_PREVISION),
)


def prevision(horizon_min: int) -> Usage:
    """La prévision à 5 ou 15 minutes : le calendrier est permis (calculé depuis `window_start`), l'état voulu de la minute ne l'est pas.

    Sur le jeu v1 (un seul jour) le calendrier est constant et ne porte aucune information ; il sert les séries longues
    (METR-LA, IA-10). Les colonnes calendaires du fichier ne sont pas lues : la fonction `variables_calendaires` fait foi.
    """
    cible = f"speed_ratio_h{horizon_min}"
    if cible not in CIBLES_PREVISION:
        raise ValueError(f"horizon inconnu : {horizon_min} (jeu v1 : {HORIZONS})")
    autres = tuple(c for c in CIBLES_PREVISION if c != cible)
    return Usage(
        nom=f"prevision-h{horizon_min}",
        numeriques=MESURES + HISTORIQUE + TRONCON_NUMERIQUE + CALENDRIER_DERIVE,
        categorielles=TRONCON_CATEGORIE,
        cible=cible,
        interdites=_interdites(cle=CLES, futur=autres, verite=(CIBLE_DETECTION,)),
        calendrier=True,
    )


def verifier_usage(usage: Usage, colonnes_du_jeu: Collection[str] = NOMS) -> list[str]:
    """Les écarts d'un usage avec le cadrage : liste vide = conforme."""
    ecarts = []
    derivees = set(CALENDRIER_DERIVE) if usage.calendrier else set()
    for colonne in usage.variables:
        if colonne in usage.interdites:
            ecarts.append(f"{colonne} est interdite ({usage.interdites[colonne]})")
        elif colonne not in colonnes_du_jeu and colonne not in derivees:
            ecarts.append(f"{colonne} n'est pas une colonne du jeu")
    if usage.cible in usage.variables:
        ecarts.append(f"la cible {usage.cible} est aussi une variable")
    if usage.cible not in colonnes_du_jeu:
        ecarts.append(f"la cible {usage.cible} n'est pas une colonne du jeu")
    doubles = set(usage.numeriques) & set(usage.categorielles)
    if doubles:
        ecarts.append(f"colonnes à la fois numériques et catégorielles : {sorted(doubles)}")
    if len(set(usage.variables)) != len(usage.variables):
        ecarts.append("une variable est listée deux fois")
    return ecarts


def colonnes_non_classees(usage: Usage, colonnes_du_jeu: Collection[str] = NOMS) -> list[str]:
    """Les colonnes du jeu que l'usage ne classe ni comme variable, ni comme cible, ni comme interdite."""
    classees = set(usage.variables) | {usage.cible} | set(usage.interdites)
    return [colonne for colonne in colonnes_du_jeu if colonne not in classees]
