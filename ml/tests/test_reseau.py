"""Le réseau spatio-temporel d'IA-16 : le passage avant numpy (service) est celui de PyTorch (entraînement), et le format refuse ce qui est faux."""

import importlib.util
import json
import unittest

from tests import support  # noqa: F401  (chemins d'import)

TORCH = importlib.util.find_spec("torch") is not None
NUMPY = importlib.util.find_spec("numpy") is not None


def _petit_reseau():
    import numpy as np
    import torch

    from prevision import voisins
    from prevision.reseau import Donnees, Reseau, adjacence, preparer

    torch.manual_seed(3)
    rng = np.random.default_rng(3)
    pas, capteurs = 3 * 7 * 288, 6
    instants = (4 * 86_400_000 + np.arange(pas, dtype=np.int64) * 300_000)
    jour = np.sin(2 * np.pi * (np.arange(pas) % 288) / 288)
    brut = 55 + 8 * jour[:, None] + rng.normal(scale=2, size=(pas, capteurs)).cumsum(axis=0) * 0.01 + rng.normal(scale=1.5, size=(pas, capteurs))
    brut[rng.random(brut.shape) < 0.03] = np.nan
    from prevision import variables

    rempli = variables.remplir(brut, 55.0)
    apprentissage = np.arange(variables.DEBUT_MIN, 2 * 7 * 288)
    donnees = preparer(brut, rempli, instants, apprentissage, k=2)
    modele = Reseau(adjacence(donnees.profil), cache=8)
    for p in modele.parameters():  # des poids non nuls et variés : un passage avant qui compte
        torch.nn.init.normal_(p, std=0.4)
    return np, torch, modele, donnees, brut, rempli, instants, tuple(f"S{i}" for i in range(capteurs))


@unittest.skipUnless(TORCH and NUMPY, "PyTorch absent (ml/.venv)")
class Parite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from registre import format_reseau

        cls.np, cls.torch, cls.modele, cls.donnees, cls.brut, cls.rempli, cls.instants, cls.capteurs = _petit_reseau()
        cls.octets = format_reseau.exporter(cls.modele, cls.donnees, {"jeu": "essai"}, cls.capteurs)
        cls.relu = format_reseau.ModeleReseau.depuis_octets(cls.octets)

    def test_le_passage_avant_numpy_est_celui_de_pytorch(self):
        from prevision.reseau import predire

        np = self.np
        t = np.array([30, 500, 900, 1500, 1700])
        attendu = predire(self.modele, self.donnees, t)  # (5, 6 capteurs, 6 horizons)
        for i, ti in enumerate(t):
            fenetre = slice(ti - 11, ti + 1)
            obtenu = self.relu.predire(self.rempli[fenetre], (~np.isnan(self.brut[fenetre])).astype(float), self.instants[fenetre])
            self.assertLess(float(np.abs(obtenu - attendu[i]).max()), 2e-3, f"t = {ti}")  # arrondis du format : moins de 0,002 mph

    def test_la_prevision_depend_bien_de_l_entree(self):
        np = self.np
        t = 700
        fenetre = slice(t - 11, t + 1)
        base = self.relu.predire(self.rempli[fenetre], np.ones((12, 6)), self.instants[fenetre])
        autre = self.relu.predire(self.rempli[fenetre] + 10.0, np.ones((12, 6)), self.instants[fenetre])
        self.assertGreater(float(np.abs(autre - base).max()), 1.0)
        self.assertEqual(base.shape, (6, 6))

    def test_deux_exports_donnent_les_memes_octets(self):
        from registre import format_reseau

        self.assertEqual(format_reseau.exporter(self.modele, self.donnees, {"jeu": "essai"}, self.capteurs), self.octets)

    def test_le_fichier_est_du_json_pur_et_sans_pickle(self):
        document = json.loads(self.octets)
        self.assertEqual(document["format"], "novaria-modele-reseau")
        self.assertEqual(document["capteurs"], list(self.capteurs))
        self.assertNotIn(b"pickle", self.octets)

    def test_une_fenetre_mal_formee_est_refusee(self):
        np = self.np
        with self.assertRaises(ValueError):
            self.relu.predire(np.ones((5, 6)), np.ones((5, 6)), np.zeros(5, dtype=np.int64))
        with self.assertRaises(ValueError):
            fenetre = np.full((12, 6), np.nan)
            self.relu.predire(fenetre, np.ones((12, 6)), self.instants[:12])


@unittest.skipUnless(TORCH and NUMPY, "PyTorch absent (ml/.venv)")
class Refus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from registre import format_reseau

        cls.format = format_reseau
        _, _, modele, donnees, _, _, _, capteurs = _petit_reseau()
        cls.document = json.loads(format_reseau.exporter(modele, donnees, {}, capteurs))

    def _lire(self, **changements):
        document = dict(self.document)
        document.update(changements)
        return self.format.ModeleReseau.depuis_octets(json.dumps(document).encode("utf-8"))

    def test_refus(self):
        poids = dict(self.document["poids"])
        cas = {
            "pas du JSON": lambda: self.format.ModeleReseau.depuis_octets(b"{pas du json"),
            "champ en trop": lambda: self._lire(extra=1),
            "mauvais format": lambda: self._lire(format="autre"),
            "capteurs en double": lambda: self._lire(capteurs=["a"] * 6),
            "ecart nul": lambda: self._lire(ecart=0),
            "adjacence de mauvaise forme": lambda: self._lire(adjacence=[[1.0]]),
            "habituel de mauvaise forme": lambda: self._lire(habituel=[[1.0] * 6]),
            "poids manquant": lambda: self._lire(poids={k: v for k, v in poids.items() if k != "tete.2.bias"}),
            "poids en trop": lambda: self._lire(poids={**poids, "inconnu": [1.0]}),
            "poids de mauvaise forme": lambda: self._lire(poids={**poids, "tete.2.bias": [0.0]}),
            "nombre non fini": lambda: self.format.ModeleReseau.depuis_octets(json.dumps({**self.document}).replace('"ecart":', '"ecart":NaN,"x":', 1).encode()),
        }
        for nom, appel in cas.items():
            with self.subTest(nom), self.assertRaises(self.format.FormatInvalide):
                appel()

    def test_un_fichier_trop_gros_est_refuse(self):
        with self.assertRaisesRegex(self.format.FormatInvalide, "trop gros"):
            self.format.ModeleReseau.depuis_octets(b" " * (64 * 1024 * 1024 + 1))


if __name__ == "__main__":
    unittest.main()
