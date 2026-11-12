"""Format `novaria-modele-lineaire` : un modèle linéaire en JSON, lisible sans exécuter de code (cadrage ML, M3 et S3).

Un fichier `pickle` exécute du code quand on le lit : on n'en charge jamais. Une régression logistique multiclasse n'a
besoin que de nombres : moyenne et écart de chaque variable, un vecteur de coefficients par état, une ordonnée par état,
et la préparation apprise sur l'entraînement (médianes, catégories). Ce module les écrit (avec scikit-learn, côté
entraînement) et les relit (bibliothèque standard seule, côté service) ; la lecture valide chaque champ et refuse
tout ce qui n'est pas exactement ce format.

Limite : seul ce format existe. `HistGradientBoostingClassifier` n'a pas de format sûr ici (skops et ONNX n'ont pas été
essayés) : un modèle de ce type ne peut pas être enregistré.
"""

import json
import math
from dataclasses import dataclass

from mesures.metriques import ETATS
from preparation.ajustement import Preparation
from preparation.variables import DETECTION, Usage

NOM = "novaria-modele-lineaire"
VERSION = 1
TAILLE_MAX = 1024 * 1024
CHAMPS = {"format", "version", "classes", "variables", "centrage", "coefficients", "intercepts", "preparation"}


class FormatInvalide(ValueError):
    """Le fichier n'est pas un modèle `novaria-modele-lineaire` conforme : on ne le charge pas."""


def _fini(valeur, chemin: str) -> float:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or not math.isfinite(valeur):
        raise FormatInvalide(f"{chemin} : nombre fini attendu")
    return float(valeur)


def _vecteur(valeur, longueur: int, chemin: str) -> list[float]:
    if not isinstance(valeur, list) or len(valeur) != longueur:
        raise FormatInvalide(f"{chemin} : liste de {longueur} nombres attendue")
    return [_fini(v, f"{chemin}[{i}]") for i, v in enumerate(valeur)]


def exporter(pipeline, preparation: Preparation) -> bytes:
    """Les octets du modèle (un `Pipeline` StandardScaler puis LogisticRegression de scikit-learn) et de sa préparation.

    Les nombres sont écrits avec `repr` (aller-retour exact) : deux exports du même modèle donnent les mêmes octets.
    """
    try:
        centrage, regression = pipeline.steps[0][1], pipeline.steps[1][1]
        classes = [str(c) for c in regression.classes_]
        coefficients = regression.coef_.tolist()
        intercepts = regression.intercept_.tolist()
        moyenne, echelle = centrage.mean_.tolist(), centrage.scale_.tolist()
    except (AttributeError, IndexError, TypeError) as erreur:
        raise FormatInvalide("seul un Pipeline (StandardScaler, LogisticRegression) ajusté s'exporte") from erreur
    document = {
        "format": NOM, "version": VERSION, "classes": classes, "variables": preparation.noms(),
        "centrage": {"moyenne": moyenne, "echelle": echelle},
        "coefficients": coefficients, "intercepts": intercepts, "preparation": preparation.parametres(),
    }
    octets = (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")
    ModeleLineaire.depuis_octets(octets)  # ce qu'on écrit doit se relire : sinon on n'écrit rien
    return octets


@dataclass(frozen=True)
class ModeleLineaire:
    classes: tuple[str, ...]
    variables: tuple[str, ...]
    moyenne: tuple[float, ...]
    echelle: tuple[float, ...]
    coefficients: tuple[tuple[float, ...], ...]
    intercepts: tuple[float, ...]
    preparation: Preparation

    @classmethod
    def depuis_octets(cls, octets: bytes, usage: Usage = DETECTION) -> "ModeleLineaire":
        if len(octets) > TAILLE_MAX:
            raise FormatInvalide("fichier trop gros")
        try:
            document = json.loads(octets.decode("utf-8"), parse_constant=_refuser_constante)
        except (UnicodeDecodeError, ValueError) as erreur:
            raise FormatInvalide(f"JSON illisible : {erreur}") from erreur
        if not isinstance(document, dict) or set(document) != CHAMPS:
            raise FormatInvalide(f"champs attendus : {sorted(CHAMPS)}")
        if document["format"] != NOM or document["version"] != VERSION:
            raise FormatInvalide(f"format {document['format']!r} version {document['version']!r} : {NOM} version {VERSION} attendus")
        classes = document["classes"]
        if not isinstance(classes, list) or len(classes) < 2 or not all(c in ETATS for c in classes) or len(set(classes)) != len(classes):
            raise FormatInvalide(f"classes : au moins deux états parmi {ETATS}, sans doublon")
        try:
            preparation = Preparation.depuis_parametres(usage, document["preparation"])
        except (ValueError, TypeError) as erreur:
            raise FormatInvalide(f"préparation : {erreur}") from erreur
        variables = preparation.noms()
        if document["variables"] != variables:
            raise FormatInvalide("variables : différentes de celles que la préparation produit")
        n = len(variables)
        centrage = document["centrage"]
        if not isinstance(centrage, dict) or set(centrage) != {"moyenne", "echelle"}:
            raise FormatInvalide("centrage : moyenne et echelle attendues")
        echelle = _vecteur(centrage["echelle"], n, "centrage.echelle")
        if any(e <= 0 for e in echelle):
            raise FormatInvalide("centrage.echelle : valeurs strictement positives attendues")
        coefficients = document["coefficients"]
        if not isinstance(coefficients, list) or len(coefficients) != len(classes):
            raise FormatInvalide("coefficients : un vecteur par état")
        return cls(
            tuple(classes), tuple(variables), tuple(_vecteur(centrage["moyenne"], n, "centrage.moyenne")), tuple(echelle),
            tuple(tuple(_vecteur(v, n, f"coefficients[{i}]")) for i, v in enumerate(coefficients)),
            tuple(_vecteur(document["intercepts"], len(classes), "intercepts")), preparation,
        )

    def predire(self, lignes: list[dict]) -> list[str]:
        """L'état de chaque ligne : l'état de plus grand score. Une ligne seule ou dans un lot donne la même réponse."""
        matrice, _ = self.preparation.transformer(({**ligne, self.preparation.usage.cible: ligne.get(self.preparation.usage.cible, "")}
                                                   for ligne in lignes), imputer=True)
        sorties = []
        for rang in matrice:
            centre = [(x - m) / e for x, m, e in zip(rang, self.moyenne, self.echelle, strict=True)]
            scores = [math.fsum(c * x for c, x in zip(coef, centre, strict=True)) + b for coef, b in zip(self.coefficients, self.intercepts, strict=True)]
            sorties.append(self.classes[max(range(len(scores)), key=lambda i: (scores[i], -i))])
        return sorties


def _refuser_constante(nom: str):
    raise ValueError(f"constante JSON refusée : {nom}")
