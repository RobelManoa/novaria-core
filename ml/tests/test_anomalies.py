"""Détection d'anomalies (IA-09) : variables, règles, évaluation et banc d'essai, sans le rapport complet.

Les cas de règles sont des flux fabriqués à la main (le résultat attendu se calcule de tête) ; un petit run réel du
simulateur vérifie la chaîne de bout en bout. Les tests d'Isolation Forest ont besoin de scikit-learn (`ml/.venv`,
`python3 scripts/dev/dev.py ml-env`) et sont ignorés sans lui.
"""

import unittest

from tests import support  # noqa: F401  (chemins d'import)

from anomalies import campagne, evaluation, isolation, regles, variables
from anomalies.campagne import Banc, Injection, Mesure
from anomalies.regles import Alerte, DetecteurRegles
from jeu_entrainement.catalogue import RunSpec

try:
    import sklearn  # noqa: F401

    SKLEARN = True
except ImportError:
    SKLEARN = False

T0 = 1_792_483_200.0  # 2026-10-20T08:00:00Z


def flux(capteur="SENSOR_001", n=40, vehicules=3, vitesse=45.0, occupation=0.1, debut=0.0, retard=0.0, ident="x"):
    """n messages de 10 s, avec un peu de variation pour que le plateau ne se déclenche pas tout seul."""
    sortie = []
    for k in range(n):
        instant = T0 + debut + 10 * (k + 1)
        sortie.append(Mesure(instant + retard, instant, capteur, f"{ident}:{capteur}:{int(instant)}", vehicules + (k % 3) - 1, vitesse + (k % 5), occupation + 0.01 * (k % 4)))
    return sortie


def jouer(mesures, parametres=regles.PARAMETRES, fin=None):
    detecteur = DetecteurRegles(parametres)
    alertes = []
    for m in sorted(mesures, key=lambda x: x.livre):
        alertes += detecteur.traiter(m)
    return alertes + detecteur.fin(fin if fin is not None else max(m.livre for m in mesures))


def noms(alertes):
    return sorted({a.detecteur for a in alertes})


class Variables(unittest.TestCase):
    def test_un_flux_normal_ne_declenche_aucune_regle(self):
        self.assertEqual(jouer(flux(n=120)), [])

    def test_une_copie_compte_mais_ne_modifie_pas_l_historique_ni_le_plateau(self):
        suivi = variables.Suivi()
        m = flux(n=3)[2]
        premiere = suivi.observer(m)
        copie = suivi.observer(m._replace(livre=m.livre + 3))
        i = variables.NOMS.index
        self.assertEqual((premiere[i("copies")], copie[i("copies")]), (1, 2))
        self.assertEqual(copie[i("plateau")], 1.0)
        self.assertEqual(len(suivi.capteurs[m.capteur].debits), 1)

    def test_le_champ_qualite_du_simulateur_n_est_pas_dans_la_mesure(self):
        self.assertNotIn("quality", Mesure._fields)
        self.assertNotIn("status", Mesure._fields)

    def test_le_silence_et_le_retard_se_lisent_a_la_livraison(self):
        suivi = variables.Suivi()
        a, b = flux(n=2, retard=120.0)
        suivi.observer(a)
        x = suivi.observer(b)
        self.assertEqual(x[variables.NOMS.index("silence_s")], 10.0)
        self.assertEqual(x[variables.NOMS.index("retard_s")], 120.0)


class Regles(unittest.TestCase):
    def test_capteur_muet_alerte_60_s_apres_la_derniere_livraison(self):
        mesures = flux("SENSOR_001", 20) + flux("SENSOR_002", 60)
        alertes = [a for a in jouer(mesures) if a.detecteur == "capteur_muet"]
        derniere = T0 + 200
        self.assertEqual([(a.capteur, a.a) for a in alertes], [("SENSOR_001", derniere + 60)])

    def test_un_capteur_muet_qui_reprend_puis_se_tait_de_nouveau_alerte_deux_fois(self):
        mesures = flux("SENSOR_001", 10) + flux("SENSOR_001", 10, debut=200) + flux("SENSOR_002", 80)
        self.assertEqual(sum(a.detecteur == "capteur_muet" for a in jouer(mesures)), 2)

    def test_message_en_retard_au_dela_de_30_s(self):
        self.assertEqual(noms(jouer(flux(n=20, retard=31.0))), ["livraison_en_retard"])
        self.assertEqual(jouer(flux(n=20, retard=30.0)), [])

    def test_un_identifiant_deja_livre_est_un_doublon(self):
        mesures = flux(n=20)
        copie = mesures[10]._replace(livre=mesures[10].livre + 3)
        alertes = jouer([*mesures, copie])
        self.assertEqual([(a.detecteur, a.a) for a in alertes], [("doublon", copie.livre)])

    def test_valeur_aberrante_ecart_a_la_mediane(self):
        mesures = flux(n=60)
        i = 40
        mesures[i] = mesures[i]._replace(vitesse=95.0)
        alertes = jouer(mesures)
        self.assertEqual([(a.detecteur, a.a) for a in alertes], [("ecart_mediane", mesures[i].livre)])

    def test_comptage_aberrant(self):
        mesures = flux(n=60)
        mesures[45] = mesures[45]._replace(vehicules=26)
        self.assertEqual(noms(jouer(mesures)), ["ecart_mediane"])

    def test_vitesse_nulle_avec_des_vehicules_est_incoherente(self):
        mesures = flux(n=60)
        mesures[50] = mesures[50]._replace(vehicules=2, vitesse=0.0)
        self.assertEqual(noms(jouer(mesures)), ["ecart_mediane"])

    def test_aucun_vehicule_et_aucune_vitesse_n_est_pas_une_anomalie(self):
        mesures = flux(n=60)
        mesures[50] = mesures[50]._replace(vehicules=0, vitesse=None, occupation=0.0)
        self.assertEqual(jouer(mesures), [])

    def test_plateau_apres_douze_mesures_identiques(self):
        mesures = flux(n=60)
        gel = mesures[30]
        for k in range(30, 50):
            mesures[k] = mesures[k]._replace(vehicules=gel.vehicules, vitesse=gel.vitesse, occupation=gel.occupation)
        alertes = [a for a in jouer(mesures) if a.detecteur == "plateau"]
        self.assertEqual(alertes[0].a, mesures[30 + 11].livre)  # la 12e mesure identique
        self.assertEqual(len(alertes), 20 - 11)

    def test_chute_de_debit_sans_ralentissement(self):
        mesures = flux(n=80, vehicules=4)
        for k in range(50, 80):
            mesures[k] = mesures[k]._replace(vehicules=0, vitesse=None, occupation=0.0)
        alertes = [a for a in jouer(mesures) if a.detecteur == "chute_de_debit"]
        self.assertTrue(alertes)
        self.assertGreater(alertes[0].a, mesures[50].livre)

    def test_une_baisse_de_debit_avec_ralentissement_n_est_pas_inexpliquee(self):
        mesures = flux(n=80, vehicules=4, vitesse=45.0)
        for k in range(50, 80):
            mesures[k] = mesures[k]._replace(vehicules=0 if k % 2 else 1, vitesse=8.0, occupation=0.5)
        self.assertNotIn("chute_de_debit", noms(jouer(mesures)))

    def test_route_peu_chargee_pas_de_chute(self):
        mesures = flux(n=80, vehicules=1)
        for k in range(50, 80):
            mesures[k] = mesures[k]._replace(vehicules=0, vitesse=None)
        self.assertNotIn("chute_de_debit", noms(jouer(mesures)))


def banc(injections, mesures=None, duree=3600.0):
    spec = RunSpec("t", "journee-calme", 1, "evaluation", "08:00", int(duree))
    return Banc(spec, "evaluation", mesures or [], injections, T0, T0 + duree)


class Evaluation(unittest.TestCase):
    def test_les_alertes_proches_d_un_capteur_forment_un_episode(self):
        a = [Alerte("r", "S1", 100), Alerte("r", "S1", 150), Alerte("r", "S1", 400), Alerte("r", "S2", 120)]
        e = evaluation.episodes(a)
        self.assertEqual([(x.capteur, x.debut, x.fin) for x in e], [("S1", 100, 150), ("S2", 120, 120), ("S1", 400, 400)])

    def test_delai_rappel_et_fausses_alertes(self):
        injections = [Injection("muet", "S1", T0 + 100, T0 + 400, 0.0, "simulateur"), Injection("muet", "S2", T0 + 100, T0 + 400, 0.0, "simulateur")]
        alertes = [Alerte("capteur_muet", "S1", T0 + 150), Alerte("capteur_muet", "S3", T0 + 900)]
        r = evaluation.evaluer_banc(banc(injections), alertes)
        self.assertEqual([d for _, d, _ in r.delais], [50.0, None])
        self.assertEqual((r.episodes_vrais, r.episodes_faux), (1, 1))
        resume = evaluation.resume_par_type([r])["muet"]
        self.assertEqual((resume["injectees"], resume["detectees"], resume["rappel"], resume["delai_median_s"]), (2, 1, 0.5, 50.0))
        self.assertEqual(evaluation.precision([r]), 0.5)
        self.assertEqual(evaluation.fausses_par_heure([r]), 1.0)

    def test_une_alerte_avant_l_anomalie_ou_trop_tard_n_est_pas_une_detection(self):
        injection = Injection("retard", "S1", T0 + 100, T0 + 200, 120.0, "simulateur")
        tot = evaluation.evaluer_banc(banc([injection]), [Alerte("r", "S1", T0 + 99)])
        tard = evaluation.evaluer_banc(banc([injection]), [Alerte("r", "S1", T0 + 200 + 120 + evaluation.TOLERANCE_S + 1)])
        dans = evaluation.evaluer_banc(banc([injection]), [Alerte("r", "S1", T0 + 200 + 120)])
        self.assertEqual([tot.delais[0][1], tard.delais[0][1], dans.delais[0][1]], [None, None, 220.0])


class BancEssai(unittest.TestCase):
    def test_les_roles_ne_se_recouvrent_pas(self):
        specs = campagne.APPRENTISSAGE_RUNS + campagne._specs_reglage(campagne.APPRENTISSAGE, 131, 7) + campagne.VALIDATION_RUNS + campagne._specs_reglage() + campagne.EVALUATION_RUNS
        self.assertEqual(len({s.seed for s in specs}), len(specs))
        self.assertEqual(len({s.run_id for s in specs}), len(specs))
        self.assertTrue(all(s.seed >= 101 for s in specs))  # jamais les graines du jeu v1 (11 à 34)

    def test_l_evaluation_couvre_les_quatre_anomalies_du_simulateur_trois_fois_par_scenario(self):
        total = {t: 0 for t in campagne.FORCES}
        for s in campagne.EVALUATION_RUNS:
            for texte in s.anomalies:
                total[texte.partition(":")[0]] += 1
        self.assertEqual(total, {"muet": 9, "retard": 9, "doublon": 9, "aberrante": 9})

    def test_un_petit_run_reel_de_bout_en_bout(self):
        spec = RunSpec("ia09-test", "heure-de-pointe", 7, "evaluation", "07:00", 1200,
                       ("muet:sensor=SENSOR_003,at=+600,duration=5m", "doublon:sensor=SENSOR_004,at=+300,duration=2m,copies=1,lag=2",
                        "retard:sensor=SENSOR_005,at=+800,duration=3m,delay=90", "aberrante:sensor=SENSOR_006,at=+500,duration=10s,variant=vitesse-nulle"))
        b = campagne.executer(spec, campagne.EVALUATION)
        self.assertEqual(sorted(i.type for i in b.injections), ["aberrante", "doublon", "muet", "retard"])
        r = evaluation.evaluer_banc(b, regles.alertes_des_regles(b))
        delais = {i.type: d for i, d, _ in r.delais}
        self.assertTrue(all(d is not None for d in delais.values()), delais)
        self.assertEqual((delais["muet"], delais["doublon"], delais["aberrante"]), (50.0, 2.0, 0.0))  # le doublon est vu 2 s après l'original (lag=2)
        self.assertEqual(regles.alertes_des_regles(b), regles.alertes_des_regles(b))  # déterministe

    def test_banc_synthetique_range_ses_injections_avec_les_instants_voulus(self):
        b = campagne.banc_synthetique("heure-de-pointe", 331)
        self.assertEqual([(i.type, i.capteur, i.source) for i in b.injections],
                         [(t, c, campagne.SYNTHETIQUE) for t, c, _, _ in campagne.INJECTIONS_SYNTHETIQUES])
        self.assertEqual([i.debut - b.debut for i in b.injections], [d for _, _, d, _ in campagne.INJECTIONS_SYNTHETIQUES])
        self.assertEqual(len(b.mesures), len(campagne.executer(b.spec, campagne.EVALUATION).mesures))

    def test_les_injections_synthetiques_ne_changent_que_leur_capteur_et_leur_fenetre(self):
        spec = RunSpec("ia09-synth-test", "heure-de-pointe", 8, "evaluation", "07:00", 1200)
        b = campagne.executer(spec, campagne.EVALUATION)
        avant = b.mesures
        gele = campagne.figer(avant, "SENSOR_001", T0 - T0 + b.debut + 600, b.debut + 800)
        modifiees = [(x, y) for x, y in zip(avant, gele, strict=True) if x != y]
        self.assertTrue(modifiees)
        self.assertTrue(all(x.capteur == "SENSOR_001" and b.debut + 600 <= x.instant <= b.debut + 800 for x, _ in modifiees))
        valeurs = {(y.vehicules, y.vitesse, y.occupation) for _, y in modifiees}
        self.assertEqual(len(valeurs), 1)
        chute = campagne.chuter(avant, "SENSOR_002", b.debut + 600, b.debut + 800)
        self.assertTrue(all(y.vehicules <= x.vehicules for x, y in zip(avant, chute, strict=True)))


@unittest.skipUnless(SKLEARN, "scikit-learn absent : python3 scripts/dev/dev.py ml-env")
class IsolationForest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = RunSpec("ia09-if", "heure-de-pointe", 9, "apprentissage", "07:00", 1800)
        cls.banc = campagne.executer(spec, campagne.APPRENTISSAGE)
        cls.modele, cls.lignes = isolation.entrainer([cls.banc])

    def test_les_variables_sont_celles_des_regles(self):
        self.assertEqual(isolation.VARIABLES, variables.NOMS)
        lignes, mesures = isolation.variables_du_banc(self.banc)
        self.assertEqual(len(lignes), len(mesures))
        self.assertTrue(all(len(x) == len(variables.NOMS) for x in lignes[:50]))

    def test_les_scores_sont_deterministes_et_un_seuil_plus_bas_donne_moins_d_alertes(self):
        notes, mesures = isolation.scores(self.modele, self.banc)
        self.assertEqual(notes, isolation.scores(self.modele, self.banc)[0])
        larges = isolation.alertes_du_modele(self.modele, self.banc, max(notes) + 1, (notes, mesures))
        serres = isolation.alertes_du_modele(self.modele, self.banc, min(notes) + 1e-9, (notes, mesures))
        self.assertEqual(len(larges), len(mesures))
        self.assertLessEqual(len(serres), 1)

    def test_un_message_aberrant_a_un_score_plus_bas_que_la_mediane(self):
        _, mesures = isolation.variables_du_banc(self.banc)
        notes, _ = isolation.scores(self.modele, self.banc)
        rang = len(mesures) // 2
        aberrant = mesures[rang]._replace(vitesse=190.0, vehicules=60)
        copie = self.banc.__class__(self.banc.spec, self.banc.role, [aberrant if m == mesures[rang] else m for m in self.banc.mesures], [], self.banc.debut, self.banc.fin)
        nouvelles, nouvelles_mesures = isolation.scores(self.modele, copie)
        position = nouvelles_mesures.index(aberrant)
        self.assertLess(nouvelles[position], sorted(notes)[len(notes) // 2])

    def test_choix_du_seuil_tient_le_budget(self):
        from anomalies import rapport

        seuil, taux = rapport.choisir_seuil(self.modele, [self.banc])
        self.assertLessEqual(taux, evaluation.BUDGET_FAUSSES_PAR_HEURE)


@unittest.skipUnless(SKLEARN, "scikit-learn absent : python3 scripts/dev/dev.py ml-env")
class Rapport(unittest.TestCase):
    """La campagne complète prend une minute ; ici elle tourne sur trois petits runs pour vérifier l'enchaînement et les fichiers."""

    @classmethod
    def setUpClass(cls):
        def petit(nom, graine, anomalies=(), role=campagne.EVALUATION):
            return campagne.executer(RunSpec(nom, "heure-de-pointe", graine, role, "07:00", 1500, anomalies), role)

        cls.bancs = {
            campagne.APPRENTISSAGE: [petit("ia09-r-app", 9, role=campagne.APPRENTISSAGE)],
            campagne.VALIDATION: [petit("ia09-r-val", 10, role=campagne.VALIDATION)],
            campagne.EVALUATION: [petit("ia09-r-eval", 11, ("muet:sensor=SENSOR_003,at=+600,duration=5m", "aberrante:sensor=SENSOR_006,at=+900,duration=10s,variant=vitesse-nulle"))],
        }

    def test_ecrire_produit_le_json_et_le_markdown_sans_secret_ni_chemin_local(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock

        from anomalies import rapport

        with tempfile.TemporaryDirectory() as dossier, mock.patch.object(campagne, "tous_les_bancs", return_value=self.bancs):
            chemin_json, chemin_md = Path(dossier) / "a.json", Path(dossier) / "a.md"
            resultat = rapport.ecrire(chemin_json, chemin_md)
            lu = json.loads(chemin_json.read_text(encoding="utf-8"))
            texte = chemin_md.read_text(encoding="utf-8")
        self.assertEqual(lu["detecteurs"]["regles"]["par_type"]["muet"]["rappel"], 1.0)
        self.assertEqual(lu["detecteurs"]["regles"]["par_type"]["aberrante"]["delai_median_s"], 0.0)
        self.assertEqual(set(resultat["detecteurs"]), {"regles", "isolation_forest"})
        self.assertIn("| capteur muet | simulateur | 1 | 100 % (1/1) | 50 / 50 |", texte)
        self.assertNotIn(str(support.RACINE), texte + json.dumps(lu))
        self.assertNotIn("\r", texte)

    def test_le_point_d_entree_rend_0_et_1_sans_scikit_learn(self):
        from unittest import mock

        from anomalies import __main__ as principal
        from anomalies import rapport

        with mock.patch.object(rapport, "ecrire", side_effect=isolation.SklearnAbsent("absent")), mock.patch("sys.stderr"):
            self.assertEqual(principal.main(), 1)
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as dossier, mock.patch.object(campagne, "tous_les_bancs", return_value=self.bancs), \
                mock.patch.object(rapport, "JSON", Path(dossier) / "a.json"), mock.patch.object(rapport, "MARKDOWN", Path(dossier) / "a.md"), mock.patch("sys.stdout"):
            self.assertEqual(principal.main(), 0)
            self.assertTrue((Path(dossier) / "a.md").is_file())


if __name__ == "__main__":
    unittest.main()
