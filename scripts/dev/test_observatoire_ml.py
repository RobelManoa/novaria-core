"""La chaîne d'entraînement en schéma vivant (onglet « Entraînement » de l'observatoire) : ce que la carte lit, ce qu'elle dit
quand un fichier manque, et le rejeu en direct. Aucun Docker, aucune commande réelle.
Lancement : python3 -m unittest discover -s scripts/dev -p "test_observatoire_ml.py"  (Windows : py -3 ...).
"""

import io
import json
import re
import tempfile
import time
import unittest
from pathlib import Path

import observatoire_demos as d
import observatoire_ml as m

RACINE = Path(__file__).resolve().parents[2]
PAGE = (RACINE / "ops" / "observatoire" / "index.html").read_text(encoding="utf-8")
IDENTIFIANTS = ["simulateur", "jeu", "preparation", "reference", "entrainement", "evaluation", "controles", "porte", "registre", "service"]


def par_id(carte):
    return {n["id"]: n for n in carte["noeuds"]}


class CarteDuDepot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.carte = m.carte()
        cls.noeuds = par_id(cls.carte)

    def test_les_dix_etapes_sont_la_dans_l_ordre_de_la_chaine(self):
        self.assertEqual(sorted(self.noeuds), sorted(IDENTIFIANTS))
        self.assertEqual(self.carte["colonnes"], 6)
        for n in self.carte["noeuds"]:
            self.assertIn(n["etat"], ("ok", "alarme", "touche", "arret"))
            self.assertTrue(n["role"] and n["entree"] and n["sortie"] and n["libelle"], n["id"])
            self.assertIn(n["ligne"], (0, 1))
            self.assertIn(n["colonne"], range(6))

    def test_chaque_lien_relie_deux_etapes_qui_existent_et_va_de_gauche_a_droite_ou_de_haut_en_bas(self):
        for lien in self.carte["liens"]:
            a, b = self.noeuds[lien["de"]], self.noeuds[lien["vers"]]
            self.assertTrue(a["colonne"] < b["colonne"] or (a["colonne"] == b["colonne"] and a["ligne"] < b["ligne"]), lien)

    def test_deux_etapes_ne_se_superposent_pas(self):
        places = [(n["colonne"], n["ligne"]) for n in self.carte["noeuds"]]
        self.assertEqual(len(places), len(set(places)))

    def test_le_seul_lien_en_pointille_est_le_modele_non_branche_sur_le_service(self):
        self.assertEqual([(x["de"], x["vers"]) for x in self.carte["liens"] if x["pointille"]], [("registre", "service")])

    def test_la_porte_est_rouge_quand_des_conditions_sont_manquees_et_dit_lesquelles(self):
        porte = self.noeuds["porte"]
        conditions = (json.loads((RACINE / "ml" / "evaluation" / "resultat-test.json").read_text(encoding="utf-8"))["conditions"])
        manquees = [c["condition"] for c in conditions if not c["remplie"]]
        self.assertTrue(manquees, "le jeu du dépôt a un modèle rejeté")
        self.assertEqual(porte["etat"], "alarme")
        for code in manquees:
            self.assertIn(code, porte["sous"])
        self.assertEqual(len(porte["details"]), len(conditions))

    def test_aucun_modele_en_service_se_voit_au_registre_et_au_service(self):
        self.assertEqual(self.noeuds["registre"]["etat"], "touche")
        self.assertIn("aucun modèle en service", self.noeuds["registre"]["sous"])
        self.assertEqual(self.noeuds["service"]["etat"], "touche")
        self.assertIn("règle de seuils", self.noeuds["service"]["sous"])
        self.assertIn("non branché", json.dumps(self.noeuds["service"]["details"], ensure_ascii=False))

    def test_les_chiffres_affiches_viennent_des_fichiers(self):
        test = json.loads((RACINE / "ml" / "evaluation" / "resultat-test.json").read_text(encoding="utf-8"))
        f1 = f"{test['modele']['f1_macro']:.3f}".replace(".", ",")
        self.assertIn(f1, self.noeuds["evaluation"]["sous"])
        selection = json.loads((RACINE / "ml" / "evaluation" / "selection.json").read_text(encoding="utf-8"))
        self.assertIn(selection["choix"]["candidat"], self.noeuds["entrainement"]["sous"])
        manifeste = json.loads((RACINE / "data" / "datasets" / "novaria-congestion-v1" / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn(f"{len(manifeste['runs'])} runs", self.noeuds["jeu"]["sous"])

    def test_chaque_etape_qui_se_rejoue_a_sa_demonstration(self):
        for n in self.carte["noeuds"]:
            if n["demo"]:
                self.assertIn(n["demo"], d.PAR_ID, n["id"])
                self.assertEqual(d.PAR_ID[n["demo"]].theme, "entrainement")

    def test_l_etape_qui_reecrit_un_fichier_suivi_n_est_pas_rejouable(self):
        self.assertIsNone(self.noeuds["entrainement"]["demo"])
        self.assertIn("non rejoué en direct", self.noeuds["entrainement"]["commande"])


class CarteSansRien(unittest.TestCase):
    def test_des_fichiers_absents_ne_donnent_jamais_une_etape_faite(self):
        with tempfile.TemporaryDirectory() as dossier:
            vide = Path(dossier)
            carte = m.carte(jeu=vide / "jeu", evaluation=vide / "ev", decision=vide / "decision.json", pointeur=vide / "pointeur.json")
        noeuds = par_id(carte)
        for identifiant in ("jeu", "entrainement", "evaluation", "controles", "porte"):
            self.assertEqual(noeuds[identifiant]["etat"], "arret", identifiant)
        self.assertEqual(noeuds["preparation"]["etat"], "arret")
        self.assertIn("jeu absent", noeuds["preparation"]["sous"])
        self.assertEqual(noeuds["controles"]["details"], [{"nom": "Dernière exécution", "valeur": "aucune sur ce poste"}])

    def test_un_fichier_illisible_n_est_pas_une_erreur(self):
        with tempfile.TemporaryDirectory() as dossier:
            vide = Path(dossier)
            (vide / "ev").mkdir()
            (vide / "ev" / "selection.json").write_text("{pas du json", encoding="utf-8")
            carte = m.carte(jeu=vide / "jeu", evaluation=vide / "ev", decision=vide / "d.json", pointeur=vide / "p.json")
        self.assertEqual(par_id(carte)["entrainement"]["etat"], "arret")

    def test_un_modele_en_service_change_le_registre_et_le_service(self):
        with tempfile.TemporaryDirectory() as dossier:
            pointeur = Path(dossier) / "en-service.json"
            pointeur.write_text(json.dumps({"run_id": "ia05-essai"}), encoding="utf-8")
            noeuds = par_id(m.carte(pointeur=pointeur))
        self.assertEqual(noeuds["registre"]["etat"], "ok")
        self.assertIn("ia05-essai", json.dumps(noeuds["registre"]["details"]))
        self.assertEqual(noeuds["service"]["etat"], "ok")

    def test_une_decision_sans_condition_manquee_donne_une_porte_verte(self):
        with tempfile.TemporaryDirectory() as dossier:
            decision = Path(dossier) / "decision.json"
            decision.write_text(json.dumps({"decision": "accepté", "conditions": [{"condition": "A1", "libelle": "x", "modele": 1, "exige": "≥ 0", "remplie": True}], "securite": []}), encoding="utf-8")
            noeuds = par_id(m.carte(decision=decision))
        self.assertEqual(noeuds["porte"]["etat"], "ok")
        self.assertEqual(noeuds["controles"]["etat"], "ok")

    def test_la_carte_est_serialisable(self):
        json.dumps(m.carte())


class FauxProcessus:
    def __init__(self, lignes, code):
        self.stdout, self.code = io.StringIO("".join(f"{x}\n" for x in lignes)), code

    def wait(self):
        return self.code

    def terminate(self):
        pass


def attendre(taches):
    for _ in range(300):
        c = taches.etat()["courante"]
        if c and c["etat"] != "en_cours":
            return c
        time.sleep(0.01)
    raise AssertionError("pas terminé")


class Rejeu(unittest.TestCase):
    def test_la_porte_fermee_est_le_resultat_attendu_pas_une_panne(self):
        taches = d.Taches(lanceur=lambda *_a, **_k: FauxProcessus(["Porte FERMÉE : modèle sous le seuil"], 1))
        taches.demarrer("ent-porte")
        c = attendre(taches)
        self.assertEqual((c["etat"], c["code"]), ("ok", 1))

    def test_une_autre_demonstration_qui_sort_en_1_reste_un_echec(self):
        taches = d.Taches(lanceur=lambda *_a, **_k: FauxProcessus(["boum"], 1))
        taches.demarrer("ent-evaluer")
        self.assertEqual(attendre(taches)["etat"], "echec")

    def test_toute_la_chaine_joue_les_quatre_etapes_dans_l_ordre_puis_finit_sur_la_porte(self):
        appels = []

        def lancer(commande, **_):
            appels.append(commande[2:])
            return FauxProcessus(["ok"], 1 if commande[-1] == "porte" else 0)

        taches = d.Taches(lanceur=lancer)
        taches.demarrer("ent-tout")
        c = attendre(taches)
        self.assertEqual(appels, [["preparation-check"], ["reference-mesure"], ["ml-pipeline", "evaluer"], ["ml-pipeline", "porte"]])
        self.assertEqual((c["etat"], c["code"]), ("ok", 1))

    def test_toute_la_chaine_s_arrete_si_une_etape_echoue(self):
        appels = []

        def lancer(commande, **_):
            appels.append(commande[2:])
            return FauxProcessus(["x"], 2 if commande[-1] == "reference-mesure" else 0)

        taches = d.Taches(lanceur=lancer)
        taches.demarrer("ent-tout")
        self.assertEqual(attendre(taches)["etat"], "echec")
        self.assertEqual(appels, [["preparation-check"], ["reference-mesure"]])

    def test_aucune_demonstration_d_entrainement_n_ecrit_un_fichier_suivi(self):
        for demo in (x for x in d.DEMOS if x.theme == "entrainement"):
            for commande in d.commandes(demo):
                self.assertNotIn("train", commande, demo.identifiant)  # ml-train réécrit selection.json
                self.assertNotIn("dataset-build", commande)
                self.assertNotIn("ml-anomalies", commande)
                self.assertNotIn("ml-prevision", commande)

    def test_les_commandes_viennent_toutes_de_dev_py(self):
        sous_commandes = set(re.findall(r'add\("([a-z0-9-]+)"', (RACINE / "scripts" / "dev" / "dev.py").read_text(encoding="utf-8")))
        for demo in (x for x in d.DEMOS if x.theme == "entrainement"):
            for etape in demo.suite or (demo.arguments,):
                self.assertIn(etape[0], sous_commandes, demo.identifiant)


class Page(unittest.TestCase):
    def test_l_onglet_et_ses_fonctions_existent(self):
        for attendu in ('data-vue="entrainement"', "function dessinerEntrainement", "function dessinerCarteMl", "/api/entrainement", "noeudsEnCours"):
            self.assertIn(attendu, PAGE)

    def test_chaque_commande_de_la_page_correspond_a_une_demonstration(self):
        for commande in re.findall(r'"((?:preparation-check|reference-mesure|ml-pipeline \w+|ml-registre en-service))":', PAGE):
            premiere = commande.split()[0]
            self.assertTrue(any(premiere in (x.suite[0][0] if x.suite else x.arguments[0], *[e[0] for e in x.suite]) for x in d.DEMOS), commande)


if __name__ == "__main__":
    unittest.main()
