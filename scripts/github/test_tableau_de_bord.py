"""Tableau de bord de pilotage (GES-11) : les trois indicateurs, la distinction « zéro » et « non mesuré », la lecture de GitHub.

Aucun accès réseau : GitHub est remplacé par un faux (`FauxGitHub`) ou par un faux `urlopen`. Les tests sur les vrais fichiers du
dépôt vérifient que le calcul relit bien les documents tels qu'ils sont écrits aujourd'hui.
Lancement : python3 -m unittest discover -s scripts/github -p "test_tableau_de_bord.py"  (Windows : py -3 ...).
"""

import io
import json
import re
import sys
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True  # un fichier .pyc de ce dossier est suivi par Git : ne pas le réécrire

import tableau_de_bord as t  # noqa: E402

RACINE = Path(__file__).resolve().parents[2]
AUJOURDHUI = date(2026, 11, 20)

EXIGENCES = """| ID | Exigence | Critère | Priorité | Preuve | État | Issues |
|---|---|---|---|---|---|---|
| EXG-COL-01 | **Simulateur.** Contexte | Critère | **Doit** | preuve | Prouvé | MS-07 |
| EXG-COL-02 | Validation | Critère | **Doit** | preuve | Prouvé : détail daté du 03/11 | MS-08 |
| EXG-TRA-01 | Fenêtres | Critère | **Devrait** | preuve | Partiel : il manque le rejeu | BE-06 |
| EXG-ALE-01 | Alertes | Critère | **Pourrait** | preuve | À faire | MS-11 |
"""
RISQUES = """| ID | Risque | Cause | Effet | Responsable | Action | Signal | Statut |
|---|---|---|---|---|---|---|---|
| R1 | Retard | Charge | Retard | Les deux | Prototypes | Planning | Ouvert |
| R2 | Données | Jeu | Rejet | Daddy | Jeu ouvert | Taux | Suspendu (C-05) : aucune ressource |
| R3 | Coûts | Cloud | Dépassement | Manoa | Arrêt | Alertes | Clos le 2026-11-10 |
| R11 et R12 | Ajoutés le 27/10/2026 avec la révision de l'ADR-008 |
"""


def issue(numero, etat="closed", jalon=1, preuve="docs/a.md", etiquettes=(), pr=False, titre=None):
    corps = f"## Tâches\n- [ ] x\n\n## Preuve attendue\n{preuve}\n\n<sub>Réf.</sub>" if preuve is not None else "## Tâches\n- [ ] x"
    donnees = {"number": numero, "title": titre or f"[X-{numero}] titre", "state": etat, "body": corps,
               "milestone": {"number": jalon} if jalon else None, "labels": [{"name": n} for n in etiquettes]}
    if pr:
        donnees["pull_request"] = {}
    return donnees


JALONS = [{"number": 1, "title": "M1 · Socle", "due_on": "2026-11-01T00:00:00Z"},
          {"number": 2, "title": "M2 · Données", "due_on": "2026-12-15T00:00:00Z"},
          {"number": 3, "title": "M3 · Vide", "due_on": None}]


class FauxGitHub:
    depot, ref = "x/y", "main"

    def __init__(self, issues=(), jalons=JALONS, arbre=("docs/a.md", "docs/b/c.md"), fichiers=None, en_panne=()):
        self._issues, self._jalons, self._arbre = list(issues), list(jalons), set(arbre)
        self._fichiers = fichiers if fichiers is not None else {t.EXIGENCES: EXIGENCES, t.RISQUES: RISQUES}
        self.en_panne = set(en_panne)

    def _verifier(self, nom):
        if nom in self.en_panne:
            raise t.ErreurSource(f"{nom} : HTTP 500")

    def issues(self):
        self._verifier("issues")
        return self._issues

    def jalons(self):
        self._verifier("jalons")
        return self._jalons

    def arbre(self):
        self._verifier("arbre")
        return self._arbre

    def fichier(self, chemin):
        self._verifier(chemin)
        if chemin not in self._fichiers:
            raise t.ErreurSource(f"{chemin} : HTTP 404")
        return self._fichiers[chemin]


class Exigences(unittest.TestCase):
    def test_les_etats_sont_comptes_par_leur_premier_mot(self):
        e = t.exigences(EXIGENCES)
        self.assertEqual(e["par_etat"], {"Prouvé": 2, "Partiel": 1, "À faire": 1})
        self.assertEqual((e["verifiees"]["valeur"], e["verifiees"]["sur"]), (2, 4))
        self.assertEqual(e["verifiees"]["pourcentage"], 50.0)
        self.assertEqual(e["par_priorite"]["Doit"], {"Prouvé": 2, "Partiel": 0, "À faire": 0})
        self.assertEqual(e["par_domaine"]["TRA"]["Partiel"], 1)

    def test_aucune_exigence_prouvee_est_un_zero_mesure(self):
        texte = EXIGENCES.replace("| Prouvé", "| À faire").replace("| Prouvé :", "| À faire :")
        v = t.exigences(texte)["verifiees"]
        self.assertTrue(v["mesure"])
        self.assertEqual((v["valeur"], v["sur"], v["pourcentage"]), (0, 4, 0.0))

    def test_un_etat_illisible_n_est_ni_prouve_ni_compte(self):
        texte = EXIGENCES + "| EXG-API-01 | API | Critère | **Doit** | preuve | à voir | BE-01 |\n"
        e = t.exigences(texte)
        self.assertEqual(e["illisibles"], ["EXG-API-01"])
        self.assertEqual(e["verifiees"]["sur"], 4, "l'exigence illisible n'est pas dans le dénominateur")
        self.assertEqual(e["verifiees"]["total_lignes"], 5)

    def test_un_document_sans_tableau_est_non_mesure_et_non_zero(self):
        for texte in ("", "# Titre\n\nrien\n"):
            v = t.exigences(texte)["verifiees"]
            self.assertFalse(v["mesure"])
            self.assertIsNone(v["valeur"])
            self.assertIn("aucune exigence", v["raison"])

    def test_tous_les_etats_illisibles_donnent_non_mesure(self):
        texte = "| EXG-COL-01 | a | b | **Doit** | p | ??? | I |\n"
        self.assertFalse(t.exigences(texte)["verifiees"]["mesure"])


class Risques(unittest.TestCase):
    def test_un_risque_est_traite_quand_il_est_clos_et_pas_quand_il_est_suspendu(self):
        r = t.risques(RISQUES)
        self.assertEqual(r["par_statut"], {"Ouvert": 1, "Suspendu": 1, "Clos": 1})
        self.assertEqual((r["traites"]["valeur"], r["traites"]["sur"]), (1, 3))

    def test_la_ligne_de_note_n_est_pas_un_risque(self):
        self.assertEqual(t.risques(RISQUES)["traites"]["total_lignes"], 3)

    def test_aucun_risque_clos_est_un_zero_mesure(self):
        r = t.risques(RISQUES.replace("Clos le 2026-11-10", "Ouvert"))
        self.assertTrue(r["traites"]["mesure"])
        self.assertEqual((r["traites"]["valeur"], r["traites"]["sur"]), (0, 3))

    def test_un_registre_vide_est_non_mesure(self):
        r = t.risques("| ID | Risque |\n|---|---|\n")
        self.assertFalse(r["traites"]["mesure"])

    def test_un_risque_sans_responsable_ou_sans_action_est_signale(self):
        r = t.risques(RISQUES + "| R9 | Sans | c | e |  |  | s | Ouvert |\n")
        self.assertEqual(r["incomplets"], ["R9"])

    def test_un_statut_inconnu_n_est_pas_compte(self):
        r = t.risques(RISQUES + "| R9 | Flou | c | e | Daddy | a | s | Voir ailleurs |\n")
        self.assertEqual(r["illisibles"], ["R9"])
        self.assertEqual(r["traites"]["sur"], 3)


class Preuves(unittest.TestCase):
    ARBRE = {"docs/a.md", "docs/b/c.md", "ml/evaluation/x.json"}

    def test_les_chemins_sont_lus_dans_la_section_preuve(self):
        self.assertEqual(t.preuves_citees(issue(1, preuve="`docs/a.md` et ml/evaluation/.")["body"]), ["docs/a.md", "ml/evaluation/"])

    def test_une_preuve_sans_chemin_n_est_pas_verifiable(self):
        for preuve in ("sortie du plan", "Capture d'écran du tableau de bord", "Rapport .md"):
            self.assertEqual(t.classer_preuve(issue(1, preuve=preuve)["body"], self.ARBRE), "non_verifiable", preuve)

    def test_une_issue_sans_section_preuve_n_est_pas_verifiable(self):
        self.assertEqual(t.classer_preuve(issue(1, preuve=None)["body"], self.ARBRE), "non_verifiable")
        self.assertEqual(t.classer_preuve(None, self.ARBRE), "non_verifiable")

    def test_fichier_dossier_et_motif(self):
        for preuve in ("docs/a.md", "docs/b/", "ml/evaluation/*.json"):
            self.assertEqual(t.classer_preuve(issue(1, preuve=preuve)["body"], self.ARBRE), "versionnee", preuve)

    def test_partielle_et_absente(self):
        self.assertEqual(t.classer_preuve(issue(1, preuve="docs/a.md et docs/nulle.md")["body"], self.ARBRE), "partielle")
        self.assertEqual(t.classer_preuve(issue(1, preuve="docs/nulle.md")["body"], self.ARBRE), "absente")

    def test_un_nom_de_dossier_n_est_pas_un_prefixe_de_texte(self):
        self.assertFalse(t.preuve_existe("docs/b", {"docs/bb/c.md"}))

    def test_un_arbre_inconnu_rend_la_preuve_non_verifiable_et_non_absente(self):
        self.assertEqual(t.classer_preuve(issue(1, preuve="docs/nulle.md")["body"], None), "non_verifiable")


class Livrables(unittest.TestCase):
    def calculer(self, issues, arbre=("docs/a.md",)):
        return t.livrables(JALONS, issues, set(arbre) if arbre is not None else None, AUJOURDHUI)

    def test_les_issues_sont_comptees_par_jalon(self):
        lv = self.calculer([issue(1), issue(2, "open"), issue(3, jalon=2, preuve="docs/nulle.md")])
        m1, m2 = lv["jalons"][0], lv["jalons"][1]
        self.assertEqual((m1["issues"], m1["fermees"], m1["ouvertes"]), (2, 1, 1))
        self.assertEqual(m1["avancement"]["pourcentage"], 50.0)
        self.assertEqual((m2["issues"], m2["fermees"]), (1, 1))
        self.assertEqual(m2["preuves"]["absente"], 1)
        self.assertEqual(lv["global"]["valeur"], 2)
        self.assertEqual(lv["global"]["sur"], 3)

    def test_un_jalon_sans_issue_est_non_mesure_et_pas_a_zero_pour_cent(self):
        vide = self.calculer([issue(1)])["jalons"][2]
        self.assertFalse(vide["avancement"]["mesure"])
        self.assertIsNone(vide["avancement"]["pourcentage"])
        self.assertEqual(vide["issues"], 0)

    def test_un_jalon_dont_rien_n_est_ferme_est_un_zero_mesure(self):
        m = self.calculer([issue(1, "open"), issue(2, "open")])["jalons"][0]
        self.assertTrue(m["avancement"]["mesure"])
        self.assertEqual((m["avancement"]["valeur"], m["avancement"]["pourcentage"]), (0, 0.0))

    def test_le_retard_ne_vaut_que_pour_une_echeance_passee_avec_des_issues_ouvertes(self):
        lv = self.calculer([issue(1, "open"), issue(2, jalon=2, etat="open")])
        self.assertTrue(lv["jalons"][0]["en_retard"])
        self.assertFalse(lv["jalons"][1]["en_retard"], "échéance du 15/12 : pas encore passée")
        self.assertFalse(self.calculer([issue(1)])["jalons"][0]["en_retard"], "tout est fermé")
        self.assertFalse(lv["jalons"][2]["en_retard"], "pas d'échéance")

    def test_les_p0_ouvertes_sont_listees(self):
        lv = self.calculer([issue(7, "open", etiquettes=("prio:P0",)), issue(8, "open", etiquettes=("prio:P1",)), issue(9, "closed", etiquettes=("prio:P0",))])
        self.assertEqual(lv["jalons"][0]["ouvertes_p0"], [7])

    def test_les_preuves_introuvables_sont_nommees(self):
        lv = self.calculer([issue(5, preuve="docs/nulle.md et docs/a.md", titre="[BE-05] Endpoints")])
        self.assertEqual(lv["preuves_introuvables"], [{"issue": 5, "titre": "[BE-05] Endpoints", "jalon": "M1 · Socle", "chemins": ["docs/nulle.md"]}])

    def test_sans_arbre_aucune_preuve_n_est_dite_absente(self):
        lv = self.calculer([issue(1, preuve="docs/nulle.md")], arbre=None)
        self.assertFalse(lv["preuves_verifiees"])
        self.assertEqual(lv["jalons"][0]["preuves"]["absente"], 0)
        self.assertEqual(lv["preuves_introuvables"], [])

    def test_une_issue_sans_jalon_est_comptee_a_part(self):
        self.assertEqual(self.calculer([issue(1, jalon=None)])["sans_jalon"], 1)


class Calcul(unittest.TestCase):
    def calculer(self, **options):
        return t.calculer(FauxGitHub(**options.pop("source", {})), aujourdhui=AUJOURDHUI, **options)

    def test_trois_indicateurs_sont_calcules_depuis_la_source(self):
        r = t.calculer(FauxGitHub(issues=[issue(1), issue(2, "open")]), aujourdhui=AUJOURDHUI)
        self.assertEqual(r["exigences"]["verifiees"]["valeur"], 2)
        self.assertEqual(r["risques"]["traites"]["valeur"], 1)
        self.assertEqual(r["livrables"]["global"]["sur"], 2)
        self.assertEqual(r["erreurs"], {})

    def test_une_source_en_panne_donne_non_mesure_jamais_zero(self):
        r = t.calculer(FauxGitHub(en_panne=(t.EXIGENCES, t.RISQUES, "issues")), aujourdhui=AUJOURDHUI)
        for m in (r["exigences"]["verifiees"], r["risques"]["traites"], r["livrables"]["global"]):
            self.assertFalse(m["mesure"])
            self.assertIsNone(m["valeur"])
            self.assertIn("HTTP 500", m["raison"])
        self.assertEqual(set(r["erreurs"]), {t.EXIGENCES, t.RISQUES, "issues"})

    def test_un_fichier_introuvable_n_arrete_pas_les_autres_indicateurs(self):
        r = t.calculer(FauxGitHub(issues=[issue(1)], fichiers={t.EXIGENCES: EXIGENCES}), aujourdhui=AUJOURDHUI)
        self.assertTrue(r["exigences"]["verifiees"]["mesure"])
        self.assertFalse(r["risques"]["traites"]["mesure"])
        self.assertTrue(r["livrables"]["global"]["mesure"])

    def test_un_arbre_illisible_garde_l_avancement_et_ote_les_preuves(self):
        r = t.calculer(FauxGitHub(issues=[issue(1)], en_panne=("arbre",)), aujourdhui=AUJOURDHUI)
        self.assertTrue(r["livrables"]["global"]["mesure"])
        self.assertFalse(r["livrables"]["preuves_verifiees"])
        self.assertIn("arbre", r["erreurs"])

    def test_les_fichiers_locaux_sont_lus_dans_la_copie_de_travail(self):
        with tempfile.TemporaryDirectory() as dossier:
            for chemin, texte in ((t.EXIGENCES, EXIGENCES), (t.RISQUES, RISQUES.replace("Clos le 2026-11-10", "Ouvert"))):
                cible = Path(dossier) / chemin
                cible.parent.mkdir(parents=True, exist_ok=True)
                cible.write_text(texte, encoding="utf-8")
            r = t.calculer(FauxGitHub(issues=[issue(1)], fichiers={}), fichiers_locaux=True, aujourdhui=AUJOURDHUI, racine=Path(dossier))
        self.assertEqual(r["ref"], "copie de travail")
        self.assertEqual(r["exigences"]["verifiees"]["valeur"], 2)
        self.assertEqual(r["risques"]["traites"]["valeur"], 0)

    def test_un_fichier_local_absent_est_non_mesure(self):
        with tempfile.TemporaryDirectory() as dossier:
            r = t.calculer(FauxGitHub(issues=[issue(1)]), fichiers_locaux=True, aujourdhui=AUJOURDHUI, racine=Path(dossier))
        self.assertFalse(r["exigences"]["verifiees"]["mesure"])
        self.assertIn(t.EXIGENCES, r["erreurs"])


class Presentation(unittest.TestCase):
    def rendre(self, **source):
        return t.markdown(t.calculer(FauxGitHub(**source), aujourdhui=AUJOURDHUI))

    def test_un_zero_et_un_non_mesure_se_lisent_differemment(self):
        zero = self.rendre(issues=[issue(1, "open")], fichiers={t.EXIGENCES: EXIGENCES, t.RISQUES: RISQUES.replace("Clos le 2026-11-10", "Ouvert")})
        self.assertIn("0 sur 3 (0,0 %)", zero)
        absent = self.rendre(issues=[issue(1)], fichiers={t.EXIGENCES: EXIGENCES})
        self.assertIn("**non mesuré**", absent)
        self.assertIn(t.RISQUES, absent, "la source en défaut est nommée")

    def test_un_jalon_vide_et_une_absence_de_preuve_sont_dits_non_mesures(self):
        texte = self.rendre(issues=[issue(1, "open")])
        self.assertIn("aucune issue dans ce jalon", texte)
        self.assertIn("non mesuré (aucune issue fermée)", texte)

    def test_le_tableau_dit_la_revision_lue(self):
        self.assertIn("fichiers lus à : **main**", self.rendre(issues=[issue(1)]))

    def test_le_json_est_serialisable(self):
        json.dumps(t.calculer(FauxGitHub(issues=[issue(1)]), aujourdhui=AUJOURDHUI))


class MiseAJour(unittest.TestCase):
    def test_seul_le_bloc_entre_les_reperes_change(self):
        with tempfile.TemporaryDirectory() as dossier:
            document = Path(dossier) / "d.md"
            document.write_text(f"avant é\n{t.DEBUT}\nancien\n{t.FIN}\naprès\n", encoding="utf-8", newline="\n")
            t.mettre_a_jour(document, "nouveau\n")
            octets = document.read_bytes()
        self.assertEqual(octets.decode("utf-8"), f"avant é\n{t.DEBUT}\nnouveau\n{t.FIN}\naprès\n")
        self.assertNotIn(b"\r", octets)

    def test_sans_reperes_rien_n_est_ecrit(self):
        with tempfile.TemporaryDirectory() as dossier:
            document = Path(dossier) / "d.md"
            document.write_text("rien\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                t.mettre_a_jour(document, "x\n")
            self.assertEqual(document.read_text(encoding="utf-8"), "rien\n")


class Reponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class LectureDeGitHub(unittest.TestCase):
    def github(self, reponses, jeton=None):
        appels = []

        def ouvrir(requete, timeout=None):
            appels.append(requete)
            reponse = reponses(requete.full_url)
            if isinstance(reponse, Exception):
                raise reponse
            return Reponse(json.dumps(reponse).encode() if not isinstance(reponse, bytes) else reponse)

        return t.GitHub("x/y", "main", jeton, ouvrir), appels

    def test_les_pull_requests_ne_sont_pas_des_livrables(self):
        g, _ = self.github(lambda url: [issue(1), issue(2, pr=True)])
        self.assertEqual([i["number"] for i in g.issues()], [1])

    def test_la_pagination_suit_les_pages_pleines(self):
        pages = {1: [issue(n) for n in range(100)], 2: [issue(n) for n in range(100, 130)]}
        g, appels = self.github(lambda url: pages[int(re.search(r"[?&]page=(\d+)", url).group(1))])
        self.assertEqual(len(g.issues()), 130)
        self.assertEqual(len(appels), 2)

    def test_la_limite_d_appels_est_dite_sans_afficher_le_jeton(self):
        erreur = urllib.error.HTTPError("https://api.github.com/x", 403, "rate", {}, None)
        g, _ = self.github(lambda url: erreur, jeton="ghp_secret_de_test")
        with self.assertRaises(t.ErreurSource) as ctx:
            g.jalons()
        self.assertIn("limite d'appels", str(ctx.exception))
        self.assertNotIn("ghp_secret_de_test", str(ctx.exception))

    def test_le_jeton_part_en_en_tete_et_pas_dans_l_adresse(self):
        g, appels = self.github(lambda url: [], jeton="ghp_secret_de_test")
        g.jalons()
        self.assertEqual(appels[0].get_header("Authorization"), "Bearer ghp_secret_de_test")
        self.assertNotIn("ghp_secret_de_test", appels[0].full_url)

    def test_sans_jeton_aucun_en_tete_d_autorisation(self):
        g, appels = self.github(lambda url: [])
        g.jalons()
        self.assertIsNone(appels[0].get_header("Authorization"))

    def test_un_reseau_coupe_est_une_erreur_de_source(self):
        g, _ = self.github(lambda url: urllib.error.URLError("hors ligne"))
        with self.assertRaises(t.ErreurSource):
            g.jalons()

    def test_une_reponse_illisible_est_une_erreur_de_source(self):
        g, _ = self.github(lambda url: b"<html>")
        with self.assertRaises(t.ErreurSource):
            g.jalons()

    def test_un_arbre_tronque_n_est_pas_utilise(self):
        g, _ = self.github(lambda url: {"truncated": True, "tree": []})
        with self.assertRaises(t.ErreurSource):
            g.arbre()

    def test_l_arbre_ne_garde_que_les_fichiers(self):
        g, _ = self.github(lambda url: {"truncated": False, "tree": [{"path": "docs", "type": "tree"}, {"path": "docs/a.md", "type": "blob"}]})
        self.assertEqual(g.arbre(), {"docs/a.md"})

    def test_la_revision_est_encodee_dans_l_adresse(self):
        g, appels = self.github(lambda url: b"texte")
        g.ref = "feature/x y"
        g.fichier("docs/a.md")
        self.assertIn("feature%2Fx%20y", appels[0].full_url)


class DocumentsDuDepot(unittest.TestCase):
    """Le calcul relit les vrais documents tels qu'ils sont écrits ; un changement de format fait échouer ces tests."""

    def test_le_bilan_chiffre_de_exigences_md_est_retrouve(self):
        texte = (RACINE / t.EXIGENCES).read_text(encoding="utf-8")
        e = t.exigences(texte)
        bilan = re.search(r"\| Prouvé / Partiel / À faire \| (\d+) / (\d+) / (\d+) \|", texte)
        self.assertEqual([e["par_etat"][k] for k in t.ETATS_EXIGENCE], [int(x) for x in bilan.groups()])
        self.assertEqual(e["illisibles"], [])

    def test_le_registre_des_risques_est_lu_en_entier(self):
        texte = (RACINE / t.RISQUES).read_text(encoding="utf-8")
        r = t.risques(texte)
        lignes = len(re.findall(r"(?m)^\| R\d+ \|", texte))
        self.assertEqual(r["traites"]["total_lignes"], lignes)
        self.assertEqual(r["illisibles"], [], "chaque risque a un statut lisible")
        self.assertEqual(r["incomplets"], [])

    def test_le_document_du_tableau_de_bord_a_ses_reperes_et_ses_sources(self):
        texte = t.DOCUMENT.read_text(encoding="utf-8")
        self.assertLess(texte.index(t.DEBUT), texte.index(t.FIN))
        for attendu in ("exigences.md", "registre-risques.md", "milestones", "non mesuré", "tableau_de_bord.py", "GITHUB_TOKEN"):
            self.assertIn(attendu, texte)


if __name__ == "__main__":
    unittest.main()
