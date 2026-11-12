"""Les deux candidats du cadrage ML (section 7) et leurs grilles de réglages (12 combinaisons au plus chacun).

scikit-learn est importé à l'intérieur des fonctions : ce module se charge sans lui (les tests qui en ont besoin sont
ignorés sur un poste qui ne l'a pas : `python3 scripts/dev/dev.py ml-env`).
"""

import itertools
import warnings
from collections.abc import Callable
from dataclasses import dataclass

from entrainement import SEED

MAX_COMBINAISONS = 12


class SklearnAbsent(ImportError):
    pass


def _sklearn():
    try:
        import sklearn
    except ImportError as erreur:
        raise SklearnAbsent("scikit-learn est absent : python3 scripts/dev/dev.py ml-env (Windows : py -3 scripts/dev/dev.py ml-env)") from erreur
    return sklearn


def _regression_logistique(params: dict):
    _sklearn()
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(
        StandardScaler(),
        LogisticRegression(C=params["C"], class_weight=params["class_weight"], max_iter=2000, random_state=SEED),
        memory=None,  # aucun cache disque : un entraînement ne laisse rien derrière lui
    )


def _gradient_boosting(params: dict):
    _sklearn()
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(
        learning_rate=params["learning_rate"], max_leaf_nodes=params["max_leaf_nodes"], class_weight=params["class_weight"],
        max_iter=200, early_stopping=False, random_state=SEED,
    )


def _grille(**valeurs) -> tuple[dict, ...]:
    noms = list(valeurs)
    return tuple(dict(zip(noms, combinaison, strict=True)) for combinaison in itertools.product(*valeurs.values()))


@dataclass(frozen=True)
class Candidat:
    nom: str
    libelle: str
    imputer: bool  # la régression logistique ne supporte pas les valeurs absentes ; le gradient boosting oui
    grille: tuple[dict, ...]
    fabrique: Callable[[dict], object]

    def construire(self, params: dict):
        return self.fabrique(params)


LOGISTIQUE = Candidat(
    "logistique", "Régression logistique multiclasse (variables centrées et réduites)", True,
    _grille(C=(0.01, 0.1, 1.0, 10.0), class_weight=(None, "balanced")), _regression_logistique,
)
GRADIENT = Candidat(
    "gradient", "HistGradientBoostingClassifier", False,
    _grille(learning_rate=(0.05, 0.1), max_leaf_nodes=(15, 31), class_weight=(None, "balanced")), _gradient_boosting,
)
CANDIDATS = (LOGISTIQUE, GRADIENT)  # l'ordre est celui de la simplicité : à égalité, le premier gagne


def candidat(nom: str) -> Candidat:
    return next(c for c in CANDIDATS if c.nom == nom)


def ajuster(c: Candidat, params: dict, matrice: list[list[float]], cible: list[str]) -> tuple[object, list[str]]:
    """Entraîne un modèle ; rend aussi les avertissements (une non-convergence ne doit pas passer inaperçue)."""
    with warnings.catch_warnings(record=True) as vus:
        warnings.simplefilter("always")
        modele = c.construire(params).fit(matrice, cible)
    return modele, sorted({f"{v.category.__name__}: {v.message}" for v in vus})
