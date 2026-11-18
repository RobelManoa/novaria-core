"""Isolation Forest sur les mêmes variables que les règles (scikit-learn, importé ici seulement).

Isolation Forest ne reçoit aucune étiquette : il est ajusté sur du trafic **non étiqueté** qui contient quelques
anomalies, comme un flux réel. Son seuil de score est fixé sur la validation avec le même budget de fausses alertes
que les règles (`evaluation.budget`). Réglages fixés d'avance : 200 arbres, 256 mesures par arbre, graine 42.

Limite de principe : le modèle ne juge que les messages qui arrivent. Un capteur muet n'en envoie plus, donc rien
n'est noté pendant le silence ; il n'est vu qu'à la reprise, par la variable `silence_s`.
"""

from anomalies import SEED
from anomalies.campagne import Banc
from anomalies.regles import Alerte
from anomalies.variables import NOMS, Suivi

ARBRES = 200
ECHANTILLON = 256


class SklearnAbsent(ImportError):
    pass


def variables_du_banc(banc: Banc) -> tuple[list[tuple], list]:
    """Le vecteur de variables de chaque message livré, dans l'ordre de livraison, et les messages."""
    suivi = Suivi()
    mesures = sorted(banc.mesures, key=lambda m: (m.livre, m.capteur))
    return [suivi.observer(m) for m in mesures], mesures


def entrainer(bancs: list[Banc]):
    try:
        from sklearn.ensemble import IsolationForest
    except ImportError as erreur:
        raise SklearnAbsent("scikit-learn est absent : python3 scripts/dev/dev.py ml-env (Windows : py -3 scripts/dev/dev.py ml-env)") from erreur
    lignes = [x for banc in bancs for x in variables_du_banc(banc)[0]]
    modele = IsolationForest(n_estimators=ARBRES, max_samples=ECHANTILLON, contamination="auto", random_state=SEED, n_jobs=1)
    return modele.fit(lignes), len(lignes)


def scores(modele, banc: Banc) -> tuple[list[float], list]:
    """Score de chaque message (plus il est bas, plus le message est isolé) et les messages."""
    lignes, mesures = variables_du_banc(banc)
    return list(modele.score_samples(lignes)), mesures


def alertes_du_modele(modele, banc: Banc, seuil: float, notes_et_mesures: tuple | None = None) -> list[Alerte]:
    notes, mesures = notes_et_mesures or scores(modele, banc)
    return [Alerte("isolation_forest", m.capteur, m.livre, f"score {note:.3f}") for note, m in zip(notes, mesures, strict=True) if note < seuil]


VARIABLES = NOMS


def auc_par_type(notes_par_banc: list[tuple]) -> dict[str, float | None]:
    """Aire sous la courbe ROC des scores, par type d'anomalie : indépendante du seuil. Les messages touchés par un type
    (positifs) contre tous les messages hors injection (négatifs) ; `None` quand aucun message n'est touché (capteur muet)."""
    from sklearn.metrics import roc_auc_score

    negatifs: list[float] = []
    positifs: dict[str, list[float]] = {}
    for banc, (notes, mesures) in notes_par_banc:
        for note, m in zip(notes, mesures, strict=True):
            types = [i.type for i in banc.injections if i.capteur == m.capteur and i.debut <= m.instant <= i.fin]
            if types:
                positifs.setdefault(types[0], []).append(-note)
            else:
                negatifs.append(-note)
    return {t: (roc_auc_score([1] * len(p) + [0] * len(negatifs), p + negatifs) if p else None) for t, p in positifs.items()}

