"""Variables habituelles et voisines (IA-16) : pas de fuite du futur, pas de fuite de la ligne dans son propre habituel, voisins sensés."""

import importlib.util
import unittest

from tests import support  # noqa: F401  (chemins d'import)

NUMPY = importlib.util.find_spec("numpy") is not None


@unittest.skipUnless(NUMPY, "numpy absent (ml/.venv)")
class Voisins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np

        from prevision import PAS_PAR_JOUR, voisins

        cls.np, cls.voisins = np, voisins
        rng = np.random.default_rng(5)
        cls.semaines = 6
        pas = cls.semaines * 7 * PAS_PAR_JOUR
        cls.debut_ms = 4 * 86_400_000  # un lundi 00:00 (le 5 janvier 1970)
        cls.instants = cls.debut_ms + np.arange(pas, dtype=np.int64) * 300_000
        # Deux groupes de 4 capteurs : chacun suit son propre ralentissement ; le profil de la semaine est commun.
        ralentissement_a = np.convolve(rng.normal(size=pas), np.ones(8) / 8, mode="same")
        ralentissement_b = np.convolve(rng.normal(size=pas), np.ones(8) / 8, mode="same")
        jour = np.sin(2 * np.pi * (np.arange(pas) % PAS_PAR_JOUR) / PAS_PAR_JOUR)
        colonnes = [60 + 5 * jour + 6 * ralentissement_a + rng.normal(scale=0.3, size=pas) for _ in range(4)]
        colonnes += [60 + 5 * jour + 6 * ralentissement_b + rng.normal(scale=0.3, size=pas) for _ in range(4)]
        cls.brut = np.stack(colonnes, axis=1)
        cls.brut[rng.random(cls.brut.shape) < 0.02] = np.nan
        from prevision import variables

        cls.rempli = variables.remplir(cls.brut, 60.0)
        cls.apprentissage = np.arange(variables.DEBUT_MIN, 4 * 7 * PAS_PAR_JOUR)  # quatre semaines pour apprendre
        cls.profil = voisins.apprendre(cls.rempli, cls.brut, cls.instants, cls.apprentissage, k=3)

    def test_le_creneau_de_la_semaine_part_du_lundi(self):
        np = self.np
        self.assertEqual(int(self.voisins.creneau(np.array([self.debut_ms]))[0]), 0)  # lundi 00:00
        self.assertEqual(int(self.voisins.creneau(np.array([self.debut_ms + 300_000]))[0]), 1)
        self.assertEqual(int(self.voisins.creneau(np.array([self.debut_ms + 7 * 86_400_000]))[0]), 0)  # une semaine plus tard
        self.assertEqual(int(self.voisins.creneau(np.array([0]))[0]), 3 * 288)  # le 1er janvier 1970 est un jeudi

    def test_les_voisins_d_un_capteur_sont_ceux_de_son_groupe(self):
        for capteur in range(8):
            groupe = set(range(4)) if capteur < 4 else set(range(4, 8))
            self.assertEqual(set(self.profil.voisins[capteur].tolist()), groupe - {capteur}, f"capteur {capteur}")

    def test_un_capteur_n_est_jamais_son_propre_voisin(self):
        for capteur in range(8):
            self.assertNotIn(capteur, self.profil.voisins[capteur])

    def test_les_noms_correspondent_aux_colonnes(self):
        np = self.np
        t = np.arange(400, 420)
        colonnes = self.voisins.variables(self.profil, self.rempli, self.instants, t, 6)
        self.assertEqual(colonnes.shape, (20 * 8, len(self.profil.noms())))
        self.assertEqual(len(set(self.profil.noms())), len(self.profil.noms()))

    def test_les_variables_ne_regardent_jamais_le_futur(self):
        np = self.np
        t = np.arange(900, 910)
        avant = self.voisins.variables(self.profil, self.rempli, self.instants, t, 6)
        futur = self.rempli.copy()
        futur[t.max() + 1 :] += 1000.0  # on change tout ce qui suit le dernier instant
        apres = self.voisins.variables(self.profil, futur, self.instants, t, 6)
        np.testing.assert_array_equal(avant, apres)

    def test_en_apprentissage_l_habituel_ne_contient_pas_la_semaine_de_la_ligne(self):
        np = self.np
        from prevision import PAS_PAR_JOUR

        # On abîme une seule semaine d'apprentissage : l'habituel « hors semaine » de cette semaine ne doit pas le voir.
        brut = self.brut.copy()
        semaine_cible = 2
        brut[semaine_cible * 7 * PAS_PAR_JOUR : (semaine_cible + 1) * 7 * PAS_PAR_JOUR] += 500.0
        from prevision import variables

        rempli = variables.remplir(brut, 60.0)
        profil = self.voisins.apprendre(rempli, brut, self.instants, self.apprentissage, k=3)
        rang = semaine_cible - 0  # la première semaine du jeu est la semaine 0 de l'apprentissage
        self.assertLess(float(profil.habituel_hors_semaine[rang].max()), 100.0)  # sans la semaine abîmée : habituel normal
        self.assertGreater(float(profil.habituel.max()), 100.0)  # avec : l'habituel global la contient
        autre = (rang + 1) % self.semaines
        self.assertGreater(float(profil.habituel_hors_semaine[autre].max()), 100.0)  # une autre semaine, elle, la voit

    def test_l_habituel_ne_depend_que_de_l_apprentissage(self):
        np = self.np
        from prevision import variables

        brut = self.brut.copy()
        brut[4 * 7 * 288 :] += 300.0  # tout ce qui suit l'apprentissage (validation, test) est abîmé
        rempli = variables.remplir(brut, 60.0)
        profil = self.voisins.apprendre(rempli, brut, self.instants, self.apprentissage, k=3)
        np.testing.assert_array_equal(profil.habituel, self.profil.habituel)
        np.testing.assert_array_equal(profil.voisins, self.profil.voisins)


if __name__ == "__main__":
    unittest.main()
