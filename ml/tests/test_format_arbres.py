"""Le format `novaria-modele-arbres` : une prévision identique à scikit-learn, sans pickle, et des refus nets (IA-16)."""

import importlib.util
import json
import unittest

from tests import support  # noqa: F401  (chemins d'import)
from registre import format_arbres as fa  # noqa: E402

SKLEARN = importlib.util.find_spec("sklearn") is not None


@unittest.skipUnless(SKLEARN, "scikit-learn absent (ml/.venv)")
class ParitéAvecScikitLearn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        from sklearn.ensemble import HistGradientBoostingRegressor

        rng = np.random.default_rng(7)
        cls.np = np
        cls.X = rng.normal(size=(3000, 6))
        cls.X[::13, 2] = np.nan  # des valeurs manquantes, apprises par le modèle
        cls.X[::29, 4] = np.nan
        y = 2 * cls.X[:, 0] + np.nan_to_num(cls.X[:, 2]) - 0.5 * np.nan_to_num(cls.X[:, 4]) ** 2 + rng.normal(size=3000)
        cls.modele = HistGradientBoostingRegressor(max_iter=40, max_leaf_nodes=15, early_stopping=False, random_state=1).fit(cls.X, y)
        cls.noms = tuple(f"v{i}" for i in range(6))
        cls.octets = fa.exporter(cls.modele, cls.noms, {"horizon_pas": 6})

    def test_la_prevision_relue_est_celle_de_scikit_learn(self):
        relu = fa.ModeleArbres.depuis_octets(self.octets)
        attendu = self.modele.predict(self.X)
        ecart = max(abs(relu.predire(list(map(float, ligne))) - a) for ligne, a in zip(self.X[:600], attendu[:600]))
        self.assertLess(ecart, 1e-9)

    def test_des_valeurs_jamais_vues_et_des_manques_donnent_aussi_la_meme_prevision(self):
        np = self.np
        rng = np.random.default_rng(99)
        nouveau = rng.normal(scale=4, size=(300, 6))
        nouveau[::3, 0] = np.nan
        nouveau[::5, 1] = np.nan
        relu = fa.ModeleArbres.depuis_octets(self.octets)
        attendu = self.modele.predict(nouveau)
        for ligne, a in zip(nouveau, attendu):
            self.assertAlmostEqual(relu.predire(list(map(float, ligne))), a, places=9)

    def test_deux_exports_du_meme_modele_donnent_les_memes_octets(self):
        self.assertEqual(fa.exporter(self.modele, self.noms, {"horizon_pas": 6}), self.octets)

    def test_le_fichier_est_du_json_pur(self):
        document = json.loads(self.octets)
        self.assertEqual(document["format"], fa.NOM)
        self.assertEqual(document["meta"], {"horizon_pas": 6})
        self.assertNotIn(b"pickle", self.octets)
        self.assertEqual(len(document["arbres"]), 40)

    def test_un_nombre_de_noms_different_du_modele_est_refuse(self):
        with self.assertRaises(fa.FormatInvalide):
            fa.exporter(self.modele, ("a", "b"))

    def test_ce_qui_n_est_pas_un_modele_d_arbres_ne_s_exporte_pas(self):
        with self.assertRaises(fa.FormatInvalide):
            fa.exporter(object(), self.noms)


def _arbre_minimal(**changements):
    arbre = {"variable": [0, 0, 0], "seuil": [0.5, 0.0, 0.0], "gauche": [1, 0, 0], "droite": [2, 0, 0],
             "valeur": [0.0, -1.0, 1.0], "manquant_a_gauche": [1, 0, 0], "feuille": [0, 1, 1]}
    arbre.update(changements)
    return arbre


def _document(**changements):
    document = {"format": fa.NOM, "version": fa.VERSION, "variables": ["x"], "base": 10.0, "arbres": [_arbre_minimal()], "meta": {}}
    document.update(changements)
    return json.dumps(document).encode("utf-8")


class Lecture(unittest.TestCase):
    def test_un_arbre_minimal_se_lit_et_se_parcourt(self):
        modele = fa.ModeleArbres.depuis_octets(_document())
        self.assertEqual(modele.predire([0.2]), 9.0)  # 10 + feuille de gauche
        self.assertEqual(modele.predire([0.9]), 11.0)
        self.assertEqual(modele.predire([float("nan")]), 9.0)  # le manque va à gauche, comme appris
        self.assertEqual(modele.predire([0.5]), 9.0)  # x <= seuil : gauche

    def test_le_manque_peut_aller_a_droite(self):
        modele = fa.ModeleArbres.depuis_octets(_document(arbres=[_arbre_minimal(manquant_a_gauche=[0, 0, 0])]))
        self.assertEqual(modele.predire([float("nan")]), 11.0)

    def test_plusieurs_arbres_s_additionnent(self):
        modele = fa.ModeleArbres.depuis_octets(_document(arbres=[_arbre_minimal(), _arbre_minimal()]))
        self.assertEqual(modele.predire([0.9]), 12.0)

    def test_refus(self):
        cas = {
            "pas du JSON": b"{pas du json",
            "pas du texte": b"\xff\xfe",
            "champ en trop": _document(extra=1),
            "mauvais format": _document(format="autre"),
            "mauvaise version": _document(version=2),
            "variables vides": _document(variables=[]),
            "noms en double": _document(variables=["x", "x"]),
            "aucun arbre": _document(arbres=[]),
            "base non finie": b'{"format":"novaria-modele-arbres","version":1,"variables":["x"],"base":NaN,"arbres":[],"meta":{}}',
            "champ d'arbre manquant": _document(arbres=[{k: v for k, v in _arbre_minimal().items() if k != "seuil"}]),
            "listes de longueurs différentes": _document(arbres=[_arbre_minimal(seuil=[0.5])]),
            "variable hors limites": _document(arbres=[_arbre_minimal(variable=[3, 0, 0])]),
            "enfant avant son parent (cycle)": _document(arbres=[_arbre_minimal(gauche=[0, 0, 0])]),
            "enfant hors de l'arbre": _document(arbres=[_arbre_minimal(droite=[9, 0, 0])]),
            "seuil non numérique": _document(arbres=[_arbre_minimal(seuil=["a", 0.0, 0.0])]),
            "entier attendu": _document(arbres=[_arbre_minimal(variable=[0.5, 0, 0])]),
        }
        for nom, octets in cas.items():
            with self.subTest(nom), self.assertRaises(fa.FormatInvalide):
                fa.ModeleArbres.depuis_octets(octets)

    def test_un_fichier_trop_gros_est_refuse_avant_d_etre_lu(self):
        with self.assertRaisesRegex(fa.FormatInvalide, "trop gros"):
            fa.ModeleArbres.depuis_octets(b" " * (fa.TAILLE_MAX + 1))


if __name__ == "__main__":
    unittest.main()
