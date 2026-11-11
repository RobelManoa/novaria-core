"""De lignes du jeu à des matrices : médianes et catégories apprises sur l'entraînement seul.

`Preparation.ajuster` est le seul endroit où un chiffre est appris des données (médiane de remplacement des valeurs
absentes, liste des catégories). Il ne reçoit **que** des lignes d'entraînement : `runs_permis` fait échouer l'appel si
une ligne vient d'un autre run (validation ou test), pour qu'aucune statistique du futur ne passe dans une variable.
`transformer` n'apprend plus rien : la même ligne donne la même sortie, seule ou dans un lot.
"""

import math
import statistics
from collections.abc import Collection, Iterable

from preparation import calendrier
from preparation.variables import Usage

NAN = float("nan")


class FuiteDInformation(ValueError):
    """Un calcul d'ajustement a reçu des lignes qui n'appartiennent pas à l'entraînement."""


class Preparation:
    def __init__(self, usage: Usage) -> None:
        self.usage = usage
        self.medianes: dict[str, float] = {}
        self.categories: dict[str, list[str]] = {}
        self.runs_d_ajustement: list[str] = []
        self._ajustee = False

    def ajuster(self, lignes: Iterable[dict], *, runs_permis: Collection[str] | None = None) -> "Preparation":
        lignes = list(lignes)
        if not lignes:
            raise ValueError("ajustement sur zéro ligne")
        runs = sorted({ligne["run_id"] for ligne in lignes})
        if runs_permis is not None and (etrangers := sorted(set(runs) - set(runs_permis))):
            raise FuiteDInformation(f"l'ajustement ne se fait que sur l'entraînement ; runs étrangers : {etrangers}")
        for colonne in self.usage.numeriques:
            if colonne in calendrier.NOMS:
                continue  # calculée depuis l'instant, rien à apprendre
            presentes = [v for ligne in lignes if (v := ligne[colonne]) is not None]
            if not presentes:
                raise ValueError(f"{colonne} n'a aucune valeur dans l'ensemble d'ajustement")
            self.medianes[colonne] = float(statistics.median(float(v) for v in presentes))
        for colonne in self.usage.categorielles:
            self.categories[colonne] = sorted({ligne[colonne] for ligne in lignes})
        self.runs_d_ajustement = runs
        self._ajustee = True
        return self

    def noms(self) -> list[str]:
        """Les colonnes de la matrice, dans l'ordre : numériques, puis une colonne par catégorie (`road_type=LOCAL`)."""
        self._exiger_ajustement()
        numeriques = list(self.usage.numeriques)
        categories = [f"{c}={valeur}" for c in self.usage.categorielles for valeur in self.categories[c]]
        return numeriques + categories

    def transformer(self, lignes: Iterable[dict], *, imputer: bool) -> tuple[list[list[float]], list]:
        """Matrice et cible. `imputer` : une valeur absente prend la médiane de l'entraînement, sinon `nan`.

        Une ligne dont la cible est absente (prévision, fin de run) est écartée. Une catégorie jamais vue à
        l'entraînement est refusée : la coder « partout 0 » cacherait une donnée que le modèle n'a jamais connue.
        """
        self._exiger_ajustement()
        matrice, cible = [], []
        for ligne in lignes:
            if (y := ligne[self.usage.cible]) is None:
                continue
            valeurs = self._calendaires(ligne)
            rang = []
            for colonne in self.usage.numeriques:
                v = valeurs[colonne] if colonne in valeurs else ligne[colonne]
                if v is None:
                    v = self.medianes[colonne] if imputer else NAN
                rang.append(float(v))
            for colonne in self.usage.categorielles:
                if ligne[colonne] not in self.categories[colonne]:
                    raise ValueError(f"{colonne} = {ligne[colonne]!r} n'a pas été vue à l'entraînement")
                rang += [1.0 if ligne[colonne] == valeur else 0.0 for valeur in self.categories[colonne]]
            matrice.append(rang)
            cible.append(y)
        return matrice, cible

    def parametres(self) -> dict:
        """Ce qui a été appris, à consigner dans `model_runs.params` : de quoi refaire la même préparation."""
        self._exiger_ajustement()
        return {
            "usage": self.usage.nom,
            "medianes": dict(sorted(self.medianes.items())),
            "categories": {c: list(v) for c, v in sorted(self.categories.items())},
            "runs_d_ajustement": list(self.runs_d_ajustement),
        }

    def _calendaires(self, ligne: dict) -> dict:
        return calendrier.variables_calendaires(ligne["window_start"]) if self.usage.calendrier else {}

    def _exiger_ajustement(self) -> None:
        if not self._ajustee:
            raise RuntimeError("appeler ajuster (entraînement seul) avant d'utiliser la préparation")


def contient_nan(matrice: list[list[float]]) -> bool:
    return any(math.isnan(v) for rang in matrice for v in rang)
