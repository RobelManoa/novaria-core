"""Format `novaria-modele-arbres` : un modèle d'arbres boostés en JSON, lisible sans exécuter de code (IA-16).

Le format linéaire (`format_lineaire.py`) ne sait pas écrire un `HistGradientBoostingRegressor` : « un modèle de ce type ne peut pas
être enregistré ». Ce module comble le manque **sans `pickle`** : un modèle d'arbres n'est que des nombres (la prévision de base et,
pour chaque arbre, des tableaux de nœuds). On l'écrit avec scikit-learn (côté entraînement) et on le relit, avec une fonction de
prévision, en **bibliothèque standard seule** (côté service) : le service de traitement n'a besoin ni de numpy ni de scikit-learn.

La lecture valide chaque champ et refuse tout ce qui n'est pas exactement ce format : champ en trop ou manquant, nombre non fini,
indice hors limites, nœud dont un enfant ne vient pas **après** lui (donc aucun cycle : la descente d'un arbre se termine
toujours), taille démesurée.

Prévision : `base + somme des valeurs de feuille`. Dans chaque arbre, on va à gauche quand `x[variable] <= seuil`, à droite sinon ;
une valeur manquante (NaN) va du côté appris à l'entraînement. Limite : variables numériques seulement (pas de variable catégorielle).
"""

import json
import math
from dataclasses import dataclass

NOM = "novaria-modele-arbres"
VERSION = 1
TAILLE_MAX = 64 * 1024 * 1024
ARBRES_MAX = 5_000
NOEUDS_MAX = 200_000
CHAMPS = {"format", "version", "variables", "base", "arbres", "meta"}
CHAMPS_ARBRE = {"variable", "seuil", "gauche", "droite", "valeur", "manquant_a_gauche", "feuille"}


class FormatInvalide(ValueError):
    """Le fichier n'est pas un modèle `novaria-modele-arbres` conforme : on ne le charge pas."""


def _fini(valeur, chemin: str) -> float:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or not math.isfinite(valeur):
        raise FormatInvalide(f"{chemin} : nombre fini attendu")
    return float(valeur)


def _entier(valeur, chemin: str) -> int:
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise FormatInvalide(f"{chemin} : entier attendu")
    return valeur


def exporter(modele, variables: tuple[str, ...], meta: dict | None = None) -> bytes:
    """Les octets d'un `HistGradientBoostingRegressor` ajusté. Deux exports du même modèle donnent les mêmes octets."""
    try:
        predicteurs = modele._predictors  # noqa: SLF001 : scikit-learn ne publie pas d'accès aux arbres
        base = float(modele._baseline_prediction.ravel()[0])  # noqa: SLF001
        attendu = int(modele.n_features_in_)
    except (AttributeError, IndexError, TypeError, ValueError) as erreur:
        raise FormatInvalide("seul un HistGradientBoostingRegressor ajusté s'exporte") from erreur
    if attendu != len(variables):
        raise FormatInvalide(f"{len(variables)} noms de variables pour {attendu} variables apprises")
    arbres = []
    for iteration in predicteurs:
        if len(iteration) != 1:
            raise FormatInvalide("un seul arbre par itération attendu (régression)")
        noeuds = iteration[0].nodes
        if bool(noeuds["is_categorical"].any()):
            raise FormatInvalide("les variables catégorielles ne sont pas prises en charge")
        arbres.append({
            "variable": noeuds["feature_idx"].astype(int).tolist(),
            "seuil": noeuds["num_threshold"].astype(float).tolist(),
            "gauche": noeuds["left"].astype(int).tolist(),
            "droite": noeuds["right"].astype(int).tolist(),
            "valeur": noeuds["value"].astype(float).tolist(),
            "manquant_a_gauche": noeuds["missing_go_to_left"].astype(int).tolist(),
            "feuille": noeuds["is_leaf"].astype(int).tolist(),
        })
    document = {"format": NOM, "version": VERSION, "variables": list(variables), "base": base, "arbres": arbres, "meta": meta or {}}
    octets = (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    ModeleArbres.depuis_octets(octets)  # ce qu'on écrit doit se relire : sinon on n'écrit rien
    return octets


@dataclass(frozen=True)
class Arbre:
    variable: tuple[int, ...]
    seuil: tuple[float, ...]
    gauche: tuple[int, ...]
    droite: tuple[int, ...]
    valeur: tuple[float, ...]
    manquant_a_gauche: tuple[bool, ...]
    feuille: tuple[bool, ...]

    def predire(self, ligne) -> float:
        """Descend l'arbre ; `ligne` est indexable par rang de variable, NaN pour une valeur manquante."""
        n = 0
        while not self.feuille[n]:
            x = ligne[self.variable[n]]
            gauche = self.manquant_a_gauche[n] if x != x else x <= self.seuil[n]  # x != x : NaN
            n = self.gauche[n] if gauche else self.droite[n]
        return self.valeur[n]


@dataclass(frozen=True)
class ModeleArbres:
    variables: tuple[str, ...]
    base: float
    arbres: tuple[Arbre, ...]
    meta: dict

    def predire(self, ligne) -> float:
        total = self.base
        for arbre in self.arbres:
            total += arbre.predire(ligne)
        return total

    @classmethod
    def depuis_octets(cls, octets: bytes) -> "ModeleArbres":
        if len(octets) > TAILLE_MAX:
            raise FormatInvalide("fichier trop gros")
        try:
            document = json.loads(octets.decode("utf-8"), parse_constant=_refuser_constante)
        except (UnicodeDecodeError, json.JSONDecodeError) as erreur:
            raise FormatInvalide(f"JSON illisible : {erreur}") from erreur
        if not isinstance(document, dict) or set(document) != CHAMPS:
            raise FormatInvalide(f"champs attendus exactement : {sorted(CHAMPS)}")
        if document["format"] != NOM or document["version"] != VERSION:
            raise FormatInvalide(f"format {NOM!r} version {VERSION} attendu")
        variables = document["variables"]
        if not isinstance(variables, list) or not variables or not all(isinstance(v, str) and v for v in variables):
            raise FormatInvalide("variables : liste de noms non vides attendue")
        if len(set(variables)) != len(variables):
            raise FormatInvalide("variables : noms en double")
        if not isinstance(document["meta"], dict):
            raise FormatInvalide("meta : objet attendu")
        brut = document["arbres"]
        if not isinstance(brut, list) or not 0 < len(brut) <= ARBRES_MAX:
            raise FormatInvalide(f"arbres : de 1 à {ARBRES_MAX} arbres attendus")
        arbres = tuple(_arbre(a, len(variables), f"arbres[{i}]") for i, a in enumerate(brut))
        return cls(tuple(variables), _fini(document["base"], "base"), arbres, document["meta"])


def _refuser_constante(nom: str):
    raise FormatInvalide(f"constante JSON refusée : {nom}")


def _arbre(brut, nb_variables: int, chemin: str) -> Arbre:
    if not isinstance(brut, dict) or set(brut) != CHAMPS_ARBRE:
        raise FormatInvalide(f"{chemin} : champs attendus exactement : {sorted(CHAMPS_ARBRE)}")
    longueur = len(brut["feuille"]) if isinstance(brut["feuille"], list) else -1
    if not 0 < longueur <= NOEUDS_MAX:
        raise FormatInvalide(f"{chemin} : de 1 à {NOEUDS_MAX} nœuds attendus")
    for champ in CHAMPS_ARBRE:
        if not isinstance(brut[champ], list) or len(brut[champ]) != longueur:
            raise FormatInvalide(f"{chemin}.{champ} : liste de {longueur} éléments attendue")
    variable = tuple(_entier(v, f"{chemin}.variable[{n}]") for n, v in enumerate(brut["variable"]))
    gauche = tuple(_entier(v, f"{chemin}.gauche[{n}]") for n, v in enumerate(brut["gauche"]))
    droite = tuple(_entier(v, f"{chemin}.droite[{n}]") for n, v in enumerate(brut["droite"]))
    feuille = tuple(bool(_entier(v, f"{chemin}.feuille[{n}]")) for n, v in enumerate(brut["feuille"]))
    manquant = tuple(bool(_entier(v, f"{chemin}.manquant_a_gauche[{n}]")) for n, v in enumerate(brut["manquant_a_gauche"]))
    for n in range(longueur):
        if not feuille[n]:
            if not 0 <= variable[n] < nb_variables:
                raise FormatInvalide(f"{chemin}.variable[{n}] : rang hors limites")
            for enfant, nom in ((gauche[n], "gauche"), (droite[n], "droite")):
                if not n < enfant < longueur:
                    raise FormatInvalide(f"{chemin}.{nom}[{n}] : l'enfant doit venir après son parent et rester dans l'arbre")
    seuil = tuple(_fini(v, f"{chemin}.seuil[{n}]") for n, v in enumerate(brut["seuil"]))
    valeur = tuple(_fini(v, f"{chemin}.valeur[{n}]") for n, v in enumerate(brut["valeur"]))
    return Arbre(variable, seuil, gauche, droite, valeur, manquant, feuille)
