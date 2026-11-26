"""Le lecteur numpy du réseau (IA-16) sans PyTorch : ces tests tournent aussi sur la CI, où PyTorch n'est pas installé.

Le réseau est écrit à la main (quelques poids fixés), pas appris : on vérifie ce que le lecteur promet, c'est-à-dire qu'il refuse
tout ce qui n'est pas exactement le format et que son passage avant est stable, de la bonne forme et sensible à l'entrée.
La parité avec PyTorch est contrôlée dans `test_reseau.py` (ignoré sans PyTorch).
"""

import importlib.util
import json
import unittest

from tests import support  # noqa: F401  (chemins d'import)

NUMPY = importlib.util.find_spec("numpy") is not None

CAPTEURS = ["A", "B"]
CACHE = 3


def _document(poids_valeur: float = 0.0) -> dict:
    """Un document valide : 2 capteurs, 3 neurones cachés ; tous les poids valent `poids_valeur`."""
    from registre.lecteur_reseau import PAS_PAR_SEMAINE, formes_attendues

    def plat(forme):
        if len(forme) == 1:
            return [poids_valeur] * forme[0]
        return [plat(forme[1:]) for _ in range(forme[0])]

    n = len(CAPTEURS)
    return {
        "format": "novaria-modele-reseau",
        "version": 1,
        "capteurs": list(CAPTEURS),
        "moyenne": 55.0,
        "ecart": 10.0,
        "echelle_sortie": 10.0,
        "adjacence": [[0.5, 0.5], [0.5, 0.5]],
        "habituel": [[0.0] * n for _ in range(PAS_PAR_SEMAINE)],
        "poids": {nom: plat(forme) for nom, forme in formes_attendues(CACHE).items()},
        "meta": {"jeu": "essai"},
    }


def _octets(document: dict) -> bytes:
    return json.dumps(document).encode("utf-8")


@unittest.skipUnless(NUMPY, "numpy absent (ml/.venv)")
class Lecture(unittest.TestCase):
    def setUp(self):
        import numpy as np

        from registre.lecteur_reseau import ModeleReseau

        self.np, self.classe = np, ModeleReseau
        self.instants = 4 * 86_400_000 + np.arange(12, dtype=np.int64) * 300_000
        self.vitesses = np.tile(np.array([[50.0, 62.0]]), (12, 1))
        self.presentes = np.ones((12, 2))

    def test_un_document_valide_est_relu_avec_ses_champs(self):
        modele = self.classe.depuis_octets(_octets(_document()))
        self.assertEqual(modele.capteurs, ("A", "B"))
        self.assertEqual((modele.moyenne, modele.ecart, modele.echelle_sortie, modele.cache), (55.0, 10.0, 10.0, CACHE))
        self.assertEqual(modele.meta, {"jeu": "essai"})
        self.assertEqual(modele.habituel.shape, (2016, 2))
        self.assertEqual(modele.poids["gru.weight_ih_l0"].shape, (9, 3))

    def test_des_poids_nuls_rendent_la_persistance(self):
        np = self.np
        modele = self.classe.depuis_octets(_octets(_document(0.0)))
        prevu = modele.predire(self.vitesses, self.presentes, self.instants)
        self.assertEqual(prevu.shape, (2, 6))
        self.assertTrue(np.allclose(prevu[0], 50.0) and np.allclose(prevu[1], 62.0))

    def test_des_poids_non_nuls_changent_la_prevision_et_elle_depend_de_l_entree(self):
        np = self.np
        modele = self.classe.depuis_octets(_octets(_document(0.3)))
        base = modele.predire(self.vitesses, self.presentes, self.instants)
        self.assertTrue(np.isfinite(base).all())
        self.assertFalse(np.allclose(base[0], 50.0))
        self.assertTrue(np.array_equal(base, modele.predire(self.vitesses, self.presentes, self.instants)))  # déterministe
        autre = modele.predire(self.vitesses - 20.0, self.presentes, self.instants)
        self.assertGreater(float(np.abs(autre - base).max()), 0.1)

    def test_le_creneau_de_la_semaine_part_du_lundi(self):
        from registre.lecteur_reseau import creneau

        np = self.np
        lundi = 4 * 86_400_000  # le 5 janvier 1970 est un lundi
        self.assertEqual(int(creneau(np.array([lundi]))[0]), 0)
        self.assertEqual(int(creneau(np.array([lundi + 300_000]))[0]), 1)
        self.assertEqual(int(creneau(np.array([lundi + 7 * 86_400_000]))[0]), 0)
        self.assertEqual(int(creneau(np.array([0]))[0]), 3 * 288)  # le 1er janvier 1970 est un jeudi

    def test_une_fenetre_mal_formee_est_refusee(self):
        np = self.np
        modele = self.classe.depuis_octets(_octets(_document()))
        with self.assertRaisesRegex(ValueError, "forme"):
            modele.predire(np.ones((5, 2)), np.ones((5, 2)), self.instants[:5])
        with self.assertRaisesRegex(ValueError, "instants"):
            modele.predire(self.vitesses, self.presentes, self.instants[:5])
        with self.assertRaisesRegex(ValueError, "manquante"):
            modele.predire(np.full((12, 2), np.nan), self.presentes, self.instants)


@unittest.skipUnless(NUMPY, "numpy absent (ml/.venv)")
class Refus(unittest.TestCase):
    def lire(self, document=None, octets=None):
        from registre.lecteur_reseau import ModeleReseau

        return ModeleReseau.depuis_octets(octets if octets is not None else _octets(document))

    def test_le_lecteur_refuse_tout_ce_qui_n_est_pas_le_format(self):
        from registre.lecteur_reseau import FormatInvalide

        def avec(**changements):
            return {**_document(), **changements}

        def sans_poids(nom):
            document = _document()
            del document["poids"][nom]
            return document

        def poids(**changements):
            document = _document()
            document["poids"].update(changements)
            return document

        cas = {
            "pas du JSON": {"octets": b"{pas du json"},
            "pas de l'UTF-8": {"octets": b"\xff\xfe"},
            "pas un objet": {"octets": b"[1, 2]"},
            "champ en trop": {"document": avec(extra=1)},
            "champ manquant": {"document": {k: v for k, v in _document().items() if k != "meta"}},
            "mauvais format": {"document": avec(format="autre")},
            "mauvaise version": {"document": avec(version=2)},
            "capteurs vides": {"document": avec(capteurs=[])},
            "capteurs pas en liste": {"document": avec(capteurs="AB")},
            "nom de capteur vide": {"document": avec(capteurs=["A", ""])},
            "capteurs en double": {"document": avec(capteurs=["A", "A"])},
            "écart nul": {"document": avec(ecart=0)},
            "échelle négative": {"document": avec(echelle_sortie=-1.0)},
            "moyenne booléenne": {"document": avec(moyenne=True)},
            "moyenne en texte": {"document": avec(moyenne="55")},
            "meta pas un objet": {"document": avec(meta=[])},
            "poids pas un objet": {"document": avec(poids=[])},
            "poids sans entrée": {"document": avec(poids={})},
            "entrée pas une liste": {"document": poids(**{"entree.weight": 3})},
            "entrée vide": {"document": poids(**{"entree.weight": []})},
            "poids manquant": {"document": sans_poids("tete.2.bias")},
            "poids en trop": {"document": poids(inconnu=[1.0])},
            "poids de mauvaise forme": {"document": poids(**{"tete.2.bias": [0.0]})},
            "poids pas des nombres": {"document": poids(**{"entree.bias": ["a", "b", "c"]})},
            "adjacence de mauvaise forme": {"document": avec(adjacence=[[1.0]])},
            "adjacence négative": {"document": avec(adjacence=[[1.0, -0.5], [0.5, 0.5]])},
            "habituel de mauvaise forme": {"document": avec(habituel=[[0.0, 0.0]])},
            "constante NaN": {"octets": _octets(_document()).replace(b'"ecart": 10.0', b'"ecart": NaN')},
            "constante Infinity": {"octets": _octets(_document()).replace(b'"moyenne": 55.0', b'"moyenne": Infinity')},
        }
        for nom, arguments in cas.items():
            with self.subTest(nom), self.assertRaises(FormatInvalide):
                self.lire(**arguments)

    def test_un_nombre_non_fini_dans_un_tableau_est_refuse(self):
        from registre.lecteur_reseau import FormatInvalide

        document = _document()
        document["poids"]["entree.bias"] = [123456.0, 0.0, 0.0]
        octets = json.dumps(document).encode("utf-8").replace(b"123456.0", b"1e999")  # 1e999 devient l'infini à la lecture
        with self.assertRaisesRegex(FormatInvalide, "finis"):
            self.lire(octets=octets)

    def test_un_fichier_trop_gros_est_refuse(self):
        from registre import lecteur_reseau

        ancienne = lecteur_reseau.TAILLE_MAX
        lecteur_reseau.TAILLE_MAX = 10
        try:
            with self.assertRaisesRegex(lecteur_reseau.FormatInvalide, "trop gros"):
                self.lire(octets=b" " * 11)
        finally:
            lecteur_reseau.TAILLE_MAX = ancienne


if __name__ == "__main__":
    unittest.main()
