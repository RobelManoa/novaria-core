"""Préparation des variables et découpage (IA-02) : variables permises, calendrier, historique sans futur, ajustement
sur l'entraînement seul, découpage par run et par scénario, découpage dans l'ordre du temps, contrôles sur le jeu v1."""

import dataclasses
import json
import math
import random
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

from tests import support  # noqa: F401 : chemins d'import

from jeu_entrainement import catalogue as cat
from preparation import ajustement, calendrier, controles, decoupage, donnees, historique, variables
from preparation.__main__ import main

VERSIONNE = donnees.DOSSIER_JEU
JEU_PRESENT = (VERSIONNE / "train.parquet").is_file() and (VERSIONNE / "validation.parquet").is_file()
MINUTE = 60_000


class TestCalendrier(unittest.TestCase):
    def test_le_20_octobre_2026_est_un_mardi(self):
        c = calendrier.variables_calendaires(datetime(2026, 10, 20, 7, 40, tzinfo=UTC))
        self.assertEqual((c["hour_of_day"], c["iso_day_of_week"], c["is_weekend"], c["is_holiday"]), (7, 2, False, False))

    def test_le_week_end(self):
        samedi = calendrier.variables_calendaires(datetime(2026, 10, 24, 12, 0, tzinfo=UTC))
        dimanche = calendrier.variables_calendaires(datetime(2026, 10, 25, 12, 0, tzinfo=UTC))
        lundi = calendrier.variables_calendaires(datetime(2026, 10, 26, 12, 0, tzinfo=UTC))
        vendredi = calendrier.variables_calendaires(datetime(2026, 10, 23, 23, 59, tzinfo=UTC))
        self.assertEqual((vendredi["is_weekend"], samedi["is_weekend"], dimanche["is_weekend"], lundi["is_weekend"]), (False, True, True, False))

    def test_angles_connus(self):
        minuit = calendrier.variables_calendaires(datetime(2026, 10, 19, 0, 0, tzinfo=UTC))  # lundi 0 h
        six_heures = calendrier.variables_calendaires(datetime(2026, 10, 19, 6, 0, tzinfo=UTC))
        self.assertAlmostEqual(minuit["hour_sin"], 0.0, places=12)
        self.assertAlmostEqual(minuit["hour_cos"], 1.0, places=12)
        self.assertAlmostEqual(six_heures["hour_sin"], 1.0, places=12)
        self.assertAlmostEqual(minuit["dow_sin"], 0.0, places=12)
        self.assertAlmostEqual(minuit["dow_cos"], 1.0, places=12)

    def test_23h59_est_proche_de_minuit_et_pas_loin(self):
        """Raison d'être du sinus et du cosinus : 23 h 59 et 0 h sont voisins, alors que 23 et 0 sont loin sur une échelle."""
        a = calendrier.variables_calendaires(datetime(2026, 10, 19, 23, 59, tzinfo=UTC))
        b = calendrier.variables_calendaires(datetime(2026, 10, 20, 0, 0, tzinfo=UTC))
        distance = math.hypot(a["hour_sin"] - b["hour_sin"], a["hour_cos"] - b["hour_cos"])
        self.assertLess(distance, 0.01)

    def test_dimanche_soir_est_proche_de_lundi_matin(self):
        a = calendrier.variables_calendaires(datetime(2026, 10, 25, 23, 59, tzinfo=UTC))
        b = calendrier.variables_calendaires(datetime(2026, 10, 26, 0, 0, tzinfo=UTC))
        self.assertLess(math.hypot(a["dow_sin"] - b["dow_sin"], a["dow_cos"] - b["dow_cos"]), 0.001)

    def test_l_instant_est_converti_en_utc(self):
        decale = datetime(2026, 10, 20, 9, 40, tzinfo=timezone(timedelta(hours=2)))  # 07:40 UTC
        self.assertEqual(calendrier.variables_calendaires(decale)["hour_of_day"], 7)

    def test_un_instant_sans_fuseau_est_refuse(self):
        with self.assertRaises(ValueError):
            calendrier.variables_calendaires(datetime(2026, 10, 20, 7, 40))

    def test_jours_feries_a_la_demande_et_faux_par_defaut(self):
        instant = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
        self.assertFalse(calendrier.variables_calendaires(instant)["is_holiday"])
        self.assertTrue(calendrier.variables_calendaires(instant, {date(2026, 11, 11)})["is_holiday"])

    def test_les_noms_sont_ceux_declares(self):
        self.assertEqual(tuple(calendrier.variables_calendaires(datetime(2026, 1, 1, tzinfo=UTC))), calendrier.NOMS)


class TestHistorique(unittest.TestCase):
    RATIO = {100: 0.9, 101: 0.8, 102: None, 103: 0.6, 104: 0.5, 105: 0.4, 106: 0.3}
    FLUX = {m: float(m - 99) for m in range(100, 107)}

    def test_decalages_calcules_a_la_main(self):
        c = historique.colonnes_historiques(self.RATIO, self.FLUX, 106)
        self.assertEqual([c[f"speed_ratio_lag{k}"] for k in (1, 2, 3, 4, 5)], [0.4, 0.5, 0.6, None, 0.8])
        self.assertEqual([c[f"flow_lag{k}"] for k in (1, 2, 3, 4, 5)], [6.0, 5.0, 4.0, 3.0, 2.0])

    def test_moyennes_calculees_a_la_main(self):
        c = historique.colonnes_historiques(self.RATIO, self.FLUX, 106)
        self.assertAlmostEqual(c["speed_ratio_ma5"], (0.4 + 0.5 + 0.6 + 0.8) / 4)  # la valeur absente est ignorée
        self.assertAlmostEqual(c["flow_ma5"], (6 + 5 + 4 + 3 + 2) / 5)
        self.assertAlmostEqual(c["speed_ratio_ma15"], (0.9 + 0.8 + 0.6 + 0.5 + 0.4) / 5)  # 15 minutes : tout ce qui existe

    def test_le_debut_de_serie_n_a_rien_d_invente(self):
        c = historique.colonnes_historiques(self.RATIO, self.FLUX, 100)
        self.assertTrue(all(v is None for v in c.values()))

    def test_les_colonnes_sont_celles_du_dictionnaire_dans_l_ordre(self):
        self.assertEqual(tuple(historique.colonnes_historiques({}, {}, 0)), variables.HISTORIQUE)

    def test_la_minute_elle_meme_n_entre_jamais(self):
        avant = historique.colonnes_historiques(self.RATIO, self.FLUX, 104)
        modifie = {**self.RATIO, 104: 0.0001}
        flux_modifie = {**self.FLUX, 104: 9999.0}
        self.assertEqual(historique.colonnes_historiques(modifie, flux_modifie, 104), avant)

    def test_changer_l_avenir_ne_change_rien(self):
        avant = historique.colonnes_historiques(self.RATIO, self.FLUX, 104)
        futur = {m: (7.0 if m > 104 else v) for m, v in self.RATIO.items()}
        futur_flux = {m: (-3.0 if m > 104 else v) for m, v in self.FLUX.items()}
        self.assertEqual(historique.colonnes_historiques(futur, futur_flux, 104), avant)

    def test_un_decalage_nul_ou_negatif_est_refuse(self):
        for k in (0, -1):
            with self.assertRaises(ValueError):
                historique.valeur_decalee(self.RATIO, 104, k)
        with self.assertRaises(ValueError):
            historique.moyenne_des_precedentes(self.RATIO, 104, 0)

    def test_la_reponse_est_l_avenir_et_seulement_lui(self):
        self.assertEqual(historique.valeur_a(self.RATIO, 100, 5), 0.4)
        self.assertIsNone(historique.valeur_a(self.RATIO, 105, 5))  # fin de série
        with self.assertRaises(ValueError):
            historique.valeur_a(self.RATIO, 100, 0)


class TestVariables(unittest.TestCase):
    def test_la_detection_n_a_aucune_variable_interdite(self):
        self.assertEqual(variables.verifier_usage(variables.DETECTION), [])
        self.assertEqual(set(variables.DETECTION.variables) & set(variables.DETECTION.interdites), set())

    def test_chaque_colonne_du_jeu_est_classee_pour_chaque_usage(self):
        for usage in (variables.DETECTION, variables.prevision(5), variables.prevision(15)):
            self.assertEqual(variables.colonnes_non_classees(usage), [], usage.nom)

    def test_une_colonne_ajoutee_au_jeu_sans_decision_est_signalee(self):
        self.assertEqual(variables.colonnes_non_classees(variables.DETECTION, (*variables.NOMS, "nouvelle_colonne")), ["nouvelle_colonne"])

    def test_la_detection_exclut_cles_calendrier_et_avenir(self):
        v = set(variables.DETECTION.variables)
        for colonne in (*variables.CLES, *variables.CALENDRIER, *variables.CIBLES_PREVISION, "label_state"):
            self.assertNotIn(colonne, v)

    def test_la_detection_garde_les_mesures_l_historique_et_le_troncon(self):
        v = set(variables.DETECTION.variables)
        self.assertTrue(set(variables.MESURES) | set(variables.HISTORIQUE) | set(variables.TRONCON_NUMERIQUE) | {"road_type"} <= v)

    def test_la_prevision_exclut_la_verite_terrain_et_l_autre_horizon(self):
        u = variables.prevision(5)
        self.assertNotIn("label_state", u.variables)
        self.assertNotIn("speed_ratio_h15", u.variables)
        self.assertIn("label_state", u.interdites)
        self.assertEqual(u.cible, "speed_ratio_h5")
        self.assertTrue(u.calendrier)

    def test_une_variable_interdite_est_detectee(self):
        for fautive, morceau in (("hour_of_day", "interdite"), ("speed_ratio_h5", "interdite"), ("run_id", "interdite"), ("seed", "interdite")):
            usage = dataclasses.replace(variables.DETECTION, numeriques=(*variables.DETECTION.numeriques, fautive))
            ecarts = variables.verifier_usage(usage)
            self.assertTrue(any(fautive in e and morceau in e for e in ecarts), fautive)

    def test_la_cible_dans_les_variables_est_detectee(self):
        usage = dataclasses.replace(variables.DETECTION, categorielles=(*variables.DETECTION.categorielles, "label_state"))
        self.assertTrue(any("la cible label_state" in e for e in variables.verifier_usage(usage)))

    def test_une_colonne_inconnue_est_detectee(self):
        usage = dataclasses.replace(variables.DETECTION, numeriques=(*variables.DETECTION.numeriques, "speed_ratio_lag6"))
        self.assertTrue(any("speed_ratio_lag6" in e and "n'est pas une colonne" in e for e in variables.verifier_usage(usage)))

    def test_un_horizon_inconnu_est_refuse(self):
        with self.assertRaises(ValueError):
            variables.prevision(30)

    def test_les_colonnes_lues(self):
        self.assertNotIn("window_start", variables.DETECTION.colonnes_lues)
        self.assertIn("window_start", variables.prevision(15).colonnes_lues)
        self.assertEqual(variables.DETECTION.colonnes_lues[-1], "label_state")


def ligne(run="r1", etat="FREE_FLOW", instant=datetime(2026, 10, 20, 8, 0, tzinfo=UTC), **valeurs):
    base = {nom: 1.0 for nom in variables.DETECTION.numeriques}
    base.update(run_id=run, road_segment_id="ROAD_001", window_start=instant, road_type="LOCAL", label_state=etat,
                speed_ratio_h5=0.5, speed_ratio_h15=0.4)
    base.update(valeurs)
    return base


class TestAjustement(unittest.TestCase):
    def setUp(self):
        self.train = [ligne(speed_ratio=0.2, flow_lag1=None), ligne(speed_ratio=0.4, flow_lag1=5.0), ligne(speed_ratio=0.9, flow_lag1=7.0, road_type="ARTERIAL")]

    def test_medianes_et_categories_apprises_a_la_main(self):
        p = ajustement.Preparation(variables.DETECTION).ajuster(self.train)
        self.assertAlmostEqual(p.medianes["speed_ratio"], 0.4)
        self.assertAlmostEqual(p.medianes["flow_lag1"], 6.0)  # la valeur absente est ignorée
        self.assertEqual(p.categories["road_type"], ["ARTERIAL", "LOCAL"])
        self.assertEqual(p.runs_d_ajustement, ["r1"])

    def test_l_ajustement_refuse_les_lignes_hors_entrainement(self):
        melange = [*self.train, ligne(run="val-1")]
        with self.assertRaises(ajustement.FuiteDInformation) as e:
            ajustement.Preparation(variables.DETECTION).ajuster(melange, runs_permis={"r1"})
        self.assertIn("val-1", str(e.exception))
        ajustement.Preparation(variables.DETECTION).ajuster(self.train, runs_permis={"r1"})  # sans intrus : accepté

    def test_ajustement_sur_zero_ligne_ou_colonne_vide(self):
        with self.assertRaises(ValueError):
            ajustement.Preparation(variables.DETECTION).ajuster([])
        vides = [ligne(speed_ratio=None), ligne(speed_ratio=None)]
        with self.assertRaises(ValueError):
            ajustement.Preparation(variables.DETECTION).ajuster(vides)

    def test_transformer_avant_ajuster_est_refuse(self):
        with self.assertRaises(RuntimeError):
            ajustement.Preparation(variables.DETECTION).transformer(self.train, imputer=True)

    def test_la_valeur_absente_prend_la_mediane_de_l_entrainement_ou_nan(self):
        p = ajustement.Preparation(variables.DETECTION).ajuster(self.train)
        colonne = p.noms().index("flow_lag1")
        etrangere = [ligne(run="val-1", flow_lag1=None, speed_ratio=0.1)]
        x, _ = p.transformer(etrangere, imputer=True)
        self.assertEqual(x[0][colonne], 6.0)  # médiane de l'entraînement, pas de la validation
        x, _ = p.transformer(etrangere, imputer=False)
        self.assertTrue(math.isnan(x[0][colonne]))

    def test_transformer_n_apprend_rien(self):
        p = ajustement.Preparation(variables.DETECTION).ajuster(self.train)
        avant = json.dumps(p.parametres(), sort_keys=True)
        p.transformer([ligne(run="val-1", speed_ratio=123.0, flow_lag1=456.0)], imputer=True)
        self.assertEqual(json.dumps(p.parametres(), sort_keys=True), avant)

    def test_une_ligne_seule_donne_la_meme_sortie_que_dans_un_lot(self):
        p = ajustement.Preparation(variables.DETECTION).ajuster(self.train)
        lot = [ligne(speed_ratio=0.3), ligne(speed_ratio=None), ligne(speed_ratio=0.8, road_type="ARTERIAL")]
        x_lot, y_lot = p.transformer(lot, imputer=True)
        for i, une in enumerate(lot):
            x, y = p.transformer([une], imputer=True)
            self.assertEqual((x[0], y[0]), (x_lot[i], y_lot[i]))

    def test_une_categorie_jamais_vue_est_refusee(self):
        p = ajustement.Preparation(variables.DETECTION).ajuster(self.train)
        with self.assertRaises(ValueError) as e:
            p.transformer([ligne(road_type="MOTORWAY")], imputer=True)
        self.assertIn("MOTORWAY", str(e.exception))

    def test_codage_des_categories_et_noms_des_colonnes(self):
        p = ajustement.Preparation(variables.DETECTION).ajuster(self.train)
        noms = p.noms()
        self.assertEqual(noms[-2:], ["road_type=ARTERIAL", "road_type=LOCAL"])
        x, y = p.transformer([ligne(road_type="ARTERIAL", etat="CONGESTED")], imputer=True)
        self.assertEqual(x[0][-2:], [1.0, 0.0])
        self.assertEqual(y, ["CONGESTED"])
        self.assertEqual(len(x[0]), len(noms))

    def test_la_cible_et_les_cles_ne_sont_pas_dans_la_matrice(self):
        noms = ajustement.Preparation(variables.DETECTION).ajuster(self.train).noms()
        for interdit in ("label_state", "run_id", "seed", "speed_ratio_h5", "hour_of_day"):
            self.assertFalse(any(n.startswith(interdit) for n in noms), interdit)

    def test_prevision_calendrier_calcule_depuis_l_instant_et_cible_absente_ecartee(self):
        usage = variables.prevision(5)
        base = [ligne(instant=datetime(2026, 10, 19, 6, 0, tzinfo=UTC))]
        p = ajustement.Preparation(usage).ajuster(base)
        x, y = p.transformer([ligne(instant=datetime(2026, 10, 19, 6, 0, tzinfo=UTC), speed_ratio_h5=0.7),
                              ligne(speed_ratio_h5=None)], imputer=True)
        self.assertEqual(len(x), 1)  # la ligne sans réponse (fin de run) est écartée
        self.assertEqual(y, [0.7])
        i = p.noms().index("hour_sin")
        self.assertAlmostEqual(x[0][i], 1.0)  # 6 h : sinus de l'angle droit
        self.assertNotIn("hour_sin", p.medianes)  # calculée, rien à apprendre

    def test_les_parametres_se_serialisent_pour_model_runs(self):
        p = ajustement.Preparation(variables.DETECTION).ajuster(self.train)
        texte = json.dumps(p.parametres(), sort_keys=True)
        self.assertEqual(json.loads(texte)["usage"], "detection")
        self.assertEqual(json.loads(texte)["runs_d_ajustement"], ["r1"])


class TestDecoupageParRun(unittest.TestCase):
    def test_empreinte_stable_et_independante_de_l_ordre(self):
        a = decoupage.empreinte_du_decoupage()
        self.assertEqual(a, decoupage.empreinte_du_decoupage())
        melange = list(cat.CATALOGUE)
        random.Random(1).shuffle(melange)
        self.assertEqual(a, decoupage.empreinte_du_decoupage(tuple(melange)))

    def test_l_empreinte_du_catalogue_actuel(self):
        """Épinglée : si elle change, le découpage a changé ; relire la fiche de provenance et le cadrage."""
        self.assertEqual(decoupage.empreinte_du_decoupage(), "128bcb2861434c690a5f5b70262633c0468f6a915721ad1319c3720aeeb9c146")

    def test_deplacer_un_run_change_l_empreinte(self):
        runs = list(cat.CATALOGUE)
        runs[0] = dataclasses.replace(runs[0], ensemble=cat.TEST)
        self.assertNotEqual(decoupage.empreinte_du_decoupage(tuple(runs)), decoupage.empreinte_du_decoupage())

    def test_le_catalogue_est_conforme(self):
        self.assertEqual(decoupage.verifier_le_decoupage(), [])

    def test_aucun_run_ni_graine_commun_a_deux_ensembles(self):
        par = cat.par_ensemble()
        for a in cat.ENSEMBLES:
            for b in cat.ENSEMBLES:
                if a < b:
                    self.assertFalse({r.run_id for r in par[a]} & {r.run_id for r in par[b]})
                    self.assertFalse({r.seed for r in par[a]} & {r.seed for r in par[b]})

    def test_chaque_ensemble_a_les_trois_scenarios(self):
        for ensemble, runs in cat.par_ensemble().items():
            self.assertEqual({r.scenario_id for r in runs}, set(cat.SCENARIOS), ensemble)

    def test_les_defauts_du_decoupage_sont_detectes(self):
        base = list(cat.CATALOGUE)
        double = base + [dataclasses.replace(base[0], ensemble=cat.TEST, seed=9999)]
        self.assertTrue(decoupage.verifier_le_decoupage(tuple(double)))  # même run_id dans deux ensembles
        graine = base[:]
        graine[-1] = dataclasses.replace(graine[-1], seed=base[0].seed)
        self.assertTrue(decoupage.verifier_le_decoupage(tuple(graine)))  # même graine dans deux ensembles
        sans_scenario = [r for r in base if not (r.ensemble == cat.TEST and r.scenario_id == "incident-ponctuel")]
        self.assertTrue(decoupage.verifier_le_decoupage(tuple(sans_scenario)))  # scénario absent du test

    @unittest.skipUnless((VERSIONNE / "manifest.json").is_file(), "jeu v1 absent")
    def test_le_manifeste_versionne_suit_le_catalogue(self):
        manifeste = json.loads((VERSIONNE / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(decoupage.verifier_contre_le_manifeste(manifeste), [])

    @unittest.skipUnless((VERSIONNE / "manifest.json").is_file(), "jeu v1 absent")
    def test_les_defauts_du_manifeste_sont_detectes(self):
        manifeste = json.loads((VERSIONNE / "manifest.json").read_text(encoding="utf-8"))
        deplace = json.loads(json.dumps(manifeste))
        run = deplace["fichiers"]["train.parquet"]["runs"].pop()
        deplace["fichiers"]["test.parquet"]["runs"].append(run)
        self.assertTrue(any("le catalogue l'attend" in e for e in decoupage.verifier_contre_le_manifeste(deplace)))
        double = json.loads(json.dumps(manifeste))
        double["fichiers"]["test.parquet"]["runs"].append(manifeste["fichiers"]["train.parquet"]["runs"][0])
        self.assertTrue(any("figure dans" in e for e in decoupage.verifier_contre_le_manifeste(double)))
        manquant = json.loads(json.dumps(manifeste))
        manquant["runs"] = manquant["runs"][1:]
        self.assertTrue(any("différents" in e for e in decoupage.verifier_contre_le_manifeste(manquant)))
        range_ailleurs = json.loads(json.dumps(manifeste))
        range_ailleurs["runs"][0]["ensemble"] = "test"
        self.assertTrue(any("le manifeste le range" in e for e in decoupage.verifier_contre_le_manifeste(range_ailleurs)))


class TestDecoupageTemporel(unittest.TestCase):
    INSTANTS = [i * MINUTE for i in range(1000)]

    def test_l_ordre_du_temps_est_respecte_avec_le_delai_de_garde(self):
        p = decoupage.decouper_dans_l_ordre_du_temps(self.INSTANTS, horizon_min=15)
        t = self.INSTANTS
        garde = 15 * MINUTE
        self.assertLess(max(t[i] for i in p["train"]) + garde, min(t[i] for i in p["validation"]))
        self.assertLess(max(t[i] for i in p["validation"]) + garde, min(t[i] for i in p["test"]))

    def test_aucune_ligne_dans_deux_parties_et_aucune_perdue(self):
        p = decoupage.decouper_dans_l_ordre_du_temps(self.INSTANTS)
        tous = [i for indices in p.values() for i in indices]
        self.assertEqual(sorted(tous), list(range(1000)))
        self.assertEqual(len(tous), len(set(tous)))

    def test_les_proportions(self):
        p = decoupage.decouper_dans_l_ordre_du_temps(self.INSTANTS, horizon_min=15)
        self.assertEqual(len(p["test"]), 150)
        self.assertEqual(len(p["ecartes"]), 30)  # 15 minutes écartées avant chacune des deux bornes
        self.assertEqual(len(p["train"]) + len(p["validation"]), 1000 - 150 - 30)

    def test_la_reponse_d_une_ligne_n_entre_pas_dans_la_partie_suivante(self):
        """C'est le but du délai : la valeur à prévoir d'une ligne d'entraînement n'est jamais une valeur de la validation."""
        t = self.INSTANTS
        p = decoupage.decouper_dans_l_ordre_du_temps(t, horizon_min=15)
        premiere_validation = min(t[i] for i in p["validation"])
        self.assertTrue(all(t[i] + 15 * MINUTE < premiere_validation for i in p["train"]))

    def test_sans_delai_la_reponse_fuirait(self):
        """Contre-épreuve : avec un horizon nul, des lignes d'entraînement ont leur réponse (15 min plus tard) en validation."""
        t = self.INSTANTS
        p = decoupage.decouper_dans_l_ordre_du_temps(t, horizon_min=0)
        premiere_validation = min(t[i] for i in p["validation"])
        self.assertTrue(any(t[i] + 15 * MINUTE >= premiere_validation for i in p["train"]))
        self.assertEqual(p["ecartes"], [])

    def test_reproductible_et_independant_de_l_ordre_d_entree(self):
        a = decoupage.decouper_dans_l_ordre_du_temps(self.INSTANTS)
        b = decoupage.decouper_dans_l_ordre_du_temps(self.INSTANTS)
        self.assertEqual(a, b)
        self.assertEqual(decoupage.empreinte_des_indices(a), decoupage.empreinte_des_indices(b))
        ordre = list(range(1000))
        random.Random(7).shuffle(ordre)
        melange = [self.INSTANTS[i] for i in ordre]
        c = decoupage.decouper_dans_l_ordre_du_temps(melange)
        for partie in ("train", "validation", "test", "ecartes"):
            self.assertEqual(sorted(melange[i] for i in c[partie]), sorted(self.INSTANTS[i] for i in a[partie]), partie)

    def test_l_empreinte_change_avec_le_decoupage(self):
        a = decoupage.empreinte_des_indices(decoupage.decouper_dans_l_ordre_du_temps(self.INSTANTS, horizon_min=15))
        b = decoupage.empreinte_des_indices(decoupage.decouper_dans_l_ordre_du_temps(self.INSTANTS, horizon_min=5))
        self.assertNotEqual(a, b)

    def test_plusieurs_series_au_meme_instant_vont_dans_la_meme_partie(self):
        instants = [i * MINUTE for i in range(200) for _ in range(3)]  # trois tronçons, mêmes minutes
        p = decoupage.decouper_dans_l_ordre_du_temps(instants, horizon_min=5)
        parties = {}
        for nom in ("train", "validation", "test", "ecartes"):
            for i in p[nom]:
                parties.setdefault(instants[i], set()).add(nom)
        self.assertTrue(all(len(v) == 1 for v in parties.values()))

    def test_arguments_invalides(self):
        for parts in ((0.7, 0.2, 0.2), (0.5, 0.5), (0.0, 0.5, 0.5), (-0.1, 0.6, 0.5)):
            with self.assertRaises(ValueError):
                decoupage.decouper_dans_l_ordre_du_temps(self.INSTANTS, parts)
        with self.assertRaises(ValueError):
            decoupage.decouper_dans_l_ordre_du_temps(self.INSTANTS, horizon_min=-1)
        with self.assertRaises(ValueError):
            decoupage.decouper_dans_l_ordre_du_temps(self.INSTANTS[:5])

    def test_plis_a_fenetre_croissante(self):
        t = self.INSTANTS
        plis = decoupage.plis_temporels(t, plis=3, horizon_min=15)
        self.assertEqual(len(plis), 3)
        tailles = [len(p["apprentissage"]) for p in plis]
        self.assertEqual(tailles, sorted(tailles))
        for p in plis:
            debut_validation = min(t[i] for i in p["validation"])
            self.assertTrue(all(t[i] + 15 * MINUTE < debut_validation for i in p["apprentissage"]))
            self.assertFalse(set(p["apprentissage"]) & set(p["validation"]))
        blocs = [set(p["validation"]) for p in plis]
        self.assertFalse(blocs[0] & blocs[1] or blocs[1] & blocs[2])
        self.assertLess(max(t[i] for i in plis[0]["validation"]), min(t[i] for i in plis[1]["validation"]))

    def test_le_premier_bloc_n_est_jamais_valide_et_les_plis_se_refont(self):
        plis = decoupage.plis_temporels(self.INSTANTS, plis=3)
        premier_bloc_fin = self.INSTANTS[round(1000 / 4)]
        self.assertTrue(all(self.INSTANTS[i] >= premier_bloc_fin for p in plis for i in p["validation"]))
        self.assertEqual(plis, decoupage.plis_temporels(self.INSTANTS, plis=3))

    def test_plis_arguments_invalides(self):
        for kwargs in ({"plis": 0}, {"horizon_min": -5}):
            with self.assertRaises(ValueError):
                decoupage.plis_temporels(self.INSTANTS, **kwargs)
        with self.assertRaises(ValueError):
            decoupage.plis_temporels(self.INSTANTS[:20], plis=3)


class TestLecture(unittest.TestCase):
    def test_le_test_est_ferme_par_defaut(self):
        with self.assertRaises(donnees.EnsembleReserve):
            donnees.charger("test", Path("n'importe/où"))

    def test_ensemble_inconnu(self):
        with self.assertRaises(ValueError):
            donnees.charger("autre", Path("n'importe/où"))

    def test_la_meme_exception_pour_les_deux_lecteurs(self):
        from mesures import reference

        self.assertIs(reference.EnsembleReserve, donnees.EnsembleReserve)


@unittest.skipUnless(JEU_PRESENT, "jeu v1 absent : python3 ml/src/construire_jeu.py")
class TestSurLeJeu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train = donnees.charger("train")
        cls.validation = donnees.charger("validation")
        cls.tout = cls.train + cls.validation

    def test_tous_les_controles_passent(self):
        for nom, controle in (("historique", controles.controle_historique), ("avenir", controles.controle_aucune_dependance_au_futur),
                              ("réponses", controles.controle_reponses), ("calendrier", controles.controle_calendrier),
                              ("minutes", controles.controle_ordre_et_unicite)):
            self.assertEqual(controle(self.tout), [], nom)

    def test_les_runs_lus_sont_ceux_du_decoupage(self):
        par = cat.par_ensemble()
        self.assertEqual({ligne["run_id"] for ligne in self.train}, {r.run_id for r in par[cat.TRAIN]})
        self.assertEqual({ligne["run_id"] for ligne in self.validation}, {r.run_id for r in par[cat.VALIDATION]})

    def test_aucun_run_commun_entre_les_fichiers_lus(self):
        self.assertFalse({ligne["run_id"] for ligne in self.train} & {ligne["run_id"] for ligne in self.validation})
        self.assertFalse({ligne["seed"] for ligne in self.train} & {ligne["seed"] for ligne in self.validation})

    def test_un_defaut_injecte_dans_l_historique_est_vu(self):
        abime = [dict(ligne) for ligne in self.validation]
        i = next(k for k, ligne in enumerate(abime) if ligne["speed_ratio_lag1"] is not None)
        abime[i]["speed_ratio_lag1"] += 0.25
        self.assertEqual(len(controles.controle_historique(abime)), 1)

    def test_une_fuite_du_futur_injectee_est_vue(self):
        """Une variable décalée qui lirait la minute **suivante** au lieu de la précédente ne passe pas le contrôle."""
        par_serie = donnees.par_serie(self.validation)
        abime = []
        for serie in par_serie.values():
            for ligne, suivante in zip(serie, serie[1:] + [serie[-1]], strict=True):
                copie = dict(ligne)
                copie["speed_ratio_lag1"] = suivante["speed_ratio"]
                abime.append(copie)
        self.assertTrue(controles.controle_historique(abime))

    def test_une_reponse_decalee_est_vue(self):
        abime = [dict(ligne) for ligne in self.validation]
        i = next(k for k, ligne in enumerate(abime) if ligne["speed_ratio_h15"] is not None)
        abime[i]["speed_ratio_h15"] += 0.3
        self.assertEqual(len(controles.controle_reponses(abime)), 1)

    def test_le_detecteur_de_dependance_au_futur_voit_un_calcul_qui_regarde_devant(self):
        original = historique.valeur_decalee
        try:
            historique.valeur_decalee = lambda serie, minute, k: serie.get(minute + k)  # défaut : regarde devant
            self.assertTrue(controles.controle_aucune_dependance_au_futur(self.validation))
        finally:
            historique.valeur_decalee = original
        self.assertEqual(controles.controle_aucune_dependance_au_futur(self.validation), [])

    def test_le_calendrier_modifie_est_vu(self):
        abime = [dict(ligne) for ligne in self.validation]
        abime[0]["hour_of_day"] = (abime[0]["hour_of_day"] + 1) % 24
        self.assertEqual(len(controles.controle_calendrier(abime)), 1)

    def test_un_trou_dans_une_serie_est_vu(self):
        serie = [ligne for ligne in self.validation if ligne["run_id"] == self.validation[0]["run_id"]]
        troue = [ligne for k, ligne in enumerate(serie) if k != 3]
        self.assertTrue(controles.controle_ordre_et_unicite(troue))

    def test_la_preparation_complete_de_la_detection(self):
        usage = variables.DETECTION
        runs_train = {r.run_id for r in cat.par_ensemble()[cat.TRAIN]}
        p = ajustement.Preparation(usage).ajuster(self.train, runs_permis=runs_train)
        x_train, y_train = p.transformer(self.train, imputer=True)
        x_val, y_val = p.transformer(self.validation, imputer=True)
        self.assertEqual((len(x_train), len(x_val)), (len(self.train), len(self.validation)))
        self.assertTrue(all(len(rang) == len(p.noms()) for rang in x_train[:50] + x_val[:50]))
        self.assertFalse(ajustement.contient_nan(x_train) or ajustement.contient_nan(x_val))
        self.assertEqual(set(y_train) | set(y_val), {"FREE_FLOW", "SLOW", "CONGESTED"})
        # la validation à l'ajustement est refusée
        with self.assertRaises(ajustement.FuiteDInformation):
            ajustement.Preparation(usage).ajuster(self.train + self.validation, runs_permis=runs_train)

    def test_la_preparation_est_reproductible(self):
        usage = variables.DETECTION
        a = ajustement.Preparation(usage).ajuster(self.train).parametres()
        b = ajustement.Preparation(usage).ajuster(list(reversed(self.train))).parametres()
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_la_prevision_ecarte_les_fins_de_run_et_garde_le_reste(self):
        usage = variables.prevision(15)
        p = ajustement.Preparation(usage).ajuster(self.train)
        x, y = p.transformer(self.validation, imputer=True)
        sans_reponse = sum(1 for ligne in self.validation if ligne["speed_ratio_h15"] is None)
        self.assertEqual(len(x), len(self.validation) - sans_reponse)
        self.assertGreater(sans_reponse, 0)

    def test_le_decoupage_temporel_sur_un_run_du_jeu(self):
        serie = next(iter(donnees.par_serie(self.train).values()))
        instants = [donnees.minute(ligne) * MINUTE for ligne in serie]
        p = decoupage.decouper_dans_l_ordre_du_temps(instants, horizon_min=15)
        self.assertEqual(sum(len(v) for v in p.values()), len(serie))
        self.assertTrue(p["train"] and p["validation"] and p["test"])


@unittest.skipUnless(JEU_PRESENT, "jeu v1 absent : python3 ml/src/construire_jeu.py")
class TestCommande(unittest.TestCase):
    def test_la_commande_rend_zero_sur_le_jeu_v1_et_ecrit_un_rapport(self):
        sortie = StringIO()
        with redirect_stdout(sortie):
            code = main(["--json"])
        self.assertEqual(code, 0)
        rapport = json.loads(sortie.getvalue())
        self.assertEqual(rapport["empreinte_du_decoupage"], decoupage.empreinte_du_decoupage())
        self.assertEqual(len(rapport["controles"]), 11)
        self.assertTrue(all(v == [] for v in rapport["controles"].values()))

    def test_un_jeu_absent_donne_le_code_1(self):
        with tempfile.TemporaryDirectory() as vide, redirect_stderr(StringIO()) as erreur:
            self.assertEqual(main(["--jeu", vide]), 1)
        self.assertIn("construire_jeu.py", erreur.getvalue())

    def test_un_fichier_altere_donne_le_code_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            copie = Path(tmp)
            for nom in ("manifest.json", "train.parquet", "validation.parquet"):
                (copie / nom).write_bytes((VERSIONNE / nom).read_bytes())
            octets = bytearray((copie / "validation.parquet").read_bytes())
            octets[100] ^= 0xFF
            (copie / "validation.parquet").write_bytes(bytes(octets))
            sortie, erreur = StringIO(), StringIO()
            with redirect_stdout(sortie), redirect_stderr(erreur):
                try:
                    code = main(["--jeu", str(copie)])
                except Exception:  # noqa: BLE001 : le fichier abîmé peut aussi faire échouer la lecture
                    code = 1
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
