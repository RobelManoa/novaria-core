"""Variables et réponses : vérité terrain pour le label, passé seul pour l'historique, avenir seul pour les réponses."""

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from tests import support
from tests.support import RACINE

from jeu_entrainement import catalogue as cat
from jeu_entrainement import fenetres, lignes, simulation

DEBUT = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
TRONCON = "ROAD_005"


def ms(minute: int) -> int:
    return int((DEBUT + timedelta(minutes=minute)).timestamp() * 1000)


def fausse_fenetre(vehicules, vitesse, occupation=0.1, echantillons=6):
    return SimpleNamespace(
        vehicle_count=vehicules, sample_count=echantillons,
        exact_average_speed=None if vitesse is None else Decimal(repr(vitesse)),
        exact_occupancy=Decimal(repr(occupation)), exact_max_queue=Decimal("0.0"),
    )


def faux_run(etats, run_id="t-faux", scenario="incident-ponctuel", seed=7):
    """Vérité terrain fabriquée : `etats[minute]` pour les six intervalles de chaque minute."""
    verite = []
    for minute, etat in enumerate(etats):
        for intervalle in range(6):
            fin = DEBUT + timedelta(minutes=minute, seconds=10 * (intervalle + 1))
            verite.append({"time": fin.strftime("%Y-%m-%dT%H:%M:%SZ"), "road_segment_id": TRONCON, "label_state": etat})
    return SimpleNamespace(config=SimpleNamespace(run_id=run_id, scenario_id=scenario, seed=seed), verite=verite)


def serie(vitesses):
    return {(TRONCON, ms(m)): fausse_fenetre(10 + m, v) for m, v in enumerate(vitesses)}


def en_dict(lignes_):
    return [dict(zip(lignes.NOMS, ligne, strict=True)) for ligne in lignes_]


class Colonnes(unittest.TestCase):
    def test_le_jeu_a_les_colonnes_de_la_section_9_du_dictionnaire(self):
        texte = (RACINE / "docs" / "03-donnees" / "dictionnaire-de-donnees.md").read_text(encoding="utf-8")
        section = texte[texte.index("## 9. Jeu d'entraînement") : texte.index("## 10.")]
        for colonne in lignes.NOMS:
            self.assertIn(f"`{colonne}`", section, f"{colonne} n'est pas dans la section 9 du dictionnaire")

    def test_les_groupes_du_dictionnaire_sont_tous_representes_dans_l_ordre(self):
        self.assertEqual(list(lignes.GROUPES), ["clé", "mesures", "historique", "calendrier", "tronçon", "réponses"])
        self.assertEqual(sum(len(g) for g in lignes.GROUPES.values()), len(lignes.COLONNES))
        self.assertEqual(len(set(lignes.NOMS)), len(lignes.NOMS))

    def test_les_colonnes_attendues_existent(self):
        for nom in ("run_id", "scenario_id", "seed", "road_segment_id", "window_start", "vehicle_count", "flow_veh_per_min",
                    "average_speed_kmh", "occupancy_rate", "max_queue_length_m", "speed_ratio", "speed_ratio_lag1", "speed_ratio_lag5",
                    "flow_lag1", "flow_lag5", "hour_of_day", "iso_day_of_week", "is_weekend", "is_holiday", "lane_count", "length_m",
                    "free_flow_speed_kmh", "road_type", "label_state", "speed_ratio_h5", "speed_ratio_h15"):
            self.assertIn(nom, lignes.NOMS)

    def test_les_colonnes_sans_valeur_absente_possible_sont_obligatoires(self):
        obligatoires = {c.nom for c in lignes.COLONNES if not c.facultative}
        for nom in ("run_id", "scenario_id", "seed", "road_segment_id", "window_start", "label_state", "vehicle_count", "road_type"):
            self.assertIn(nom, obligatoires)
        self.assertNotIn("speed_ratio", obligatoires)


class LabelDeLaVeriteTerrain(unittest.TestCase):
    def test_le_label_est_l_etat_voulu_meme_quand_les_mesures_diraient_autre_chose(self):
        """Des mesures de circulation fluide (ratio 0,95) sous un état voulu CONGESTED : le label reste CONGESTED."""
        rows = en_dict(lignes.lignes_du_run(faux_run(["CONGESTED"] * 3), serie([47.5, 47.5, 47.5]))[0])
        self.assertEqual([r["label_state"] for r in rows], ["CONGESTED"] * 3)
        self.assertEqual([r["speed_ratio"] for r in rows], [0.95] * 3)

    def test_changer_la_verite_terrain_change_le_label_et_rien_d_autre(self):
        mesures = serie([30.0, 30.0, 30.0])
        a = en_dict(lignes.lignes_du_run(faux_run(["FREE_FLOW"] * 3), mesures)[0])
        b = en_dict(lignes.lignes_du_run(faux_run(["SLOW", "CONGESTED", "SLOW"]), mesures)[0])
        self.assertEqual([r["label_state"] for r in a], ["FREE_FLOW"] * 3)
        self.assertEqual([r["label_state"] for r in b], ["SLOW", "CONGESTED", "SLOW"])
        sans_label = lambda r: {k: v for k, v in r.items() if k != "label_state"}  # noqa: E731
        self.assertEqual([sans_label(r) for r in a], [sans_label(r) for r in b])

    def test_le_code_du_jeu_n_utilise_aucune_regle_de_seuils(self):
        for fichier in (Path(support.RACINE_ML) / "src" / "jeu_entrainement").glob("*.py"):
            texte = fichier.read_text(encoding="utf-8")
            for interdit in ("app.flux.classifier", "app.flux.rules", "classify(", "THRESHOLD", "ENTER_", "EXIT_"):
                self.assertNotIn(interdit, texte, f"{fichier.name} fait appel à la règle de seuils ({interdit})")

    def test_une_minute_a_cheval_sur_un_changement_prend_l_etat_majoritaire(self):
        faux = faux_run(["FREE_FLOW"])
        faux.verite[-1]["label_state"] = "SLOW"  # le dernier intervalle de la minute change d'état
        self.assertEqual(lignes.lignes_du_run(faux, serie([40.0]))[1]["etats_melanges"], 1)
        self.assertEqual(en_dict(lignes.lignes_du_run(faux, serie([40.0]))[0])[0]["label_state"], "FREE_FLOW")

    def test_a_egalite_le_dernier_etat_gagne(self):
        self.assertEqual(lignes.etat_de_la_minute(["FREE_FLOW", "FREE_FLOW", "FREE_FLOW", "SLOW", "SLOW", "SLOW"]), "SLOW")
        self.assertEqual(lignes.etat_de_la_minute(["SLOW", "SLOW", "SLOW", "FREE_FLOW", "FREE_FLOW", "FREE_FLOW"]), "FREE_FLOW")

    def test_sur_un_vrai_run_les_etats_suivent_le_calendrier_du_scenario(self):
        spec = cat.RunSpec("t-vrai", "incident-ponctuel", 5, cat.TRAIN, "08:00", 3600)
        resultat = simulation.executer(spec)
        toutes, _ = fenetres.calculer(resultat)
        rows = en_dict(lignes.lignes_du_run(resultat, toutes)[0])
        incident = {r["window_start"].strftime("%H:%M"): r["label_state"] for r in rows if r["road_segment_id"] == "ROAD_005"}
        self.assertEqual(incident["08:05"], "FREE_FLOW")
        self.assertEqual(incident["08:20"], "CONGESTED")
        self.assertEqual(incident["08:40"], "SLOW")
        self.assertEqual(incident["08:55"], "FREE_FLOW")


class HistoriqueEtReponses(unittest.TestCase):
    VITESSES = [20.0 + 2 * m for m in range(25)]  # 25 minutes, vitesse croissante : le passé et l'avenir se distinguent

    def lignes(self):
        return en_dict(lignes.lignes_du_run(faux_run(["FREE_FLOW"] * 25), serie(self.VITESSES))[0])

    def test_une_ligne_par_minute_triee(self):
        rows = self.lignes()
        self.assertEqual(len(rows), 25)
        self.assertEqual([r["window_start"] for r in rows], sorted(r["window_start"] for r in rows))

    def test_les_retards_sont_le_passe_du_meme_troncon(self):
        rows = self.lignes()
        for m in (6, 12, 20):
            for k in range(1, 6):
                self.assertEqual(rows[m][f"speed_ratio_lag{k}"], rows[m - k]["speed_ratio"], (m, k))
                self.assertEqual(rows[m][f"flow_lag{k}"], rows[m - k]["flow_veh_per_min"], (m, k))

    def test_le_debut_du_run_n_a_pas_d_historique_inventé(self):
        rows = self.lignes()
        self.assertIsNone(rows[0]["speed_ratio_lag1"])
        self.assertIsNone(rows[0]["speed_ratio_ma5"])
        self.assertIsNone(rows[2]["speed_ratio_lag3"])
        self.assertIsNotNone(rows[2]["speed_ratio_lag2"])
        self.assertIsNotNone(rows[5]["speed_ratio_lag5"])

    def test_les_moyennes_mobiles_sont_celles_du_passe_sans_la_ligne(self):
        rows = self.lignes()
        for m in (8, 20):
            passe5 = [rows[m - k]["speed_ratio"] for k in range(1, 6)]
            self.assertAlmostEqual(rows[m]["speed_ratio_ma5"], sum(passe5) / 5, places=6)
        passe15 = [rows[20 - k]["speed_ratio"] for k in range(1, 16)]
        self.assertAlmostEqual(rows[20]["speed_ratio_ma15"], sum(passe15) / 15, places=6)
        self.assertNotEqual(rows[20]["speed_ratio_ma5"], rows[20]["speed_ratio"])

    def test_les_reponses_sont_l_avenir_du_meme_troncon(self):
        rows = self.lignes()
        for m in (0, 7, 19):
            self.assertEqual(rows[m]["speed_ratio_h5"], rows[m + 5]["speed_ratio"])
        self.assertEqual(rows[5]["speed_ratio_h15"], rows[20]["speed_ratio"])

    def test_la_fin_du_run_n_a_pas_de_reponse(self):
        rows = self.lignes()
        self.assertIsNone(rows[24]["speed_ratio_h5"])
        self.assertIsNone(rows[20]["speed_ratio_h5"])
        self.assertIsNotNone(rows[19]["speed_ratio_h5"])
        self.assertIsNone(rows[10]["speed_ratio_h15"])
        self.assertIsNotNone(rows[9]["speed_ratio_h15"])

    def test_aucune_variable_ne_depend_de_l_avenir(self):
        """On change une minute future : tout ce qui est avant garde les mêmes variables ; seules les réponses bougent."""
        base = self.lignes()
        vitesses = list(self.VITESSES)
        vitesses[15] = 49.9
        modifie = en_dict(lignes.lignes_du_run(faux_run(["FREE_FLOW"] * 25), serie(vitesses))[0])
        reponses = {"speed_ratio_h5", "speed_ratio_h15"}
        for m in range(15):
            self.assertEqual({k: v for k, v in base[m].items() if k not in reponses},
                             {k: v for k, v in modifie[m].items() if k not in reponses}, f"la ligne {m} dépend de la minute 15")
        self.assertNotEqual(base[10]["speed_ratio_h5"], modifie[10]["speed_ratio_h5"])
        self.assertNotEqual(base[16]["speed_ratio_lag1"], modifie[16]["speed_ratio_lag1"])

    def test_une_fenetre_manquante_donne_un_trou_et_pas_une_valeur(self):
        mesures = serie(self.VITESSES)
        del mesures[(TRONCON, ms(10))]
        rows = en_dict(lignes.lignes_du_run(faux_run(["FREE_FLOW"] * 25), mesures)[0])
        self.assertEqual(len(rows), 24)
        suivante = next(r for r in rows if r["window_start"] == DEBUT + timedelta(minutes=11))
        self.assertIsNone(suivante["speed_ratio_lag1"])
        self.assertIsNotNone(suivante["speed_ratio_lag2"])

    def test_une_route_vide_a_un_flux_nul_et_pas_de_vitesse(self):
        mesures = {(TRONCON, ms(0)): fausse_fenetre(0, None, 0.0, 6), (TRONCON, ms(1)): fausse_fenetre(4, 40.0)}
        rows = en_dict(lignes.lignes_du_run(faux_run(["FREE_FLOW"] * 2), mesures)[0])
        self.assertEqual((rows[0]["vehicle_count"], rows[0]["flow_veh_per_min"], rows[0]["average_speed_kmh"], rows[0]["speed_ratio"]), (0, 0.0, None, None))
        self.assertEqual(rows[1]["speed_ratio_lag1"], None)
        self.assertEqual(rows[1]["flow_lag1"], 0.0)


class CalendrierEtTroncon(unittest.TestCase):
    def test_calendrier_et_caracteristiques_du_troncon(self):
        row = en_dict(lignes.lignes_du_run(faux_run(["FREE_FLOW"]), serie([40.0]))[0])[0]
        self.assertEqual((row["hour_of_day"], row["iso_day_of_week"], row["is_weekend"], row["is_holiday"]), (8, 2, False, False))  # mardi
        self.assertEqual((row["lane_count"], row["length_m"], row["free_flow_speed_kmh"], row["road_type"]), (2, 300, 50.0, "ARTERIAL"))
        self.assertEqual((row["run_id"], row["scenario_id"], row["seed"], row["road_segment_id"]), ("t-faux", "incident-ponctuel", 7, TRONCON))

    def test_les_arrondis_sont_ceux_de_l_entrepot(self):
        self.assertEqual(lignes.arrondir(Decimal("0.0625"), 3), 0.063)  # moitié vers le haut (Python arrondirait au pair)
        self.assertEqual(lignes.arrondir(Decimal("45.25"), 1), 45.3)
        self.assertEqual(lignes.rapport_de_vitesse(Decimal("47.5"), 50.0), 0.95)
        self.assertEqual(lignes.rapport_de_vitesse(Decimal("900"), 50.0), 9.999)  # plafonné
        self.assertIsNone(lignes.rapport_de_vitesse(None, 50.0))


if __name__ == "__main__":
    unittest.main()
