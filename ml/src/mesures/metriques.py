"""Les quatre mesures du cadrage ML (`docs/06-ia-mlops/cadrage-ml.md`, section 4) : fonctions pures, sans dépendance.

Une **série** est la suite des minutes d'un tronçon dans un run : deux listes de même longueur, l'état voulu par le
scénario (vérité terrain) et l'état annoncé par la règle ou par le modèle. Une alerte naît à l'entrée dans `CONGESTED`
(ADR-028) ; elle est jugée contre les épisodes de congestion de la vérité terrain.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from statistics import median

ETATS = ("FREE_FLOW", "SLOW", "CONGESTED")
MINUTES_PAR_JOUR = 1440
TOLERANCE_MIN = 10  # une alerte jusqu'à 10 minutes avant le début réel reste rattachée à l'épisode


def f1_par_classe(vrais: Sequence[str], predits: Sequence[str]) -> dict[str, tuple[float, float, float]]:
    """Précision, rappel et F1 de chaque état ; 0 quand le dénominateur est nul."""
    if len(vrais) != len(predits):
        raise ValueError("vrais et predits n'ont pas la même longueur")
    comptes = Counter(zip(vrais, predits, strict=True))
    resultat = {}
    for etat in ETATS:
        vrais_positifs = comptes[(etat, etat)]
        annonces = sum(n for (_, p), n in comptes.items() if p == etat)
        reels = sum(n for (v, _), n in comptes.items() if v == etat)
        precision = vrais_positifs / annonces if annonces else 0.0
        rappel = vrais_positifs / reels if reels else 0.0
        f1 = 2 * precision * rappel / (precision + rappel) if precision + rappel else 0.0
        resultat[etat] = (precision, rappel, f1)
    return resultat


def f1_macro(vrais: Sequence[str], predits: Sequence[str]) -> float:
    """Moyenne des F1 des trois états, sans pondération : un état rare pèse autant qu'un état fréquent."""
    return sum(f1 for _, _, f1 in f1_par_classe(vrais, predits).values()) / len(ETATS)


def rappel_congested(vrais: Sequence[str], predits: Sequence[str]) -> float:
    return f1_par_classe(vrais, predits)["CONGESTED"][1]


def episodes(etats: Sequence[str], etat: str = "CONGESTED") -> list[tuple[int, int]]:
    """Les plages de minutes consécutives dans `etat` : (premier indice, indice après le dernier)."""
    plages, debut = [], None
    for i, courant in enumerate(etats):
        if courant == etat and debut is None:
            debut = i
        elif courant != etat and debut is not None:
            plages.append((debut, i))
            debut = None
    if debut is not None:
        plages.append((debut, len(etats)))
    return plages


def entrees(etats: Sequence[str], etat: str = "CONGESTED") -> list[int]:
    """Les minutes où l'état annoncé devient `etat` (la première minute de la série compte)."""
    return [i for i, courant in enumerate(etats) if courant == etat and (i == 0 or etats[i - 1] != etat)]


@dataclass
class Alertes:
    """Appariement des alertes aux épisodes réels, sur une ou plusieurs séries."""

    delais: list[int] = field(default_factory=list)  # minutes entre le début réel et l'alerte, 0 si en avance
    episodes: int = 0
    manques: int = 0  # épisodes réels sans aucune alerte
    alertes: int = 0
    fausses: int = 0  # alertes sans épisode à réclamer : hors épisode, ou répétées dans un même épisode
    minutes: int = 0

    def ajouter(self, autre: "Alertes") -> None:
        self.delais += autre.delais
        self.episodes += autre.episodes
        self.manques += autre.manques
        self.alertes += autre.alertes
        self.fausses += autre.fausses
        self.minutes += autre.minutes

    @property
    def delai_median(self) -> float | None:
        return median(self.delais) if self.delais else None

    @property
    def delai_max(self) -> int | None:
        return max(self.delais) if self.delais else None

    @property
    def fausses_par_troncon_et_jour(self) -> float:
        return self.fausses / (self.minutes / MINUTES_PAR_JOUR) if self.minutes else 0.0


def apparier(vrais: Sequence[str], predits: Sequence[str], tolerance: int = TOLERANCE_MIN) -> Alertes:
    """Chaque épisode réel est réclamé par la première alerte arrivée entre `début − tolérance` et sa fin.

    Le délai est l'écart entre le début réel et cette alerte (0 si elle précède). Toute autre alerte est fausse : elle
    tombe hors d'un épisode, ou répète une alerte déjà comptée dans le même épisode (un état qui clignote).
    """
    if len(vrais) != len(predits):
        raise ValueError("vrais et predits n'ont pas la même longueur")
    reclamees: set[int] = set()
    resultat = Alertes(minutes=len(vrais))
    alertes = entrees(predits)
    for debut, fin in episodes(vrais):
        resultat.episodes += 1
        premiere = next((k for k in alertes if debut - tolerance <= k < fin and k not in reclamees), None)
        if premiere is None:
            resultat.manques += 1
        else:
            reclamees.add(premiere)
            resultat.delais.append(max(0, premiere - debut))
    resultat.alertes = len(alertes)
    resultat.fausses = len(alertes) - len(reclamees)
    return resultat


@dataclass(frozen=True)
class Mesures:
    f1_macro: float
    rappel_congested: float
    precision_congested: float
    par_classe: dict[str, tuple[float, float, float]]
    alertes: Alertes

    def en_dict(self) -> dict:
        a = self.alertes
        return {
            "f1_macro": round(self.f1_macro, 4),
            "rappel_congested": round(self.rappel_congested, 4),
            "precision_congested": round(self.precision_congested, 4),
            "par_classe": {e: [round(x, 4) for x in v] for e, v in self.par_classe.items()},
            "episodes": a.episodes,
            "episodes_manques": a.manques,
            "delai_median_min": a.delai_median,
            "delai_max_min": a.delai_max,
            "alertes": a.alertes,
            "fausses_alertes": a.fausses,
            "fausses_alertes_par_troncon_et_jour": round(a.fausses_par_troncon_et_jour, 4),
            "troncons_jours": round(a.minutes / MINUTES_PAR_JOUR, 2),
        }


def mesurer(series: Iterable[tuple[Sequence[str], Sequence[str]]]) -> Mesures:
    """F1 et rappel sur **toutes les minutes réunies** ; alertes série par série.

    Les mesures se calculent sur l'ensemble réuni et non run par run : un run de journée calme ne contient qu'un état,
    son F1 macro vaut 1/3 quoi qu'on prédise.
    """
    tous_vrais: list[str] = []
    tous_predits: list[str] = []
    alertes = Alertes()
    for vrais, predits in series:
        tous_vrais += vrais
        tous_predits += predits
        alertes.ajouter(apparier(vrais, predits))
    par_classe = f1_par_classe(tous_vrais, tous_predits)
    return Mesures(
        f1_macro=sum(f1 for _, _, f1 in par_classe.values()) / len(ETATS),
        rappel_congested=par_classe["CONGESTED"][1],
        precision_congested=par_classe["CONGESTED"][0],
        par_classe=par_classe,
        alertes=alertes,
    )
