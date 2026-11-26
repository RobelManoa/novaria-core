"""Le lecteur du réseau de vitesse (copie de celui d'IA-16) refuse ce qui n'est pas son format.

Un petit réseau écrit à la main (2 capteurs, 3 neurones, poids constants) : on ne juge pas la
qualité de la prévision, seulement ce que le lecteur promet. La parité avec PyTorch est vérifiée
côté entraînement (`ml/tests/test_reseau.py`).
"""

import json

import numpy as np
import pytest

from app.forecast import reseau as lecteur
from app.forecast.reseau import FormatInvalide, ModeleReseau

CACHE = 3


def document(valeur: float = 0.0) -> dict:
    def plat(forme):
        if len(forme) == 1:
            return [valeur] * forme[0]
        return [plat(forme[1:]) for _ in range(forme[0])]

    return {
        "format": "novaria-modele-reseau",
        "version": 1,
        "capteurs": ["A", "B"],
        "moyenne": 55.0,
        "ecart": 10.0,
        "echelle_sortie": 10.0,
        "adjacence": [[0.5, 0.5], [0.5, 0.5]],
        "habituel": [[0.0, 0.0] for _ in range(lecteur.PAS_PAR_SEMAINE)],
        "poids": {nom: plat(forme) for nom, forme in lecteur.formes_attendues(CACHE).items()},
        "meta": {"jeu": "essai"},
    }


def lire(doc: dict | None = None, octets: bytes | None = None) -> ModeleReseau:
    return ModeleReseau.depuis_octets(octets if octets is not None else json.dumps(doc).encode())


def avec_poids(**changements) -> dict:
    doc = document()
    doc["poids"].update(changements)
    return doc


REFUS = {
    "pas du JSON": {"octets": b"{pas du json"},
    "pas de l'UTF-8": {"octets": b"\xff\xfe"},
    "pas un objet": {"octets": b"[1, 2]"},
    "champ en trop": {"doc": {**document(), "extra": 1}},
    "mauvais format": {"doc": {**document(), "format": "autre"}},
    "capteurs vides": {"doc": {**document(), "capteurs": []}},
    "capteurs pas en liste": {"doc": {**document(), "capteurs": "AB"}},
    "nom vide": {"doc": {**document(), "capteurs": ["A", ""]}},
    "capteurs en double": {"doc": {**document(), "capteurs": ["A", "A"]}},
    "écart nul": {"doc": {**document(), "ecart": 0}},
    "moyenne booléenne": {"doc": {**document(), "moyenne": True}},
    "meta pas un objet": {"doc": {**document(), "meta": []}},
    "poids pas un objet": {"doc": {**document(), "poids": []}},
    "entrée pas une liste": {"doc": avec_poids(**{"entree.weight": 3})},
    "entrée vide": {"doc": avec_poids(**{"entree.weight": []})},
    "poids en trop": {"doc": avec_poids(inconnu=[1.0])},
    "poids de mauvaise forme": {"doc": avec_poids(**{"tete.2.bias": [0.0]})},
    "poids pas des nombres": {"doc": avec_poids(**{"entree.bias": ["a", "b", "c"]})},
    "adjacence de mauvaise forme": {"doc": {**document(), "adjacence": [[1.0]]}},
    "adjacence négative": {"doc": {**document(), "adjacence": [[1.0, -0.5], [0.5, 0.5]]}},
    "constante NaN": {
        "octets": json.dumps(document()).encode().replace(b'"ecart": 10.0', b'"ecart": NaN')
    },
}


@pytest.mark.parametrize("cas", REFUS.values(), ids=REFUS.keys())
def test_the_reader_refuses_everything_that_is_not_the_format(cas):
    with pytest.raises(FormatInvalide):
        lire(cas.get("doc"), cas.get("octets"))


def test_a_value_that_overflows_to_infinity_is_refused():
    doc = avec_poids(**{"entree.bias": [123456.0, 0.0, 0.0]})
    octets = json.dumps(doc).encode().replace(b"123456.0", b"1e999")
    with pytest.raises(FormatInvalide, match="finis"):
        lire(octets=octets)


def test_a_file_that_is_too_big_is_refused(monkeypatch):
    monkeypatch.setattr(lecteur, "TAILLE_MAX", 10)
    with pytest.raises(FormatInvalide, match="trop gros"):
        lire(octets=b" " * 11)


def test_zero_weights_give_persistence_and_real_weights_move_the_forecast():
    instants = 4 * 86_400_000 + np.arange(12, dtype=np.int64) * 300_000
    vitesses, presentes = np.tile([[50.0, 62.0]], (12, 1)), np.ones((12, 2))
    persistance = lire(document(0.0)).predire(vitesses, presentes, instants)
    assert persistance.shape == (2, 6)
    assert np.allclose(persistance[0], 50.0) and np.allclose(persistance[1], 62.0)
    modele = lire(document(0.3))
    prevu = modele.predire(vitesses, presentes, instants)
    assert np.isfinite(prevu).all() and not np.allclose(prevu[0], 50.0)
    assert np.array_equal(prevu, modele.predire(vitesses, presentes, instants))
    assert np.abs(modele.predire(vitesses - 20, presentes, instants) - prevu).max() > 0.1


def test_a_badly_shaped_window_is_refused():
    modele = lire(document())
    instants = 4 * 86_400_000 + np.arange(12, dtype=np.int64) * 300_000
    with pytest.raises(ValueError, match="forme"):
        modele.predire(np.ones((5, 2)), np.ones((5, 2)), instants[:5])
    with pytest.raises(ValueError, match="instants"):
        modele.predire(np.ones((12, 2)), np.ones((12, 2)), instants[:5])
    with pytest.raises(ValueError, match="manquante"):
        modele.predire(np.full((12, 2), np.nan), np.ones((12, 2)), instants)
