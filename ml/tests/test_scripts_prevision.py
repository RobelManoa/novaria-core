"""Les trois scripts de prévision à arbres d'IA-16 (entraînement final, expérience des variables, expérience des réglages) sur un petit jeu fabriqué.

Les vrais scripts lisent METR-LA (absent de Git et de la CI) : ici `preparer()` rend une série fabriquée de 7 semaines et 12 capteurs, et
les réglages d'arbres sont réduits. Le but n'est pas la qualité de la prévision mais que la chaîne tourne de bout en bout : variables,
entraînement, lecture unique du test, export du modèle sans pickle, relecture et comparaison avec scikit-learn.
"""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import support  # noqa: F401  (chemins d'import)

LIBS = importlib.util.find_spec("numpy") is not None and importlib.util.find_spec("sklearn") is not None
PETITS_ARBRES = {"max_leaf_nodes": 7, "max_iter": 8, "learning_rate": 0.2, "min_samples_leaf": 20}


def _preparer_fabrique():
    """Même rendu que `experience_voisins.preparer()`, sur 7 semaines de 12 capteurs fabriqués."""
    import numpy as np

    from jeu_entrainement import catalogue as cat
    from prevision import PAS_PAR_JOUR, variables
    from prevision.donnees import Serie
    from prevision.rapport import GARDE_MIN, PARTS
    from preparation import decoupage

    rng = np.random.default_rng(11)
    pas = 7 * 7 * PAS_PAR_JOUR
    instants = 4 * 86_400_000 + np.arange(pas, dtype=np.int64) * 300_000
    jour = np.sin(2 * np.pi * (np.arange(pas) % PAS_PAR_JOUR) / PAS_PAR_JOUR)
    lent = np.convolve(rng.normal(size=pas), np.ones(8) / 8, mode="same")
    brut = np.stack([60 + 5 * jour + 6 * lent + rng.normal(scale=0.4, size=pas) for _ in range(12)], axis=1)
    brut[rng.random(brut.shape) < 0.02] = np.nan
    serie = Serie("essai", instants, tuple(f"S{i}" for i in range(12)), brut)
    partition = decoupage.decouper_dans_l_ordre_du_temps([int(i) for i in instants], PARTS, GARDE_MIN)
    parties = {n: np.array(sorted(partition[n])) for n in (cat.TRAIN, cat.VALIDATION, cat.TEST)}
    parties = {n: idx[idx >= variables.DEBUT_MIN] for n, idx in parties.items()}
    rempli = variables.remplir(brut, float(np.nanmean(brut[parties[cat.TRAIN]])))
    return serie, brut, instants, parties, rempli


@unittest.skipUnless(LIBS, "numpy et scikit-learn absents")
class ScriptsPrevision(unittest.TestCase):
    def test_l_entrainement_final_lit_le_test_une_fois_et_ecrit_un_modele_relisible(self):
        from prevision import entrainer_ia16
        from registre import format_arbres

        with tempfile.TemporaryDirectory() as t:
            racine = Path(t)
            (racine / "ml" / "evaluation").mkdir(parents=True)
            with (
                mock.patch.object(entrainer_ia16, "preparer", _preparer_fabrique),
                mock.patch.object(entrainer_ia16, "RACINE", racine),
                mock.patch.object(entrainer_ia16, "DOSSIER", racine / "ml" / "evaluation"),
                mock.patch.object(entrainer_ia16, "RESULTAT", racine / "ml" / "evaluation" / "prevision-ia16.json"),
                mock.patch.object(entrainer_ia16, "MODELES", racine / "var" / "models"),
                mock.patch.object(entrainer_ia16, "PARAMS_IA16", PETITS_ARBRES),
                mock.patch.object(entrainer_ia16, "PARAMS_IA10", PETITS_ARBRES),
                mock.patch.object(entrainer_ia16, "PAS_APPRENTISSAGE", 40),
                mock.patch.object(entrainer_ia16, "LIGNES_DE_CONTROLE", 50),
            ):
                sortie = entrainer_ia16.lancer(progres=lambda _: None)
                self.assertEqual(sortie["lecture_du_test"], 2)
                self.assertEqual(set(sortie["horizons"]), {"5", "15", "30"})
                bloc = sortie["horizons"]["5"]
                self.assertLess(bloc["modele"]["ecart_max_avec_scikit_learn"], 1e-6)  # le lecteur sans pickle redonne scikit-learn
                self.assertIn("bas", bloc["ecarts"]["persistance"])  # écart de MAE avec son intervalle
                fichier = racine / bloc["modele"]["fichier"]
                relu = format_arbres.ModeleArbres.depuis_octets(fichier.read_bytes())
                self.assertGreater(len(relu.arbres), 0)
                self.assertEqual(json.loads((racine / "ml" / "evaluation" / "prevision-ia16.json").read_text(encoding="utf-8"))["jeu"], "METR-LA")
                with self.assertRaisesRegex(SystemExit, "une seule lecture"):  # le test ne se lit pas deux fois
                    entrainer_ia16.lancer(progres=lambda _: None)

    def test_les_deux_experiences_sur_la_validation_ne_lisent_pas_le_test(self):
        from prevision import experience_reglages, experience_voisins

        reglages = tuple((nom, k, 40, PETITS_ARBRES) for nom, k, _, _ in experience_reglages.CONFIGS[:2])
        with (
            mock.patch.object(experience_voisins, "preparer", _preparer_fabrique),
            mock.patch.object(experience_reglages, "preparer", _preparer_fabrique),
            mock.patch.object(experience_voisins, "PARAMS", PETITS_ARBRES),
            mock.patch.object(experience_voisins, "PAS_APPRENTISSAGE", 40),
            mock.patch.object(experience_reglages, "CONFIGS", reglages),
        ):
            sortie = io.StringIO()
            with contextlib.redirect_stdout(sortie):
                experience_voisins.main((1,))
                experience_reglages.main((1,))
        texte = sortie.getvalue()
        self.assertIn("persistance MAE validation", texte)
        self.assertIn("base + voisins", texte)
        self.assertIn("K=10", texte)
        self.assertNotIn("test", texte.lower().replace("tout", "").replace("contexte", ""))  # la validation seulement

    def test_la_preparation_decoupe_dans_l_ordre_du_temps(self):
        from jeu_entrainement import catalogue as cat

        serie, brut, instants, parties, rempli = _preparer_fabrique()
        self.assertLess(parties[cat.TRAIN].max(), parties[cat.VALIDATION].min())
        self.assertLess(parties[cat.VALIDATION].max(), parties[cat.TEST].min())
        self.assertEqual(rempli.shape, brut.shape)

    def test_la_preparation_lit_le_fichier_verifie_et_garde_la_validation_apres_la_garde(self):
        from jeu_entrainement import catalogue as cat
        from prevision import donnees, experience_voisins, source

        fabrique = _preparer_fabrique()[0]
        with (
            mock.patch.object(source, "verifier", return_value=Path("metr-la.h5")),
            mock.patch.object(donnees, "charger_metr_la", return_value=fabrique) as charge,
        ):
            serie, brut, instants, parties, rempli = experience_voisins.preparer()
        charge.assert_called_once_with(Path("metr-la.h5"))
        self.assertIs(serie, fabrique)
        self.assertEqual(rempli.shape, brut.shape)
        self.assertEqual(set(parties), {cat.TRAIN, cat.VALIDATION, cat.TEST})

    def test_l_etape_exporter_ecrit_le_dossier_du_reseau_et_le_dit(self):
        from prevision import __main__ as principal
        from prevision import donnees, exporter_vitesses, source

        fabrique = _preparer_fabrique()[0]
        with tempfile.TemporaryDirectory() as t:
            sortie = io.StringIO()
            with (
                mock.patch.object(source, "verifier", return_value=Path("metr-la.h5")),
                mock.patch.object(donnees, "charger_metr_la", return_value=fabrique),
                mock.patch.object(exporter_vitesses, "DOSSIER", Path(t)),
                mock.patch("sys.argv", ["exporter", "--depuis", "1970-01-05"]),
                contextlib.redirect_stdout(sortie),
            ):
                code = principal.main(["exporter"])
            self.assertEqual(code, 0)
            self.assertIn("12 capteurs", sortie.getvalue())
            self.assertTrue((Path(t) / "manifeste.json").is_file() and (Path(t) / "mesures.csv").is_file())

    def test_les_etapes_du_reseau_appellent_l_entrainement_et_un_refus_se_dit_sans_trace(self):
        import sys
        import types

        from prevision import __main__ as principal

        appels = []
        faux = types.ModuleType("prevision.entrainer_reseau")
        faux.entrainer = lambda: appels.append("entrainer")
        faux.evaluer = lambda: appels.append("evaluer")
        with mock.patch.dict(sys.modules, {"prevision.entrainer_reseau": faux}):
            with mock.patch.object(sys.modules["prevision"], "entrainer_reseau", faux, create=True):
                self.assertEqual(principal.main(["entrainer-reseau"]), 0)
                self.assertEqual(principal.main(["evaluer-reseau"]), 0)
        self.assertEqual(appels, ["entrainer", "evaluer"])
        erreur = io.StringIO()
        with mock.patch.object(principal.source, "verifier", side_effect=principal.source.FichierRefuse("absent")):
            with contextlib.redirect_stderr(erreur):
                self.assertEqual(principal.main(["verifier"]), 1)
        self.assertIn("Refusé", erreur.getvalue())


if __name__ == "__main__":
    unittest.main()
