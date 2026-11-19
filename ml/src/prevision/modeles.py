"""Ridge et HistGradientBoosting (scikit-learn), appris sur l'écart à la persistance, et leurs réglages.

Un modèle par horizon. La réponse apprise est `vitesse(t + h) − vitesse(t)` : la prévision est la persistance plus une
correction, ce qui donne au modèle la référence la plus dure pour point de départ. Les réglages se choisissent sur la
**validation** seulement (grilles courtes, fixées d'avance) ; le test n'est lu qu'ensuite. Aucun modèle n'est écrit sur le
disque (ni `pickle`, ni fichier) : tout se fait en mémoire.
"""

from prevision import SEED

GRILLE_RIDGE = tuple({"alpha": a} for a in (0.1, 1.0, 10.0, 100.0))
GRILLE_HGB = (
    {"max_leaf_nodes": 31, "max_iter": 200, "learning_rate": 0.1},
    {"max_leaf_nodes": 63, "max_iter": 200, "learning_rate": 0.1},
    {"max_leaf_nodes": 63, "max_iter": 400, "learning_rate": 0.05},
)


class SklearnAbsent(ImportError):
    pass


def _sklearn():
    try:
        import sklearn
    except ImportError as erreur:
        raise SklearnAbsent("scikit-learn est absent : python3 scripts/dev/dev.py ml-env (Windows : py -3 scripts/dev/dev.py ml-env)") from erreur
    return sklearn


def ridge(params: dict):
    _sklearn()
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(StandardScaler(), Ridge(alpha=params["alpha"]), memory=None)


def hgb(params: dict):
    _sklearn()
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(loss="squared_error", early_stopping=False, random_state=SEED, **params)


FABRIQUES = {"ridge": (ridge, GRILLE_RIDGE), "hist_gradient_boosting": (hgb, GRILLE_HGB)}
