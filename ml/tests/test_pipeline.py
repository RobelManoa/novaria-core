"""Pipeline MLSecOps (IA-05) : décision, contrôles de sécurité, étapes `evaluer`, `porte` et `enregistrer`, ligne de commande.

La chaîne complète tourne sur un petit jeu fabriqué dans un dossier temporaire (le vrai test du jeu v1 n'est pas lu) et
a besoin de scikit-learn ; le reste est en bibliothèque standard. Les fichiers que le pipeline lit et écrit sont redirigés
vers un dossier temporaire : aucun test ne touche `var/` ni `ml/evaluation/`.
"""

import contextlib
import copy
import inspect
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from tests import support  # noqa: F401 : chemins d'import
from tests.support import petit_catalogue
from tests.test_entrainement import chemins
from tests.test_registre import GIT, octets_de_modele, T0

import pipeline
from entrainement import acceptation, candidats, execution, tracabilite
from jeu_entrainement import construire
from mesures.metriques import Alertes, Mesures
from pipeline import __main__ as cli
from pipeline import controles, decision, etapes
from preparation import donnees
from registre.runs import FichierRunStore, MemoireRunStore
from stockage import StockageLocal, sha256

try:
    import sklearn  # noqa: F401

    SKLEARN = True
except ImportError:
    SKLEARN = False

FICHE_RELUE = """# Fiche du modèle : logistique

## 1. Usage prévu
x
## 2. Données
x
## 3. Métriques
x
## 4. Limites
x
## 5. Statut
x

**Relue par** : Daddy Luciano, 12/11/2026
"""


@contextlib.contextmanager
def dossier_du_pipeline(racine: Path, fiche: str | None = FICHE_RELUE):
    """Redirige tout ce que le pipeline lit et écrit vers `racine`."""
    (racine / "docs").mkdir(exist_ok=True)
    if fiche is not None:
        (racine / "docs" / "fiche-modele.md").write_text(fiche, encoding="utf-8")
    with mock.patch.object(pipeline, "DOSSIER", racine / "pipeline"), \
            mock.patch.object(pipeline, "RUNS", racine / "pipeline" / "model_runs"), \
            mock.patch.object(pipeline, "DECISION", racine / "pipeline" / "decision.json"), \
            mock.patch.object(pipeline, "MODELE_PREPARE", racine / "pipeline" / "modele.json"), \
            mock.patch.object(pipeline, "RAPPORT_MD", racine / "pipeline" / "rapport.md"), \
            mock.patch.object(pipeline, "AUDIT_JSON", racine / "pipeline" / "audit.json"), \
            mock.patch.object(pipeline, "SBOM", racine / "pipeline" / "sbom.json"), \
            mock.patch.object(pipeline, "MAGASIN", racine / "models"), \
            mock.patch.object(pipeline, "FICHE", racine / "docs" / "fiche-modele.md"):
        yield


def condition(numero="A1", remplie=True) -> dict:
    return {"condition": numero, "libelle": f"condition {numero}", "modele": 0.9, "exige": "≥ 0.5", "remplie": remplie}


def controle(code="S1", ok=True, bloquant=True) -> dict:
    return {"code": code, "libelle": f"contrôle {code}", "ok": ok, "detail": "détail", "bloquant": bloquant}


class TestDecision(unittest.TestCase):
    def test_accepte_si_tout_est_rempli_et_verifie(self):
        accepte, raisons = decision.decider([condition("A1"), condition("A2")], [controle("S1"), controle("S4", ok=False, bloquant=False)])
        self.assertTrue(accepte)
        self.assertEqual(raisons, [])

    def test_une_condition_de_performance_manquee_ferme_la_porte(self):
        accepte, raisons = decision.decider([condition("A1"), condition("A5", remplie=False)], [controle()])
        self.assertFalse(accepte)
        self.assertEqual(len(raisons), 1)
        self.assertIn("A5 manquée", raisons[0])

    def test_un_controle_bloquant_en_echec_ferme_la_porte_meme_avec_un_bon_score(self):
        for code in ("S1", "S2", "S3", "S5", "T1", "R1"):
            with self.subTest(code=code):
                accepte, raisons = decision.decider([condition()], [controle(code, ok=False)])
                self.assertFalse(accepte)
                self.assertIn(f"{code} en échec", raisons[0])

    def test_un_controle_bloquant_non_verifie_ferme_la_porte(self):
        accepte, raisons = decision.decider([condition()], [controle("S5", ok=None)])
        self.assertFalse(accepte)
        self.assertIn("non vérifié", raisons[0])

    def test_un_controle_non_bloquant_n_arrete_rien(self):
        for ok in (False, None):
            self.assertTrue(decision.decider([condition()], [controle("S4", ok=ok, bloquant=False)])[0])

    def test_toutes_les_raisons_sont_donnees(self):
        _, raisons = decision.decider([condition("A2", False), condition("A5", False)], [controle("S5", ok=False), controle("T1", ok=None)])
        self.assertEqual(len(raisons), 4)


class TestLectureDeLaDecision(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.racine = Path(self._tmp.name)

    def ecrire(self, **changements):
        d = {"decision": "accepté", "conditions": [condition()], "securite": [controle()]}
        d.update(changements)
        with dossier_du_pipeline(self.racine):
            pipeline.DOSSIER.mkdir(parents=True, exist_ok=True)
            pipeline.DECISION.write_text(json.dumps(d), encoding="utf-8")

    def lire(self):
        with dossier_du_pipeline(self.racine):
            return decision.lire()

    def test_une_decision_coherente_se_lit(self):
        self.ecrire()
        self.assertEqual(self.lire()["raisons"], [])

    def test_un_verdict_gonfle_a_la_main_est_refuse(self):
        """Étapes séparées, fichier modifiable entre deux : « accepté » avec une condition manquée ne passe pas."""
        self.ecrire(decision="accepté", conditions=[condition("A2", remplie=False)])
        with self.assertRaises(decision.DecisionIncoherente) as e:
            self.lire()
        self.assertIn("fichier modifié", str(e.exception))

    def test_un_verdict_negatif_incoherent_est_aussi_refuse(self):
        self.ecrire(decision="rejeté")
        with self.assertRaises(decision.DecisionIncoherente):
            self.lire()

    def test_absente_illisible_ou_incomplete(self):
        with dossier_du_pipeline(self.racine), self.assertRaises(decision.DecisionIncoherente):
            decision.lire()
        with dossier_du_pipeline(self.racine):
            pipeline.DOSSIER.mkdir(parents=True, exist_ok=True)
            for contenu in ("pas du json", "{}", json.dumps({"decision": "accepté", "conditions": [{}], "securite": []}), "[]"):
                pipeline.DECISION.write_text(contenu, encoding="utf-8")
                with self.subTest(contenu=contenu[:20]), self.assertRaises(decision.DecisionIncoherente):
                    decision.lire()


class TestControlesS2S3(unittest.TestCase):
    def test_s2_l_artefact_relu_predit_comme_le_modele(self):
        c = controles.s2_artefact_trace(b"x", ["A", "B"], lambda _b: ["A", "B"])
        self.assertEqual((c.code, c.ok, c.bloquant), ("S2", True, True))

    def test_s2_un_ecart_de_prediction_echoue(self):
        c = controles.s2_artefact_trace(b"x", ["A", "B", "C"], lambda _b: ["A", "B", "A"])
        self.assertFalse(c.ok)
        self.assertIn("1 écart", c.detail)

    def test_s2_une_longueur_differente_echoue(self):
        self.assertFalse(controles.s2_artefact_trace(b"x", ["A", "B"], lambda _b: ["A"]).ok)

    def test_s2_pas_d_artefact_ou_artefact_illisible(self):
        self.assertFalse(controles.s2_artefact_trace(None, ["A"], lambda _b: ["A"]).ok)

        def illisible(_b):
            raise ValueError("JSON illisible")

        self.assertFalse(controles.s2_artefact_trace(b"x", ["A"], illisible).ok)

    def test_s3_un_modele_du_format_sur_passe(self):
        self.assertTrue(controles.s3_format_sur("logistique", octets_de_modele(), None).ok)

    def test_s3_un_candidat_sans_format_sur_echoue(self):
        c = controles.s3_format_sur("gradient", None, "seul un Pipeline s'exporte")
        self.assertFalse(c.ok)
        self.assertIn("gradient", c.detail)

    def test_s3_un_fichier_hors_format_echoue(self):
        import pickle

        self.assertFalse(controles.s3_format_sur("logistique", pickle.dumps({"x": 1}), None).ok)
        self.assertFalse(controles.s3_format_sur("logistique", None, None).ok)


class TestControleS4(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.racine = Path(self._tmp.name)
        self.exigences = self.racine / "requirements.txt"
        self.exigences.write_text("x==1\n", encoding="utf-8")

    def faux_outil(self, corps: str) -> str:
        chemin = self.racine / "pip-audit"
        chemin.write_text(f"#!{sys.executable}\nimport json, sys\nargs = sys.argv\nsortie = args[args.index('-o') + 1]\nformat_ = args[args.index('-f') + 1]\n{corps}\n", encoding="utf-8")
        chemin.chmod(chemin.stat().st_mode | stat.S_IEXEC)
        return str(chemin)

    @unittest.skipIf(os.name == "nt", "un script exécutable demande un interpréteur associé sous Windows")
    def test_aucune_vulnerabilite(self):
        outil = self.faux_outil("open(sortie, 'w').write(json.dumps({'dependencies': [{'name': 'x', 'version': '1', 'vulns': []}]}))\nsys.exit(0)")
        with dossier_du_pipeline(self.racine):
            c = controles.s4_dependances(self.exigences, outil)
        self.assertEqual((c.ok, c.bloquant), (True, False))
        self.assertIn("1 dépendances auditées", c.detail)

    @unittest.skipIf(os.name == "nt", "un script exécutable demande un interpréteur associé sous Windows")
    def test_une_vulnerabilite_est_rapportee_sans_bloquer(self):
        outil = self.faux_outil("open(sortie, 'w').write(json.dumps({'dependencies': [{'name': 'x', 'version': '1', 'vulns': [{'id': 'PYSEC-1'}]}]}))\nsys.exit(1)")
        with dossier_du_pipeline(self.racine):
            c = controles.s4_dependances(self.exigences, outil)
        self.assertEqual((c.ok, c.bloquant), (False, False))
        self.assertIn("PYSEC-1", c.detail)
        self.assertTrue(decision.decider([condition()], [c.en_dict()])[0], "S4 est rapporté, il ne bloque pas (cadrage)")

    @unittest.skipIf(os.name == "nt", "un script exécutable demande un interpréteur associé sous Windows")
    def test_une_panne_de_l_outil_est_non_verifie_et_jamais_reussi(self):
        for corps in ("sys.exit(2)", "open(sortie, 'w').write('pas du json')\nsys.exit(0)", "open(sortie, 'w').write(json.dumps({'dependencies': []}))\nsys.exit(0)"):
            with self.subTest(corps=corps[:20]), dossier_du_pipeline(self.racine):
                c = controles.s4_dependances(self.exigences, self.faux_outil(corps))
                self.assertIsNone(c.ok)

    def test_outil_absent_ou_introuvable_est_non_verifie(self):
        with dossier_du_pipeline(self.racine), mock.patch.dict(os.environ, {}, clear=False), mock.patch("shutil.which", return_value=None):
            os.environ.pop("PIP_AUDIT", None)
            self.assertIsNone(controles.s4_dependances(self.exigences).ok)
            self.assertIsNone(controles.s4_dependances(self.exigences, str(self.racine / "n-existe-pas")).ok)


class TestControleS5(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fiche = Path(self._tmp.name) / "fiche.md"

    def verifier(self, texte, candidat="logistique"):
        self.fiche.write_text(texte, encoding="utf-8")
        return controles.s5_fiche_du_modele(candidat, self.fiche)

    def test_une_fiche_complete_et_relue_passe(self):
        c = self.verifier(FICHE_RELUE)
        self.assertTrue(c.ok, c.detail)
        self.assertIn("Daddy Luciano", c.detail)

    def test_sans_relecture_de_l_autre_membre_la_condition_n_est_pas_remplie(self):
        for ligne in ("**Relue par** : à faire (Daddy Luciano)", "Relue par : non relue", "Relue par :", "Relue par :   "):
            with self.subTest(ligne=ligne):
                c = self.verifier(FICHE_RELUE.replace("**Relue par** : Daddy Luciano, 12/11/2026", ligne))
                self.assertFalse(c.ok)
                self.assertIn("relecture", c.detail)

    def test_pas_de_ligne_de_relecture(self):
        self.assertFalse(self.verifier(FICHE_RELUE.replace("**Relue par** : Daddy Luciano, 12/11/2026", "")).ok)

    def test_une_section_manquante_est_signalee(self):
        c = self.verifier(FICHE_RELUE.replace("## 4. Limites\nx\n", ""))
        self.assertFalse(c.ok)
        self.assertIn("Limites", c.detail)

    def test_la_fiche_doit_nommer_le_candidat(self):
        self.assertFalse(self.verifier(FICHE_RELUE, candidat="gradient").ok)

    def test_fiche_absente(self):
        self.assertFalse(controles.s5_fiche_du_modele("logistique", Path(self._tmp.name) / "absente.md").ok)

    def test_la_fiche_du_depot_a_toutes_ses_sections_et_nomme_le_candidat(self):
        c = controles.s5_fiche_du_modele("logistique")
        self.assertNotIn("sections manquantes", c.detail)
        self.assertNotIn("ne nomme pas", c.detail)
        self.assertFalse(c.detail.startswith("fiche-modele.md absente"))


class TestControlesT1R1(unittest.TestCase):
    def test_t1(self):
        self.assertTrue(controles.t1_code_commite(False, GIT).ok)
        self.assertFalse(controles.t1_code_commite(True, GIT).ok)
        self.assertIsNone(controles.t1_code_commite(None, GIT).ok)
        self.assertIsNone(controles.t1_code_commite(False, None).ok)

    def test_r1_des_metriques_identiques_sont_reproduites(self):
        self.assertTrue(controles.r1_reproduction({"f1": 0.98, "m": {"a": 1}}, {"f1": 0.98, "m": {"a": 1}}).ok)

    def test_r1_une_difference_echoue_et_se_nomme(self):
        c = controles.r1_reproduction({"f1": 0.98, "fausses": 3}, {"f1": 0.98, "fausses": 1})
        self.assertFalse(c.ok)
        self.assertIn("fausses", c.detail)

    def test_r1_une_cle_en_trop_ou_en_moins_echoue(self):
        self.assertFalse(controles.r1_reproduction({"f1": 1}, {"f1": 1, "autre": 2}).ok)
        self.assertFalse(controles.r1_reproduction({"f1": 1, "autre": 2}, {"f1": 1}).ok)

    def test_r1_rien_a_reproduire_est_non_verifie(self):
        self.assertIsNone(controles.r1_reproduction({"f1": 1}, None).ok)

    def test_les_controles_se_serialisent(self):
        for c in (controles.t1_code_commite(False, GIT), controles.r1_reproduction({}, None)):
            json.dumps(c.en_dict())
        self.assertEqual(controles.t1_code_commite(True, GIT).etat, "ÉCHEC")
        self.assertEqual(controles.r1_reproduction({}, None).etat, "non vérifié")


class TestIdentifiant(unittest.TestCase):
    def test_le_run_depend_de_la_selection_et_de_la_revision(self):
        a = etapes.identifiant("logistique", "ab" * 32, GIT, False)
        self.assertEqual(a, "ia05-logistique-abababab-aaaaaaaa")
        self.assertNotEqual(a, etapes.identifiant("logistique", "ab" * 32, "b" * 40, False))
        self.assertTrue(etapes.identifiant("logistique", "ab" * 32, GIT, True).endswith("-modifie"))
        self.assertIn("sans-git", etapes.identifiant("logistique", "ab" * 32, None, False))

    def test_l_identifiant_est_un_run_id_valide(self):
        from registre import documents

        documents.valider_run_id(etapes.identifiant("logistique", "ab" * 32, GIT, True))


class TestAucunReglageAuDeclenchement(unittest.TestCase):
    def test_aucune_fonction_du_pipeline_n_accepte_un_seuil_ni_un_chemin_de_resultat(self):
        for fonction in (etapes.evaluer, etapes.porte, etapes.enregistrer, decision.lire):
            noms = set(inspect.signature(fonction).parameters)
            self.assertFalse(noms & {"seuil", "marge", "borne", "f1", "threshold", "selection", "sortie", "resultat"}, (fonction.__name__, noms))

    def test_la_ligne_de_commande_n_a_que_des_etapes(self):
        sortie = StringIO()
        with redirect_stdout(sortie), self.assertRaises(SystemExit):
            cli.main(["--help"])
        aide = sortie.getvalue()
        self.assertNotIn("--seuil", aide)
        self.assertIn("evaluer", aide)

    def test_les_valeurs_du_cadrage_sont_celles_que_le_pipeline_applique(self):
        self.assertEqual((acceptation.MARGE, acceptation.BORNE_FAUSSES_ALERTES), (0.01, 0.10))


class TestConfigurationFigee(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.racine = Path(self._tmp.name)

    def ecrire(self, choix, resultat_extra=None, sha=None):
        selection = self.racine / "selection.json"
        selection.write_text(json.dumps(choix), encoding="utf-8")
        resultat = {"selection_sha256": sha or sha256(selection.read_bytes()), **(resultat_extra or {})}
        (self.racine / "resultat-test.json").write_text(json.dumps(resultat), encoding="utf-8")

    def configuration(self):
        with chemins(self.racine):
            return etapes.configuration_figee()

    def test_une_selection_dont_l_empreinte_est_celle_du_test_est_acceptee(self):
        self.ecrire({"etape": "validation", "choix": {"candidat": "logistique"}})
        choix, resultat, sha = self.configuration()
        self.assertEqual(sha, resultat["selection_sha256"])

    def test_une_selection_modifiee_apres_le_test_est_refusee(self):
        self.ecrire({"etape": "validation", "choix": {"candidat": "logistique"}}, sha="0" * 64)
        with self.assertRaises(tracabilite.ControleDeSecurite) as e:
            self.configuration()
        self.assertIn("test neuf", str(e.exception))

    def test_sans_candidat_fichiers_absents_ou_illisibles(self):
        self.ecrire({"etape": "validation", "choix": {"candidat": None}})
        with self.assertRaises(tracabilite.ControleDeSecurite):
            self.configuration()
        self.ecrire({"etape": "autre", "choix": {"candidat": "logistique"}})
        with self.assertRaises(tracabilite.ControleDeSecurite):
            self.configuration()
        (self.racine / "selection.json").write_text("pas du json", encoding="utf-8")
        with self.assertRaises(tracabilite.ControleDeSecurite):
            self.configuration()
        (self.racine / "selection.json").unlink()
        with self.assertRaises(tracabilite.ControleDeSecurite):
            self.configuration()

    def test_la_selection_du_depot_est_celle_du_test_enregistre(self):
        """Tant que le dépôt contient les deux fichiers d'IA-03, le pipeline accepte leur configuration."""
        if not (tracabilite.SELECTION.is_file() and tracabilite.RESULTAT_TEST.is_file()):
            self.skipTest("résultats d'IA-03 absents")
        _, resultat, sha = etapes.configuration_figee()
        self.assertEqual(resultat["selection_sha256"], sha)


@unittest.skipUnless(SKLEARN, "scikit-learn absent : python3 scripts/dev/dev.py ml-env")
class TestEtapes(unittest.TestCase):
    """`evaluer`, `porte`, `enregistrer` sur neuf petits runs : la porte ferme, la porte ouvre, rien ne se contourne."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        racine = Path(cls._tmp.name)
        cls.jeu = racine / "jeu"
        cls.catalogue = petit_catalogue()
        construire.construire(cls.jeu, cls.catalogue)
        cls.fichiers = racine / "ia03"
        cls.fichiers.mkdir()
        with chemins(cls.fichiers):
            selection = execution.etape_validation(cls.jeu, message=lambda _: None, catalogue=cls.catalogue)
            selection["choix"].update(candidat="logistique", variante="confirme", params=candidats.LOGISTIQUE.grille[7])  # choix figé : déterministe
            tracabilite.SELECTION.write_text(json.dumps(selection), encoding="utf-8")
            execution.etape_test(cls.jeu, message=lambda _: None, catalogue=cls.catalogue)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.racine = Path(self._t.name)
        self.runs, self.objets = FichierRunStore(self.racine / "runs"), StockageLocal(self.racine / "models")
        empile = contextlib.ExitStack()
        self.addCleanup(empile.close)
        copie = self.racine / "ia03"
        shutil.copytree(self.fichiers, copie)  # chaque test modifie sa propre copie de la sélection et du résultat
        empile.enter_context(chemins(copie, selection="selection.json"))
        empile.enter_context(dossier_du_pipeline(self.racine))
        reel = tracabilite.tracabilite
        empile.enter_context(mock.patch.object(tracabilite, "tracabilite", lambda sha: {**reel(sha), "git_sha": GIT, "code_modifie_non_commite": False}))

    def evaluer(self, **options):
        return etapes.evaluer(dossier_jeu=self.jeu, runs=self.runs, objets=self.objets, message=lambda _: None, audit=False, catalogue=self.catalogue, **options)

    def forcer(self, remplies: bool):
        liste = [acceptation.Condition(f"A{i}", f"condition A{i}", 0.9, ">= 0.5", remplies) for i in range(1, 6)]
        return mock.patch.object(etapes.acceptation, "conditions", return_value=liste)

    def run_id(self):
        return decision.lire()["run_id"]

    def test_evaluer_ecrit_la_decision_le_modele_prepare_et_le_run_sans_rien_enregistrer(self):
        d = self.evaluer()
        self.assertTrue(pipeline.DECISION.is_file())
        self.assertEqual(d["run_id"], etapes.identifiant("logistique", d["selection_sha256"], GIT, False))
        self.assertEqual([c["condition"] for c in d["conditions"]], ["A1", "A2", "A3", "A4", "A5"])
        self.assertEqual([s["code"] for s in d["securite"]], ["S1", "S2", "S3", "S4", "S5", "T1", "R1"])
        self.assertEqual(d["modele_sha256"], sha256(pipeline.MODELE_PREPARE.read_bytes()))
        self.assertEqual(self.runs.obtenir(d["run_id"])["status"], "trained")
        self.assertFalse(self.objets.exists("en-service.json"), "évaluer n'enregistre aucun modèle")
        self.assertEqual(self.runs.obtenir(d["run_id"])["metrics"]["decision"], d["decision"])

    def test_les_controles_de_la_chaine_sont_verifies_sur_le_petit_jeu(self):
        d = self.evaluer()
        etat = {s["code"]: s["ok"] for s in d["securite"]}
        self.assertEqual({k: etat[k] for k in ("S1", "S2", "S3", "S5", "T1")}, {"S1": True, "S2": True, "S3": True, "S5": True, "T1": True})
        self.assertIsNone(etat["S4"], "audit désactivé : non vérifié")
        self.assertTrue(etat["R1"], "les métriques refaites sont celles du test enregistré")

    def test_la_porte_se_ferme_sous_le_seuil_ecrit_la_trace_rejetee_et_aucun_fichier(self):
        with self.forcer(False):
            self.evaluer()
        self.assertFalse(etapes.porte(runs=self.runs, objets=self.objets, message=lambda _: None))
        run = self.runs.obtenir(self.run_id())
        self.assertEqual(run["status"], "rejected")
        self.assertIn("A1 manquée", run["reason"])
        self.assertNotIn("model_sha256", run)
        self.assertFalse(self.objets.exists(f"{run['run_id']}/modele.json"))
        self.assertFalse(self.objets.exists("en-service.json"))
        self.assertIn("non enregistré", pipeline.RAPPORT_MD.read_text(encoding="utf-8"))

    def test_enregistrer_refuse_apres_une_porte_fermee_meme_appele_directement(self):
        with self.forcer(False):
            self.evaluer()
        etapes.porte(runs=self.runs, objets=self.objets, message=lambda _: None)
        with self.assertRaises(decision.Bloque):
            etapes.enregistrer(runs=self.runs, objets=self.objets, message=lambda _: None)
        self.assertFalse(self.objets.exists("en-service.json"))

    def test_la_porte_s_ouvre_et_le_modele_est_enregistre_en_service(self):
        with self.forcer(True):
            self.evaluer()
        self.assertTrue(etapes.porte(runs=self.runs, objets=self.objets, message=lambda _: None))
        run = etapes.enregistrer(runs=self.runs, objets=self.objets, message=lambda _: None)
        self.assertEqual(run["status"], "registered")
        self.assertEqual(run["model_sha256"], decision.lire()["modele_sha256"])
        self.assertEqual(self.runs.dernier_en_service()["run_id"], run["run_id"])
        from registre import service

        self.assertEqual(service.charger_le_modele_en_service(self.objets).run_id, run["run_id"])

    def test_une_decision_gonflee_entre_les_etapes_est_refusee(self):
        with self.forcer(False):
            self.evaluer()
        contenu = json.loads(pipeline.DECISION.read_text(encoding="utf-8"))
        contenu["decision"] = "accepté"
        pipeline.DECISION.write_text(json.dumps(contenu), encoding="utf-8")
        for etape in (etapes.porte, etapes.enregistrer):
            with self.subTest(etape=etape.__name__), self.assertRaises(decision.DecisionIncoherente):
                etape(runs=self.runs, objets=self.objets, message=lambda _: None)
        self.assertFalse(self.objets.exists("en-service.json"))

    def test_un_modele_remplace_entre_les_etapes_est_refuse(self):
        with self.forcer(True):
            self.evaluer()
        etapes.porte(runs=self.runs, objets=self.objets, message=lambda _: None)
        pipeline.MODELE_PREPARE.write_bytes(octets_de_modele(intercepts=[9.0, 0.0, 0.0]))
        with self.assertRaises(tracabilite.ControleDeSecurite) as e:
            etapes.enregistrer(runs=self.runs, objets=self.objets, message=lambda _: None)
        self.assertIn("empreinte", str(e.exception))
        self.assertFalse(self.objets.exists("en-service.json"))

    def test_sans_modele_prepare_rien_n_est_enregistre(self):
        with self.forcer(True):
            self.evaluer()
        pipeline.MODELE_PREPARE.unlink()
        with self.assertRaises(tracabilite.ControleDeSecurite):
            etapes.enregistrer(runs=self.runs, objets=self.objets, message=lambda _: None)

    def test_un_bon_score_ne_rachete_pas_une_fiche_non_relue(self):
        for nom in ("fiche-modele.md",):
            (self.racine / "docs" / nom).write_text(FICHE_RELUE.replace("Daddy Luciano, 12/11/2026", "à faire"), encoding="utf-8")
        with self.forcer(True):
            d = self.evaluer()
        self.assertEqual(d["decision"], "rejeté")
        self.assertIn("S5 en échec", " ".join(d["raisons"]))
        self.assertFalse(etapes.porte(runs=self.runs, objets=self.objets, message=lambda _: None))

    def test_un_code_non_commite_ne_s_enregistre_pas(self):
        reel = tracabilite.tracabilite
        with mock.patch.object(tracabilite, "tracabilite", lambda sha: {**reel(sha), "git_sha": GIT, "code_modifie_non_commite": True}), self.forcer(True):
            d = self.evaluer()
        self.assertEqual(d["decision"], "rejeté")
        self.assertTrue(d["run_id"].endswith("-modifie"))
        self.assertIn("T1 en échec", " ".join(d["raisons"]))

    def test_un_candidat_sans_format_sur_ne_s_enregistre_pas_meme_avec_un_score_parfait(self):
        choix = json.loads(tracabilite.SELECTION.read_text(encoding="utf-8"))
        choix["choix"].update(candidat="gradient", variante="brut", params=candidats.GRADIENT.grille[0])
        tracabilite.SELECTION.write_text(json.dumps(choix), encoding="utf-8")
        resultat = json.loads(tracabilite.RESULTAT_TEST.read_text(encoding="utf-8"))
        resultat["selection_sha256"] = sha256(tracabilite.SELECTION.read_bytes())
        tracabilite.RESULTAT_TEST.write_text(json.dumps(resultat), encoding="utf-8")
        with self.forcer(True):
            d = self.evaluer()
        etat = {s["code"]: s["ok"] for s in d["securite"]}
        self.assertFalse(etat["S3"])
        self.assertFalse(etat["S2"])
        self.assertEqual(d["decision"], "rejeté")
        self.assertIsNone(d["modele_sha256"])
        self.assertFalse(pipeline.MODELE_PREPARE.exists())

    def test_une_metrique_non_reproduite_ferme_la_porte(self):
        resultat = json.loads(tracabilite.RESULTAT_TEST.read_text(encoding="utf-8"))
        resultat["modele"]["f1_macro"] = round(resultat["modele"]["f1_macro"] - 0.0123, 4)
        tracabilite.RESULTAT_TEST.write_text(json.dumps(resultat), encoding="utf-8")
        with self.forcer(True):
            d = self.evaluer()
        self.assertFalse({s["code"]: s["ok"] for s in d["securite"]}["R1"])
        self.assertEqual(d["decision"], "rejeté")

    def test_un_jeu_modifie_arrete_tout_avant_la_lecture_du_test(self):
        abime = self.racine / "jeu-abime"
        shutil.copytree(self.jeu, abime)
        octets = bytearray((abime / "train.parquet").read_bytes())
        octets[300] ^= 0xFF
        (abime / "train.parquet").write_bytes(bytes(octets))
        lus = []
        reel = donnees.charger

        def espion(ensemble, *a, **k):
            lus.append(ensemble)
            return reel(ensemble, *a, **k)

        with mock.patch.object(donnees, "charger", espion), self.assertRaises(tracabilite.ControleDeSecurite) as e:
            etapes.evaluer(dossier_jeu=abime, runs=self.runs, objets=self.objets, message=lambda _: None, audit=False, catalogue=self.catalogue)
        self.assertIn("S1", str(e.exception))
        self.assertEqual(lus, [], "ni l'entraînement ni le test ne sont lus d'un jeu douteux")
        self.assertFalse(pipeline.DECISION.exists())

    def test_une_selection_modifiee_depuis_le_test_arrete_l_evaluation(self):
        choix = json.loads(tracabilite.SELECTION.read_text(encoding="utf-8"))
        choix["choix"]["params"] = {"C": 0.01, "class_weight": None}  # un autre réglage : il faudrait un nouveau test
        tracabilite.SELECTION.write_text(json.dumps(choix), encoding="utf-8")
        with self.assertRaises(tracabilite.ControleDeSecurite):
            self.evaluer()

    def test_refaire_evaluer_ne_reecrit_pas_le_run_deja_au_registre(self):
        d = self.evaluer()
        run = self.runs.obtenir(d["run_id"])
        self.evaluer()
        self.assertEqual(self.runs.obtenir(d["run_id"]), run)
        self.assertEqual(len(self.runs.lister()), 1)

    def test_le_rapport_dit_les_raisons_de_la_porte_fermee(self):
        with self.forcer(False):
            d = self.evaluer()
        texte = decision.rapport(decision.lire())
        for morceau in ("non enregistré", "Pourquoi la porte est fermée", "A1 manquée", d["run_id"], "Contrôles de sécurité", d["tracabilite"]["dataset_sha256"]):
            self.assertIn(morceau, texte)

    def test_le_rapport_d_un_modele_accepte_n_a_pas_de_section_de_refus(self):
        with self.forcer(True):
            self.evaluer()
        texte = decision.rapport(decision.lire())
        self.assertIn("modèle accepté", texte)
        self.assertNotIn("Pourquoi la porte est fermée", texte)


class TestLigneDeCommande(unittest.TestCase):
    def appeler(self, *argv, **remplacements):
        sortie, erreur = StringIO(), StringIO()
        with redirect_stdout(sortie), redirect_stderr(erreur), \
                mock.patch.object(cli, "magasins", return_value=(MemoireRunStore(), mock.Mock())):
            with contextlib.ExitStack() as pile:
                for nom, valeur in remplacements.items():
                    pile.enter_context(mock.patch.object(etapes, nom, valeur))
                code = cli.main(list(argv))
        return code, sortie.getvalue(), erreur.getvalue()

    def test_tout_enchaine_les_trois_etapes_et_rend_zero(self):
        appels = []
        code, _, _ = self.appeler("tout", evaluer=lambda **k: appels.append("evaluer"), porte=lambda **k: appels.append("porte") or True,
                                  enregistrer=lambda **k: appels.append("enregistrer"))
        self.assertEqual((code, appels), (0, ["evaluer", "porte", "enregistrer"]))

    def test_la_porte_fermee_rend_1_et_n_enregistre_pas(self):
        appels = []
        code, _, _ = self.appeler("tout", evaluer=lambda **k: appels.append("evaluer"), porte=lambda **k: False, enregistrer=lambda **k: appels.append("enregistrer"))
        self.assertEqual((code, appels), (1, ["evaluer"]))

    def test_chaque_etape_seule(self):
        appels = []
        for etape in ("evaluer", "porte", "enregistrer"):
            self.appeler(etape, evaluer=lambda **k: appels.append("evaluer"), porte=lambda **k: appels.append("porte") or True,
                         enregistrer=lambda **k: appels.append("enregistrer"))
        self.assertEqual(appels, ["evaluer", "porte", "enregistrer"])

    def test_enregistrer_bloque_rend_1(self):
        def bloque(**_k):
            raise decision.Bloque("sous le seuil")

        code, _, erreur = self.appeler("enregistrer", enregistrer=bloque)
        self.assertEqual(code, 1)
        self.assertIn("Porte fermée", erreur)

    def test_un_controle_de_securite_refuse_rend_3(self):
        def refuse(**_k):
            raise tracabilite.ControleDeSecurite("jeu modifié")

        code, _, erreur = self.appeler("evaluer", evaluer=refuse)
        self.assertEqual((code, "Refusé" in erreur), (3, True))

    def test_une_decision_incoherente_rend_3(self):
        def incoherente(**_k):
            raise decision.DecisionIncoherente("fichier modifié")

        self.assertEqual(self.appeler("porte", porte=incoherente)[0], 3)

    def test_scikit_learn_absent_ou_fichier_manquant_rend_2(self):
        def sans_sklearn(**_k):
            raise candidats.SklearnAbsent("absent")

        def sans_fichier(**_k):
            raise FileNotFoundError("selection.json")

        self.assertEqual(self.appeler("evaluer", evaluer=sans_sklearn)[0], 2)
        self.assertEqual(self.appeler("evaluer", evaluer=sans_fichier)[0], 2)

    def test_le_registre_est_un_dossier_sans_mongodb_et_mongodb_avec_son_adresse(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MONGO_URL", None)
            runs, objets = cli.magasins()
        self.assertIsInstance(runs, FichierRunStore)
        self.assertIsInstance(objets, StockageLocal)
        with mock.patch.dict(os.environ, {"MONGO_URL": "mongodb://x"}), \
                mock.patch.object(cli.MongoRunStore, "depuis_l_adresse", return_value=MemoireRunStore()) as fabrique:
            runs, _ = cli.magasins()
        fabrique.assert_called_once_with("mongodb://x")

    def test_un_adaptateur_de_stockage_inconnu_est_une_erreur_de_configuration(self):
        erreur = StringIO()
        with mock.patch.dict(os.environ, {"STORAGE_BACKEND": "s3"}), redirect_stderr(erreur):
            os.environ.pop("MONGO_URL", None)
            code = cli.main(["evaluer"])  # `magasins` n'est pas remplacé : c'est lui qu'on essaie
        self.assertEqual(code, 2)
        self.assertIn("S3 est documenté, non exécuté", erreur.getvalue())

    def test_la_connexion_est_fermee(self):
        runs = mock.Mock()
        with mock.patch.object(cli, "magasins", return_value=(runs, mock.Mock())), mock.patch.object(etapes, "evaluer"), redirect_stdout(StringIO()):
            cli.main(["evaluer"])
        runs.fermer.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
