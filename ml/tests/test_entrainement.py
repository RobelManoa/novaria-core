"""Entraînement et comparaison (IA-03) : règles du cadrage ML en fonctions pures, puis la chaîne complète sur un petit jeu.

Les tests qui entraînent un modèle ont besoin de scikit-learn (`ml/.venv`, `python3 scripts/dev/dev.py ml-env`) et sont
ignorés sans lui. Aucun test ne lit le vrai fichier de test du jeu v1 : la chaîne complète tourne sur un petit jeu
fabriqué dans un dossier temporaire.
"""

import dataclasses
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import support
from tests.support import petit_catalogue

from entrainement import acceptation, candidats, evaluation, execution, rapport, selection, tracabilite
from jeu_entrainement import catalogue as cat
from jeu_entrainement import construire
from mesures.metriques import Alertes, Mesures
from preparation import ajustement, decoupage, donnees

try:
    import sklearn  # noqa: F401

    SKLEARN = True
except ImportError:
    SKLEARN = False

F, S, C = "FREE_FLOW", "SLOW", "CONGESTED"
JOURS = 14 * 1440


def mesures(f1=0.9, rappel=0.9, delais=(1,), manques=0, fausses=0, episodes=None, minutes=JOURS) -> Mesures:
    a = Alertes(delais=list(delais), episodes=episodes if episodes is not None else len(delais) + manques, manques=manques,
                alertes=len(delais) + fausses, fausses=fausses, minutes=minutes)
    return Mesures(f1, rappel, 0.9, {}, a)


class TestConfirmation(unittest.TestCase):
    def test_exemple_calcule_a_la_main(self):
        self.assertEqual(evaluation.confirmer([F, F, C, F, F, C, C, C, F]), [F, F, F, F, F, F, C, C, C])

    def test_un_etat_qui_clignote_n_est_jamais_annonce(self):
        self.assertEqual(set(evaluation.confirmer([F, C] * 20)), {F})

    def test_deux_etats_differents_ne_s_additionnent_pas(self):
        self.assertEqual(evaluation.confirmer([F, C, S, C, S, C]), [F] * 6)

    def test_la_premiere_prediction_est_annoncee_telle_quelle(self):
        self.assertEqual(evaluation.confirmer([C, C, F, C])[0], C)

    def test_une_confirmation_de_une_fenetre_ne_change_rien(self):
        predits = [F, C, F, S, S, C]
        self.assertEqual(evaluation.confirmer(predits, 1), predits)

    def test_serie_vide(self):
        self.assertEqual(evaluation.confirmer([]), [])

    def test_le_retour_au_fluide_est_aussi_confirme(self):
        self.assertEqual(evaluation.confirmer([C, C, C, F, C, C, F, F, F]), [C, C, C, C, C, C, C, F, F])


class TestMesuresDuModele(unittest.TestCase):
    def lignes(self):
        return [{"run_id": r, "road_segment_id": s, "label_state": F} for r, s, n in (("r1", "A", 3), ("r1", "B", 2), ("r2", "A", 4)) for _ in range(n)]

    def test_bornes_des_series(self):
        self.assertEqual(evaluation.bornes(self.lignes()), [(0, 3), (3, 5), (5, 9)])
        self.assertEqual(evaluation.bornes([]), [])

    def test_matrice_de_confusion_a_la_main(self):
        m = evaluation.matrice_de_confusion([F, F, S, C, C], [F, S, S, C, F])
        self.assertEqual(m[F], {F: 1, S: 1, C: 0})
        self.assertEqual(m[S], {F: 0, S: 1, C: 0})
        self.assertEqual(m[C], {F: 1, S: 0, C: 1})

    def test_la_confirmation_est_appliquee_par_serie_et_pas_sur_la_suite_des_lignes(self):
        """Deux séries bout à bout : le premier état de la seconde n'est pas « confirmé » par la fin de la première."""
        lignes = [{"run_id": "r", "road_segment_id": "A", "label_state": F}] * 3 + [{"run_id": "r", "road_segment_id": "B", "label_state": C}] * 3
        predits = [F, F, F, C, C, C]
        m = evaluation.mesurer_predictions(lignes, predits, True)
        self.assertEqual(m.alertes.alertes, 1)  # B annonce C dès sa première minute, sans attendre


class TestAcceptation(unittest.TestCase):
    REF = mesures(f1=0.976, rappel=0.974, delais=(1, 1))

    def condition(self, modele, numero):
        return next(c for c in acceptation.conditions(modele, self.REF) if c.numero == numero)

    def test_un_modele_qui_remplit_tout_est_accepte(self):
        liste = acceptation.conditions(mesures(f1=0.99, rappel=0.99, delais=(1, 1)), self.REF)
        self.assertEqual([c.numero for c in liste], ["A1", "A2", "A3", "A4", "A5"])
        self.assertTrue(acceptation.accepte(liste))

    def test_a1_et_a2_exigent_la_marge_de_0_01(self):
        self.assertTrue(self.condition(mesures(f1=0.986), "A1").remplie)
        self.assertFalse(self.condition(mesures(f1=0.9859), "A1").remplie)
        self.assertTrue(self.condition(mesures(rappel=0.984), "A2").remplie)
        self.assertFalse(self.condition(mesures(rappel=0.9839), "A2").remplie)

    def test_a3_le_delai_median_ne_depasse_pas_celui_de_la_regle(self):
        self.assertTrue(self.condition(mesures(delais=(0, 1, 1)), "A3").remplie)
        self.assertFalse(self.condition(mesures(delais=(2, 2, 3)), "A3").remplie)
        self.assertFalse(self.condition(mesures(delais=(), manques=2), "A3").remplie)  # jamais d'alerte : pas de délai

    def test_a4_un_seul_episode_manque_suffit_a_echouer(self):
        self.assertFalse(self.condition(mesures(delais=(1,), manques=1), "A4").remplie)
        self.assertTrue(self.condition(mesures(delais=(1,), manques=0), "A4").remplie)

    def test_a5_au_plus_une_fausse_alerte_sur_les_14_troncon_jours(self):
        self.assertTrue(self.condition(mesures(fausses=0), "A5").remplie)
        self.assertTrue(self.condition(mesures(fausses=1), "A5").remplie)  # 1 / 14 = 0,071
        self.assertFalse(self.condition(mesures(fausses=2), "A5").remplie)  # 2 / 14 = 0,143

    def test_un_bon_f1_ne_rachete_pas_les_fausses_alertes(self):
        nerveux = mesures(f1=0.995, rappel=0.995, delais=(0, 0), fausses=10)
        liste = acceptation.conditions(nerveux, self.REF)
        self.assertTrue(next(c for c in liste if c.numero == "A1").remplie)
        self.assertFalse(acceptation.accepte(liste))

    def test_eligible_est_a5_seule(self):
        self.assertTrue(acceptation.eligible(mesures(f1=0.1, fausses=1)))
        self.assertFalse(acceptation.eligible(mesures(f1=0.999, fausses=2)))

    def test_les_valeurs_sont_celles_du_cadrage(self):
        self.assertEqual((acceptation.MARGE, acceptation.BORNE_FAUSSES_ALERTES, acceptation.ECART_D_EGALITE), (0.01, 0.10, 0.002))


def essai(indice, f1, fausses_brut=0, fausses_confirme=0, params=None) -> selection.Essai:
    return selection.Essai(indice, params or {"i": indice}, mesures(f1=f1, fausses=fausses_brut), mesures(f1=f1 - 0.001, fausses=fausses_confirme), [])


class TestChoix(unittest.TestCase):
    def test_le_meilleur_eligible_est_retenu(self):
        retenu = selection.retenir([essai(0, 0.90), essai(1, 0.95), essai(2, 0.93)])
        self.assertEqual((retenu.essai.indice, retenu.variante), (1, "brut"))

    def test_un_reglage_qui_clignote_est_ecarte_malgre_son_f1(self):
        retenu = selection.retenir([essai(0, 0.90), essai(1, 0.99, fausses_brut=5)])
        self.assertEqual(retenu.essai.indice, 0)

    def test_sans_reglage_brut_eligible_la_confirmation_est_jugee(self):
        retenu = selection.retenir([essai(0, 0.90, fausses_brut=4), essai(1, 0.95, fausses_brut=4)])
        self.assertEqual((retenu.essai.indice, retenu.variante), (1, "confirme"))

    def test_aucun_reglage_eligible(self):
        self.assertIsNone(selection.retenir([essai(0, 0.9, fausses_brut=4, fausses_confirme=4)]))

    def test_a_egalite_parfaite_le_premier_de_la_grille(self):
        self.assertEqual(selection.retenir([essai(0, 0.9), essai(1, 0.9)]).essai.indice, 0)

    def retenu(self, f1):
        return selection.Retenu(essai(0, f1), "brut")

    def test_entre_candidats_le_meilleur_f1(self):
        nom, raison = selection.choisir_le_candidat({"logistique": self.retenu(0.95), "gradient": self.retenu(0.97)})
        self.assertEqual(nom, "gradient")
        self.assertIn("meilleur F1 macro", raison)

    def test_a_moins_de_0_002_le_plus_simple(self):
        nom, raison = selection.choisir_le_candidat({"logistique": self.retenu(0.9700), "gradient": self.retenu(0.9715)})
        self.assertEqual(nom, "logistique")
        self.assertIn("le plus simple", raison)

    def test_a_0_002_pile_le_gradient_garde_l_avantage(self):
        nom, _ = selection.choisir_le_candidat({"logistique": self.retenu(0.950), "gradient": self.retenu(0.952)})
        self.assertEqual(nom, "gradient")

    def test_un_candidat_non_eligible_ne_peut_pas_gagner(self):
        nom, _ = selection.choisir_le_candidat({"logistique": None, "gradient": self.retenu(0.5)})
        self.assertEqual(nom, "gradient")
        nom, raison = selection.choisir_le_candidat({"logistique": None, "gradient": None})
        self.assertIsNone(nom)
        self.assertIn("aucun candidat éligible", raison)


class TestCandidatsEtPlis(unittest.TestCase):
    def test_au_plus_12_reglages_par_candidat(self):
        for c in candidats.CANDIDATS:
            self.assertLessEqual(len(c.grille), candidats.MAX_COMBINAISONS, c.nom)
        self.assertEqual([c.nom for c in candidats.CANDIDATS], ["logistique", "gradient"])  # simple d'abord

    def test_une_grille_trop_large_est_refusee(self):
        trop = dataclasses.replace(candidats.LOGISTIQUE, grille=tuple({"C": i, "class_weight": None} for i in range(13)))
        with self.assertRaises(ValueError):
            selection.essayer_la_grille(trop, [], [], [])

    def test_les_reglages_sont_les_combinaisons_du_produit(self):
        self.assertEqual(len({tuple(sorted(g.items(), key=str)) for g in candidats.LOGISTIQUE.grille}), 8)
        self.assertEqual({g["class_weight"] for g in candidats.GRADIENT.grille}, {None, "balanced"})

    def test_plis_par_run_du_jeu_v1(self):
        runs = [(r.run_id, r.scenario_id) for r in cat.CATALOGUE if r.ensemble != cat.TEST]
        plis = decoupage.plis_par_run(runs)
        self.assertEqual(len(plis), 3)
        self.assertEqual(sorted(r for pli in plis for r in pli), sorted(r for r, _ in runs))
        scenario = dict(runs)
        for pli in plis:
            self.assertEqual(sorted(scenario[r] for r in pli), sorted(cat.SCENARIOS))  # un run de chaque scénario

    def test_les_plis_ne_touchent_jamais_le_test_ni_ne_coupent_un_run(self):
        runs = [(r.run_id, r.scenario_id) for r in cat.CATALOGUE if r.ensemble != cat.TEST]
        tests = {r.run_id for r in cat.CATALOGUE if r.ensemble == cat.TEST}
        plis = decoupage.plis_par_run(runs)
        self.assertFalse({r for pli in plis for r in pli} & tests)
        self.assertEqual(len({r for pli in plis for r in pli}), sum(len(p) for p in plis))  # un run, un pli

    def test_les_plis_sont_reproductibles_et_independants_de_l_ordre(self):
        runs = [(r.run_id, r.scenario_id) for r in cat.CATALOGUE if r.ensemble != cat.TEST]
        self.assertEqual(decoupage.plis_par_run(runs), decoupage.plis_par_run(list(reversed(runs))))

    def test_un_run_en_trop_va_dans_le_dernier_pli(self):
        plis = decoupage.plis_par_run([("a1", "x"), ("a2", "x"), ("a3", "x"), ("b1", "y"), ("b2", "y")])
        self.assertEqual(plis, [["a1", "b1"], ["a2", "a3", "b2"]])

    def test_un_scenario_a_un_seul_run_est_refuse(self):
        with self.assertRaises(ValueError):
            decoupage.plis_par_run([("a1", "x"), ("a2", "x"), ("b1", "y")])


class TestGardesDuTest(unittest.TestCase):
    def test_un_second_essai_sur_le_test_est_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            sortie = Path(tmp) / "resultat-test.json"
            sortie.write_text("{}", encoding="utf-8")
            with self.assertRaises(tracabilite.ControleDeSecurite) as e:
                execution.etape_test(sortie=sortie, selection_json=Path(tmp) / "selection.json")
            self.assertIn("déjà été lu", str(e.exception))

    def test_le_test_n_est_pas_lu_sans_selection_prealable(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(tracabilite.ControleDeSecurite) as e:
                execution.etape_test(sortie=Path(tmp) / "r.json", selection_json=Path(tmp) / "absente.json")
            self.assertIn("étape validation", str(e.exception))

    def test_une_selection_sans_candidat_n_ouvre_pas_le_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            sel = Path(tmp) / "selection.json"
            sel.write_text(json.dumps({"etape": "validation", "choix": {"candidat": None}}), encoding="utf-8")
            with self.assertRaises(tracabilite.ControleDeSecurite):
                execution.etape_test(sortie=Path(tmp) / "r.json", selection_json=sel)

    def test_le_fichier_de_test_du_jeu_est_ferme_par_defaut(self):
        with self.assertRaises(donnees.EnsembleReserve):
            donnees.charger("test", Path("n'importe/où"))


@unittest.skipUnless(SKLEARN, "scikit-learn absent : python3 scripts/dev/dev.py ml-env")
class TestChaineComplete(unittest.TestCase):
    """Validation, choix, test unique et rapport, sur neuf petits runs fabriqués (le vrai test du jeu v1 n'est pas lu)."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dossier = Path(cls._tmp.name) / "jeu"
        cls.catalogue = petit_catalogue()
        construire.construire(cls.dossier, cls.catalogue)
        cls.sortie_selection = Path(cls._tmp.name) / "selection.json"
        cls.sortie_test = Path(cls._tmp.name) / "resultat-test.json"
        cls.appels = []
        reel = donnees.charger

        def espion(ensemble, *args, **kwargs):
            cls.appels.append((ensemble, kwargs.get("evaluation_finale", False)))
            return reel(ensemble, *args, **kwargs)

        with mock.patch.object(donnees, "charger", espion):
            cls.selection = execution.etape_validation(cls.dossier, cls.sortie_selection, message=lambda _: None, catalogue=cls.catalogue)
        cls.appels_validation = list(cls.appels)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_la_validation_ne_lit_jamais_le_test(self):
        self.assertTrue(self.appels_validation)
        self.assertNotIn("test", [e for e, _ in self.appels_validation])

    def test_chaque_candidat_a_essaye_sa_grille_et_garde_une_trace_complete(self):
        for c in candidats.CANDIDATS:
            fiche = self.selection["candidats"][c.nom]
            self.assertEqual(len(fiche["essais"]), len(c.grille))
            self.assertTrue(all(0 <= e["brut"]["f1_macro"] <= 1 for e in fiche["essais"]))

    def test_les_deux_entrainements_identiques_donnent_les_memes_mesures(self):
        for fiche in self.selection["candidats"].values():
            if fiche["retenu"]:
                self.assertTrue(fiche["reproductible"])

    def test_la_validation_croisee_met_de_cote_un_run_de_chaque_scenario(self):
        for fiche in self.selection["candidats"].values():
            if fiche["retenu"]:
                cv = fiche["validation_croisee_groupee"]
                self.assertEqual(len(cv["plis"]), 2)
                for pli in cv["plis"]:
                    self.assertEqual(len(pli["runs_a_part"]), 3)
                    self.assertTrue(all(r not in {x.run_id for x in self.catalogue if x.ensemble == cat.TEST} for r in pli["runs_a_part"]))

    def test_la_tracabilite_est_complete(self):
        t = self.selection["tracabilite"]
        manifeste = json.loads((self.dossier / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(t["dataset_sha256"], manifeste["empreinte_du_jeu"])
        self.assertEqual(t["seed"], 42)
        self.assertIn("scikit-learn", t["versions"])
        self.assertEqual(json.loads(self.sortie_selection.read_text(encoding="utf-8")), self.selection)

    def test_la_validation_croisee_n_apprend_jamais_sur_les_runs_mis_de_cote(self):
        lignes = donnees.charger("train", self.dossier) + donnees.charger("validation", self.dossier)
        runs = [(r.run_id, r.scenario_id) for r in self.catalogue if r.ensemble != cat.TEST]
        vus = []
        reel = evaluation.preparer

        def espion(c, entrainement, runs_entrainement):
            vus.append({ligne["run_id"] for ligne in entrainement})
            return reel(c, entrainement, runs_entrainement)

        retenu = selection.Retenu(selection.Essai(0, candidats.LOGISTIQUE.grille[0], mesures(), mesures(), []), "brut")
        with mock.patch.object(evaluation, "preparer", espion):
            cv = selection.validation_croisee_groupee(candidats.LOGISTIQUE, retenu, lignes, runs)
        self.assertEqual(len(vus), len(cv["plis"]))
        for apprentissage, pli in zip(vus, cv["plis"], strict=True):
            self.assertFalse(apprentissage & set(pli["runs_a_part"]))
            self.assertEqual(apprentissage | set(pli["runs_a_part"]), {r for r, _ in runs})

    def test_la_preparation_refuse_un_run_de_validation(self):
        train = donnees.charger("train", self.dossier)
        validation = donnees.charger("validation", self.dossier)
        runs_train = {r.run_id for r in self.catalogue if r.ensemble == cat.TRAIN}
        with self.assertRaises(ajustement.FuiteDInformation):
            evaluation.preparer(candidats.LOGISTIQUE, train + validation, runs_train)

    def test_un_jeu_modifie_arrete_la_validation_avant_tout_entrainement(self):
        copie = Path(self._tmp.name) / "jeu-abime"
        shutil.copytree(self.dossier, copie)
        octets = bytearray((copie / "train.parquet").read_bytes())
        octets[200] ^= 0xFF
        (copie / "train.parquet").write_bytes(bytes(octets))
        with self.assertRaises(tracabilite.ControleDeSecurite) as e:
            execution.etape_validation(copie, Path(self._tmp.name) / "x.json", message=lambda _: None, catalogue=self.catalogue)
        self.assertIn("S1", str(e.exception))

    def test_test_unique_puis_refus_du_second_essai_puis_rapport(self):
        selection_json = Path(self._tmp.name) / "selection-test.json"
        choix = json.loads(self.sortie_selection.read_text(encoding="utf-8"))
        if choix["choix"]["candidat"] is None:  # petit jeu : aucun réglage éligible ; on force un choix pour exercer l'étape
            choix["choix"].update(candidat="logistique", variante="brut", params=candidats.LOGISTIQUE.grille[0])
        selection_json.write_text(json.dumps(choix), encoding="utf-8")
        lectures = []
        reel = donnees.charger

        def espion(ensemble, *args, **kwargs):
            lectures.append((ensemble, kwargs.get("evaluation_finale", False)))
            return reel(ensemble, *args, **kwargs)

        with mock.patch.object(donnees, "charger", espion):
            resultat = execution.etape_test(self.dossier, selection_json, self.sortie_test, message=lambda _: None, catalogue=self.catalogue)
        self.assertEqual(lectures.count(("test", True)), 1, "le test est lu une seule fois")
        self.assertEqual([e for e, final in lectures if final], ["test"])
        test_runs = {r.run_id for r in self.catalogue if r.ensemble == cat.TEST}
        train_runs = {r.run_id for r in self.catalogue if r.ensemble == cat.TRAIN}
        self.assertEqual(set(resultat["runs_du_test"]), test_runs)
        self.assertFalse(set(resultat["runs_d_entrainement"]) & set(resultat["runs_du_test"]))
        self.assertEqual(set(resultat["runs_d_entrainement"]), train_runs)
        self.assertEqual(resultat["selection_sha256"], tracabilite.sha256_fichier(selection_json))
        self.assertEqual([c["condition"] for c in resultat["conditions"]], ["A1", "A2", "A3", "A4", "A5"])
        self.assertIn(resultat["decision"], ("accepté", "rejeté"))
        self.assertEqual(resultat["decision"] == "accepté", all(c["remplie"] for c in resultat["conditions"]))
        self.assertEqual(sum(sum(ligne.values()) for ligne in resultat["matrice_modele"].values()),
                         len(donnees.charger("test", self.dossier, evaluation_finale=True)))
        with self.assertRaises(tracabilite.ControleDeSecurite):
            execution.etape_test(self.dossier, selection_json, self.sortie_test, message=lambda _: None, catalogue=self.catalogue)
        texte = rapport.ecrire(selection_json, self.sortie_test, Path(self._tmp.name) / "resultats.md")
        for morceau in ("Traçabilité", "Règle de seuils (référence)", "Validation croisée groupée par run", "Conditions d'acceptation", "Matrice de confusion", "Décision"):
            self.assertIn(morceau, texte)

    def test_le_test_modifie_apres_la_selection_est_refuse(self):
        copie = Path(self._tmp.name) / "jeu-abime-apres"
        shutil.copytree(self.dossier, copie)
        octets = bytearray((copie / "test.parquet").read_bytes())
        octets[200] ^= 0xFF
        (copie / "test.parquet").write_bytes(bytes(octets))
        with self.assertRaises(tracabilite.ControleDeSecurite):
            execution.etape_test(copie, self.sortie_selection, Path(self._tmp.name) / "r2.json", message=lambda _: None, catalogue=self.catalogue)

    def test_un_autre_jeu_coherent_est_refuse_parce_que_son_empreinte_n_est_pas_celle_de_la_selection(self):
        """Un jeu entièrement refait (manifeste compris) passe S1 seul ; l'empreinte écrite dans la sélection le trahit."""
        autre = Path(self._tmp.name) / "jeu-autre"
        construire.construire(autre, petit_catalogue(decalage_graine=1))
        self.assertEqual(tracabilite.exiger_le_jeu_intact(autre), json.loads((autre / "manifest.json").read_text(encoding="utf-8"))["empreinte_du_jeu"])
        with self.assertRaises(tracabilite.ControleDeSecurite) as e:
            execution.etape_test(autre, self.sortie_selection, Path(self._tmp.name) / "r3.json", message=lambda _: None, catalogue=self.catalogue)
        self.assertIn("empreinte", str(e.exception))

    def test_le_rapport_sans_test_dit_qu_il_n_est_pas_lu(self):
        texte = rapport.rediger(self.selection, None)
        self.assertIn("Le test n'a pas encore été lu", texte)
        self.assertNotIn("Décision", texte)

    def test_aucun_chiffre_du_rapport_n_est_tape_a_la_main(self):
        texte = rapport.rediger(self.selection, None)
        ref = self.selection["reference_validation"]["f1_macro"]
        self.assertIn(str(f"{ref:.3f}").replace(".", ","), texte)


if __name__ == "__main__":
    unittest.main()
