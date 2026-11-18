"""Prototype SUMO (IA-11) : entrées, export au format des événements v0, rejeu, comparaison, lanceur Docker, image.

Aucun test ne lance Docker ni SUMO (l'essai réel se joue avec `dev.py ml-sumo simuler` ; un test facultatif le fait si
`NOVARIA_SUMO=1` et que l'image existe). Les sorties de SUMO sont ici des fichiers XML écrits à la main, au format de la
version 1.28.0 (relevé sur un vrai run), dont le résultat attendu se calcule de tête.
"""

import json
import os
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from tests import support

from jeu_entrainement.simulation import importer_le_simulateur
from prototype_sumo import IMAGE, comparaison, execution, exporter, rejeu, reseau

try:
    import jsonschema  # noqa: F401
    import referencing  # noqa: F401

    CONTRATS = True
except ImportError:
    CONTRATS = False

DEBUT = datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
E1 = '<?xml version="1.0" encoding="UTF-8"?>\n<detector>\n{}</detector>\n'
LIGNE_E1 = '    <interval begin="{b}" end="{e}" id="{i}" nVehContrib="{n}" flow="0.00" occupancy="{o}" speed="{v}" harmonicMeanSpeed="-1.00" length="-1.00" nVehEntered="{n}"/>\n'
LIGNE_E2 = '    <interval begin="{b}" end="{e}" id="{i}" sampledSeconds="1.0" nVehEntered="0" maxJamLengthInMeters="{f}"/>\n'


def ecrire_sorties(dossier: Path, e1: list[tuple], e2: list[tuple]) -> None:
    (dossier / "e1.xml").write_text(E1.format("".join(LIGNE_E1.format(b=fin - 10, e=fin, i=i, n=n, o=o, v=v) for fin, i, n, o, v in e1)), encoding="utf-8")
    (dossier / "e2.xml").write_text(E1.format("".join(LIGNE_E2.format(b=fin - 10, e=fin, i=i, f=f) for fin, i, f in e2)), encoding="utf-8")


class Entrees(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self._tmp.name)
        self.fichiers = reseau.ecrire(self.dossier, debut_s=6 * 3600, duree_s=3600, graine=7)

    def tearDown(self):
        self._tmp.cleanup()

    def test_tous_les_fichiers_sont_du_xml_bien_forme(self):
        for chemin in self.fichiers.values():
            ET.parse(chemin)

    def test_le_carrefour_reprend_int_01_du_reseau_v0(self):
        aretes = ET.parse(self.fichiers["edges.edg.xml"]).getroot().findall("edge")
        self.assertEqual(sorted(a.get("id") for a in aretes), sorted(f"{x}_{s}" for x in "NESW" for s in ("in", "out")))
        for a in aretes:
            self.assertEqual((a.get("numLanes"), a.get("speed")), ("2", "13.889"))  # 2 voies, 50 km/h

    def test_un_detecteur_de_boucle_et_de_zone_par_voie_toutes_les_10_s(self):
        racine = ET.parse(self.fichiers["detectors.add.xml"]).getroot()
        boucles, zones = racine.findall("inductionLoop"), racine.findall("laneAreaDetector")
        self.assertEqual((len(boucles), len(zones)), (8, 8))
        self.assertTrue(all(d.get("period") == "10" for d in (*boucles, *zones)))
        self.assertEqual({b.get("lane") for b in boucles}, {f"{x}_in_{k}" for x in "NESW" for k in (0, 1)})

    def test_la_graine_et_la_duree_sont_dans_la_configuration(self):
        racine = ET.parse(self.fichiers["run.sumocfg"]).getroot()
        self.assertEqual(racine.find("random_number/seed").get("value"), "7")
        self.assertEqual(racine.find("time/end").get("value"), "3600")

    def test_la_demande_est_celle_du_v0_pour_chaque_pas_de_10_minutes(self):
        flux = ET.parse(self.fichiers["flows.rou.xml"]).getroot().findall("flow")
        self.assertEqual(len(flux), 6 * 4 * 3)  # 6 pas, 4 approches, 3 mouvements
        total_approche_n = sum(float(re.search(r"exp\(([\d.]+)\)", f.get("period")).group(1)) for f in flux if f.get("id").startswith("f_N_") and f.get("id").endswith("_00"))
        attendu = reseau.debit_d_approche(6 * 3600, 300) / 3600
        self.assertAlmostEqual(total_approche_n, attendu, places=5)
        _, _, _, scenarios = importer_le_simulateur()
        self.assertAlmostEqual(reseau.debit_d_approche(0, 8 * 3600), scenarios.SCENARIOS["heure-de-pointe"].demand_scale * 1.0 * 1400, places=6)  # pic : 700 × 2 voies

    def test_la_capacite_mesuree_remplace_celle_du_v0_et_garde_la_forme_de_la_demande(self):
        pic = reseau.debit_d_approche(0, 8 * 3600, 855.0)
        creux = reseau.debit_d_approche(0, 3 * 3600, 855.0)
        self.assertAlmostEqual(pic, 855.0, places=6)
        self.assertAlmostEqual(creux / pic, reseau.debit_d_approche(0, 3 * 3600) / reseau.debit_d_approche(0, 8 * 3600), places=9)

    def test_les_parts_de_mouvements_font_un(self):
        self.assertAlmostEqual(sum(reseau.PARTS), 1.0)
        self.assertEqual({d for ds in reseau.DESTINATIONS.values() for d in ds}, set("NESW"))
        for origine, ds in reseau.DESTINATIONS.items():
            self.assertNotIn(origine, ds)

    def test_un_debit_constant_pour_l_essai_de_saturation(self):
        with tempfile.TemporaryDirectory() as d:
            fichiers = reseau.ecrire(Path(d), debut_s=0, duree_s=1200, debit_constant_vph=3000)
            periodes = {re.search(r"exp\(([\d.]+)\)", f.get("period")).group(1) for f in ET.parse(fichiers["flows.rou.xml"]).getroot().findall("flow")}
        self.assertEqual(len(periodes), 2)  # 70 % en tout droit, 15 % à gauche et 15 % à droite : deux valeurs, les mêmes à chaque pas


class Export(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self._tmp.name)
        # approche N, deux voies, trois intervalles (le premier se termine à 0 : jamais exporté)
        e1 = [(0, "e1_N_0", 0, "0.00", "-1.00"), (0, "e1_N_1", 0, "0.00", "-1.00"),
              (10, "e1_N_0", 2, "10.00", "10.00"), (10, "e1_N_1", 4, "30.00", "5.00"),
              (20, "e1_N_0", 0, "100.00", "-1.00"), (20, "e1_N_1", 0, "100.00", "-1.00"),
              (30, "e1_N_0", 3, "5.00", "-1.00"), (30, "e1_N_1", 0, "0.00", "-1.00"),
              (10, "e1_E_0", 1, "2.00", "8.00"), (10, "e1_E_1", 0, "0.00", "-1.00")]
        e2 = [(10, "e2_N_0", 0.0), (10, "e2_N_1", 12.5), (20, "e2_N_0", 40.0), (20, "e2_N_1", 25.0), (10, "e2_E_0", 0.0)]
        ecrire_sorties(self.dossier, e1, e2)
        self.evenements = exporter.evenements(self.dossier, debut=DEBUT, graine=42)

    def tearDown(self):
        self._tmp.cleanup()

    def trouver(self, capteur, secondes):
        instant = int(DEBUT.timestamp()) + secondes
        return next(e for e in self.evenements if e["data"]["sensor_id"] == capteur and e["id"].endswith(f":{instant * 1000}"))

    def test_comptage_vitesse_ponderee_occupation_et_file(self):
        d = self.trouver("SENSOR_001", 10)["data"]  # approche N de INT_01
        self.assertEqual(d["vehicle_count"], 6)
        self.assertEqual(d["average_speed_kmh"], round((2 * 10.0 + 4 * 5.0) / 6 * 3.6, 1))  # 2 véhicules à 10 m/s, 4 à 5 m/s
        self.assertEqual(d["occupancy_rate"], 0.2)  # (10 % + 30 %) / 2
        self.assertEqual(d["queue_length_m"], 12.5)  # la plus grande file des deux voies

    def test_sans_vehicule_la_vitesse_est_absente_et_l_occupation_dit_l_arret(self):
        d = self.trouver("SENSOR_001", 20)["data"]
        self.assertEqual((d["vehicle_count"], d["average_speed_kmh"], d["occupancy_rate"], d["queue_length_m"]), (0, None, 1.0, 40.0))
        self.assertEqual(d["quality"], {"status": "VALID"})

    def test_des_vehicules_sans_vitesse_donnent_une_mesure_partielle(self):
        d = self.trouver("SENSOR_001", 30)["data"]
        self.assertEqual((d["vehicle_count"], d["average_speed_kmh"]), (3, None))
        self.assertEqual(d["quality"], {"status": "PARTIAL", "flags": ["MISSING_SPEED"]})

    def test_l_intervalle_qui_se_termine_a_zero_n_est_pas_exporte(self):
        self.assertEqual(min(e["time"] for e in self.evenements), "2026-10-20T06:00:10Z")
        self.assertEqual(len(self.evenements), 4)

    def test_enveloppe_et_provenance(self):
        e = self.evenements[0]
        self.assertEqual(e["source"], "sumo/sumo-int01-pointe-s42")
        self.assertEqual(e["type"], "novaria.iot.measurement.v1")
        self.assertEqual(e["data"]["provenance"], {"source_type": "SIMULATED", "run_id": "sumo-int01-pointe-s42", "scenario_id": "sumo-carrefour-int01-pointe", "seed": 42})
        self.assertEqual(e["data"]["interval_s"], 10)
        self.assertEqual(e["id"], f"sumo-int01-pointe-s42:SENSOR_001:{int(DEBUT.timestamp() + 10) * 1000}")

    def test_les_quatre_approches_sont_les_capteurs_1_a_4_de_int_01(self):
        _, reseau_v0, _, _ = importer_le_simulateur()
        attendu = {s.approach: s.sensor_id for s in reseau_v0.SEGMENTS if s.intersection_id == "INT_01"}
        self.assertEqual(attendu, {"N": "SENSOR_001", "E": "SENSOR_002", "S": "SENSOR_003", "W": "SENSOR_004"})
        self.assertEqual(self.trouver("SENSOR_002", 10)["data"]["road_segment_id"], "ROAD_002")

    def test_tries_par_instant_puis_par_approche(self):
        cles = [(e["time"], e["data"]["sensor_id"]) for e in self.evenements]
        self.assertEqual(cles, sorted(cles))

    @unittest.skipUnless(CONTRATS, "pip install jsonschema referencing")
    def test_chaque_evenement_respecte_les_contrats(self):
        import sys

        sys.path.insert(0, str(support.RACINE / "contracts"))
        import validate_events

        for e in self.evenements:
            self.assertEqual(validate_events.validate_event(e), [], e["id"])

    def test_le_manifeste_porte_les_empreintes_et_dit_qu_il_n_y_a_pas_de_verite_terrain(self):
        for nom in ("net.net.xml", "flows.rou.xml", "detectors.add.xml", "run.sumocfg"):
            (self.dossier / nom).write_text("<x/>", encoding="utf-8")
        manifeste = exporter.ecrire(self.dossier, debut_s=6 * 3600, graine=42)
        self.assertEqual(manifeste["messages"], 4)
        self.assertIn("mesures.jsonl", manifeste["fichiers"])
        self.assertRegex(manifeste["fichiers"]["mesures.jsonl"], r"^[0-9a-f]{64}$")
        self.assertIn("aucune", manifeste["verite_terrain"])
        lignes = (self.dossier / "mesures.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lignes), 4)
        self.assertEqual(json.loads(lignes[0])["source"], "sumo/sumo-int01-pointe-s42")
        self.assertEqual(exporter.ecrire(self.dossier, debut_s=6 * 3600, graine=42)["fichiers"], manifeste["fichiers"])  # déterministe


def evenements_complets(minutes=3, run="sumo-int01-pointe-s9", comptage=3, vitesse=30.0):
    """Six mesures par minute et par approche, comme un vrai run."""
    _, reseau_v0, _, _ = importer_le_simulateur()
    from novaria_sim import events

    segments = [s for s in reseau_v0.SEGMENTS if s.intersection_id == "INT_01"]
    sortie = []
    for k in range(1, minutes * 6 + 1):
        for s in segments:
            e = events.build_event(run_id=run, scenario_id="sumo-carrefour-int01-pointe", seed=9, segment=s, instant=DEBUT.replace(minute=0) + __import__("datetime").timedelta(seconds=10 * k),
                                   vehicle_count=comptage, speed_kmh=vitesse, occupancy_rate=0.1, queue_length_m=5.0, quality_block=events.quality("VALID", []))
            e["source"] = f"sumo/{run}"
            sortie.append(e)
    return sortie


class Rejeu(unittest.TestCase):
    def test_un_run_complet_est_accepte_sans_ecart_et_les_vehicules_sont_conserves(self):
        evenements = evenements_complets(minutes=4)
        bilan = rejeu.rejouer_moteur(evenements)
        self.assertEqual(bilan["ecarts"], [])
        self.assertEqual((bilan["messages"], bilan["mesures_acceptees"], bilan["fenetres_1_minute"]), (96, 96, 16))
        self.assertEqual(bilan["vehicules"], 96 * 3)

    def test_une_mesure_manquante_est_signalee(self):
        evenements = evenements_complets(minutes=3)
        del evenements[17]
        bilan = rejeu.rejouer_moteur(evenements)
        self.assertTrue(any("mesures" in e for e in bilan["ecarts"]), bilan["ecarts"])

    def test_charger_relit_les_lignes_du_fichier(self):
        with tempfile.TemporaryDirectory() as d:
            evenements = evenements_complets(minutes=1)
            (Path(d) / "mesures.jsonl").write_text("".join(json.dumps(e) + "\n" for e in evenements), encoding="utf-8")
            self.assertEqual(rejeu.charger(Path(d)), evenements)

    def test_la_pile_recoit_les_evenements_par_lots_et_l_entrepot_est_relu(self):
        evenements = evenements_complets(minutes=2)
        import sys

        sys.path.insert(0, str(support.RACINE / "scripts" / "dev"))
        pile = mock.Mock()
        pile.envoyer.side_effect = lambda lot: ["ACCEPTED"] * len(lot)
        moteur = rejeu.rejouer_moteur(evenements)["fenetres"]
        lues = [[route, datetime.fromtimestamp(debut / 1000, UTC).strftime("%Y-%m-%d %H:%M:%S"), str(w.vehicle_count), str(w.sample_count), str(w.average_speed_kmh)]
                for (route, debut), w in moteur.items()]
        pile.psql.side_effect = [[["8", "144"]], lues]
        with tempfile.TemporaryDirectory() as d, mock.patch("parcours.Pile", return_value=pile), mock.patch.object(rejeu, "RACINE", Path(d)):
            (Path(d) / ".env").write_text("# commentaire\nCOLLECTE_PORT=8001\nGATEWAY_PORT='8000'\n", encoding="utf-8")
            bilan = rejeu.rejouer_pile(evenements, moteur, delai_attente_s=1, progres=lambda _: None)
        self.assertEqual(bilan["statuts_de_la_collecte"], {"ACCEPTED": 48})
        self.assertEqual((bilan["fenetres_attendues_dans_l_entrepot"], bilan["fenetres_dans_l_entrepot"], bilan["vehicules_dans_l_entrepot"]), (8, 8, 144))
        self.assertEqual(bilan["fenetres_retenues_sans_vitesse"], [])
        self.assertEqual(bilan["ecarts_avec_le_moteur"], [])
        self.assertIn("SELECT", pile.psql.call_args_list[0].args[0])

    def test_une_fenetre_differente_ou_absente_de_l_entrepot_est_un_ecart(self):
        moteur = rejeu.rejouer_moteur(evenements_complets(minutes=2))["fenetres"]
        (route, debut), w = next(iter(moteur.items()))
        texte = datetime.fromtimestamp(debut / 1000, UTC).strftime("%Y-%m-%d %H:%M:%S")
        bonne = [route, texte, str(w.vehicle_count), str(w.sample_count), str(w.average_speed_kmh)]
        faux = [route, texte, str(w.vehicle_count + 1), str(w.sample_count), str(w.average_speed_kmh)]
        self.assertEqual(rejeu._ecarts_entrepot([bonne], {(route, debut): w}), ([], []))
        self.assertEqual(len(rejeu._ecarts_entrepot([faux], {(route, debut): w})[0]), 1)
        self.assertEqual(len(rejeu._ecarts_entrepot([], {(route, debut): w})[0]), 1)  # la fenêtre a une vitesse : elle devait être chargée
        self.assertEqual(len(rejeu._ecarts_entrepot([bonne], {})[0]), 1)

    def test_une_minute_sans_vehicule_retenue_par_le_flux_n_est_pas_un_ecart(self):
        vide = evenements_complets(minutes=2, comptage=0)
        for e in vide:
            e["data"]["average_speed_kmh"] = None
            e["data"]["occupancy_rate"] = 1.0  # file arrêtée sur la boucle : aucun véhicule ne passe
        moteur = rejeu.rejouer_moteur(vide)["fenetres"]
        ecarts, retenues = rejeu._ecarts_entrepot([], moteur)
        self.assertEqual(ecarts, [])
        self.assertEqual(len(retenues), len(moteur))
        self.assertIn("0 véhicule", retenues[0])


class Comparaison(unittest.TestCase):
    def test_la_regle_de_seuils_annonce_un_etat_par_minute(self):
        fluide = [(60_000 * k, 10, 0.95, 0.0, 0.1) for k in range(10)]
        saturee = fluide[:3] + [(60_000 * k, 10, 0.2, 100.0, 0.9) for k in range(3, 12)]
        self.assertEqual(set(comparaison.etats(fluide)), {"FREE_FLOW"})
        self.assertIn("CONGESTED", comparaison.etats(saturee))

    def test_le_resume_compte_les_minutes_et_les_etats(self):
        bilan = rejeu.rejouer_moteur(evenements_complets(minutes=35, vitesse=48.0))
        r = comparaison.resume(bilan["fenetres"])
        self.assertEqual(r["minutes"], 4 * 35)
        self.assertAlmostEqual(r["ratio_vitesse_moyen"], 0.96, places=2)
        self.assertEqual(r["etats"]["FREE_FLOW"], 1.0)
        self.assertEqual(len(r["tranches"]), 2)
        self.assertAlmostEqual(r["vehicules_par_minute_moyen"], 18.0)

    def test_la_correlation_de_deux_profils_identiques_est_un_et_celle_d_un_profil_inverse_moins_un(self):
        self.assertAlmostEqual(comparaison.correlation([1, 2, 3, 4], [2, 4, 6, 8]), 1.0)
        self.assertAlmostEqual(comparaison.correlation([1, 2, 3, 4], [8, 6, 4, 2]), -1.0)
        self.assertIsNone(comparaison.correlation([1, 2, 3, 4], [5, 5, 5, 5]))  # un profil plat : corrélation non définie, pas d'exception


class Lanceur(unittest.TestCase):
    def test_docker_absent_donne_un_message_clair(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(execution.DockerAbsent, "introuvable"):
                execution.image_presente()

    def test_sans_image_le_lancement_dit_quoi_faire(self):
        with mock.patch.object(execution, "image_presente", return_value=False), tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(execution.DockerAbsent, "ml-sumo image"):
                execution.lancer(Path(d))

    def test_la_commande_monte_le_dossier_et_lance_netconvert_puis_sumo(self):
        with mock.patch.object(execution, "image_presente", return_value=True), tempfile.TemporaryDirectory() as d, \
                mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout="Success.\n", stderr="")) as run:
            self.assertEqual(execution.lancer(Path(d)), "Success.\n")
        commande = run.call_args.args[0]
        self.assertEqual(commande[:3], ["docker", "run", "--rm"])
        self.assertIn(IMAGE, commande)
        self.assertTrue(any(c.endswith(":/work") for c in commande))
        self.assertIn("netconvert", commande[-1])
        self.assertTrue(commande[-1].index("netconvert") < commande[-1].index("sumo -c"))

    def test_un_echec_de_sumo_remonte_sa_sortie(self):
        with mock.patch.object(execution, "image_presente", return_value=True), tempfile.TemporaryDirectory() as d, \
                mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="Error: réseau invalide")):
            with self.assertRaisesRegex(RuntimeError, "réseau invalide"):
                execution.lancer(Path(d))

    def test_une_construction_refusee_est_une_erreur_claire(self):
        with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="pull access denied")):
            with self.assertRaisesRegex(execution.DockerAbsent, "construction"):
                execution.construire_image()

    def test_l_identifiant_utilisateur_n_est_transmis_que_sous_linux(self):
        if hasattr(os, "getuid"):
            self.assertEqual(execution.utilisateur(), ["--user", f"{os.getuid()}:{os.getgid()}"])


class Image(unittest.TestCase):
    """Le Dockerfile et ses dépendances : épinglés, avec empreintes, non-root ; l'image ne fait pas partie de la pile."""

    def test_la_version_de_sumo_est_la_meme_partout(self):
        dossier = support.RACINE / "ml" / "sumo"
        verrou = (dossier / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("eclipse-sumo==1.28.0", verrou)
        self.assertTrue(IMAGE.endswith(":1.28.0"))
        self.assertGreaterEqual(verrou.count("--hash=sha256:"), 2)

    def test_le_dockerfile_exige_les_empreintes_et_n_est_pas_root(self):
        texte = (support.RACINE / "ml" / "sumo" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("--require-hashes", texte)
        self.assertRegex(texte, r"(?m)^USER sumo$")
        self.assertNotIn("COPY . ", texte)

    def test_l_image_n_est_pas_un_service_de_la_pile(self):
        compose = (support.RACINE / "compose.yaml").read_text(encoding="utf-8") if (support.RACINE / "compose.yaml").is_file() else ""
        self.assertNotIn("sumo", compose.lower())


class PointDEntree(unittest.TestCase):
    def test_les_etapes_et_leurs_codes_de_sortie(self):
        from prototype_sumo import __main__ as principal

        with mock.patch.object(execution, "construire_image") as construire, mock.patch("sys.stdout"):
            self.assertEqual(principal.main(["image"]), 0)
        construire.assert_called_once()
        with mock.patch.object(execution, "construire_image", side_effect=execution.DockerAbsent("docker absent")), mock.patch("sys.stderr"):
            self.assertEqual(principal.main(["image"]), 1)
        with mock.patch.object(principal, "simuler") as simuler, mock.patch("sys.stdout"):
            self.assertEqual(principal.main(["simuler", "--graine", "7"]), 0)
        simuler.assert_called_once_with(7)
        with mock.patch.object(principal, "calibrer", return_value=855.0) as calibrer, mock.patch("sys.stdout"):
            self.assertEqual(principal.main(["calibrer"]), 0)
        calibrer.assert_called_once()

    def test_rejouer_sans_run_est_refuse_et_avec_un_run_le_code_dit_les_ecarts(self):
        from prototype_sumo import __main__ as principal

        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(principal, "dossier_du_run", return_value=Path(d)), mock.patch("sys.stderr"):
                self.assertEqual(principal.main(["rejouer"]), 1)
            evenements = evenements_complets(minutes=2)
            (Path(d) / "mesures.jsonl").write_text("".join(json.dumps(e) + "\n" for e in evenements), encoding="utf-8")
            with mock.patch.object(principal, "dossier_du_run", return_value=Path(d)), mock.patch("sys.stdout"):
                self.assertEqual(principal.main(["rejouer"]), 0)
                with mock.patch.object(rejeu, "rejouer_pile", return_value={"ecarts_avec_le_moteur": [], "fenetres_dans_l_entrepot": 8, "fenetres_attendues_dans_l_entrepot": 8}):
                    self.assertEqual(principal.main(["rejouer", "--pile"]), 0)
                with mock.patch.object(rejeu, "rejouer_pile", return_value={"ecarts_avec_le_moteur": ["x"], "fenetres_dans_l_entrepot": 8, "fenetres_attendues_dans_l_entrepot": 8}):
                    self.assertEqual(principal.main(["rejouer", "--pile"]), 1)
                with mock.patch.object(rejeu, "rejouer_pile", return_value={"ecarts_avec_le_moteur": [], "fenetres_dans_l_entrepot": 7, "fenetres_attendues_dans_l_entrepot": 8}):
                    self.assertEqual(principal.main(["rejouer", "--pile"]), 1)

    def test_la_calibration_mesure_le_debit_de_sortie_sous_forte_demande(self):
        from prototype_sumo import __main__ as principal

        def faux_lancer(dossier, delai_s=900):
            lignes = "".join(LIGNE_E1.format(b=fin - 10, e=fin, i=f"e1_{a}_0", n=2, o="10.00", v="5.00") for a in "NESW" for fin in range(10, 3610, 10))
            (dossier / "e1.xml").write_text(E1.format(lignes), encoding="utf-8")
            (dossier / "e2.xml").write_text(E1.format(""), encoding="utf-8")
            return "Success."

        with mock.patch.object(execution, "lancer", side_effect=faux_lancer), mock.patch("sys.stdout"):
            capacite = principal.calibrer()
        # 2 véhicules toutes les 10 s pendant 3 000 s : 600 véhicules, divisés par 3000 / 3600 d'heure
        self.assertAlmostEqual(capacite, 600 / (3000 / 3600), places=6)


class Rapport(unittest.TestCase):
    def test_le_markdown_dit_le_rejeu_la_comparaison_et_la_sensibilite(self):
        from prototype_sumo import rapport

        bilan = rejeu.rejouer_moteur(evenements_complets(minutes=35, vitesse=48.0))
        resume = comparaison.resume(bilan["fenetres"])
        resultat = {"run": {"run_id": "sumo-int01-pointe-s42", "seed": 42, "messages": 8400}, "capacite_mesuree_vph": 855.0,
                    "rejeu_moteur": {k: v for k, v in bilan.items() if k != "fenetres"},
                    "comparaison": {"intersection": "INT_01", "sumo": resume, "v0": resume, "correlation_profil_de_demande": 0.5},
                    "variantes": [{"graine": 42, "position_e1_m": -10.0, "ecarts_au_rejeu": [], "etats": resume["etats"], "ratio_vitesse_moyen": 0.5,
                                   "ratio_vitesse_min": 0.1, "file_max_m": 280.0, "file_moyenne_m": 100.0, "vehicules_par_minute_moyen": 10.0}]}
        texte = rapport.markdown(resultat)
        for attendu in ("Rejeu dans le moteur de fenêtres", "SUMO contre le générateur v0", "Sensibilité", "graine 42, boucle à 10 m", "855", "aucun"):
            self.assertIn(attendu, texte)
        self.assertNotIn(str(support.RACINE), texte)

    def test_ecrire_produit_les_deux_fichiers_depuis_un_run(self):
        from prototype_sumo import rapport

        evenements = evenements_complets(minutes=35, vitesse=48.0)
        with tempfile.TemporaryDirectory() as d:
            dossier = Path(d) / "run"
            dossier.mkdir()
            (dossier / "mesures.jsonl").write_text("".join(json.dumps(e) + "\n" for e in evenements), encoding="utf-8")
            (dossier / "manifest.json").write_text(json.dumps({"run_id": "sumo-int01-pointe-s9", "seed": 9, "messages": len(evenements)}), encoding="utf-8")
            variante = {"graine": 43, "position_e1_m": -100.0, "ecarts_au_rejeu": [], "etats": {"FREE_FLOW": 1.0, "SLOW": 0.0, "CONGESTED": 0.0}, "ratio_vitesse_moyen": 0.9,
                        "ratio_vitesse_min": 0.5, "file_max_m": 10.0, "file_moyenne_m": 1.0, "vehicules_par_minute_moyen": 18.0}
            v0 = rejeu.rejouer_moteur(evenements)["fenetres"]
            with mock.patch.object(comparaison, "run_v0", return_value=v0), mock.patch.object(rapport, "_variante", return_value=variante), \
                    mock.patch.object(rapport, "GRAINES_VOISINES", (43,)):
                sortie_json, sortie_md = Path(d) / "s.json", Path(d) / "s.md"
                rapport.ecrire(dossier, sortie_json, sortie_md, progres=lambda _: None)
            self.assertEqual(json.loads(sortie_json.read_text(encoding="utf-8"))["rejeu_moteur"]["ecarts"], [])
            self.assertIn("Sensibilité", sortie_md.read_text(encoding="utf-8"))


@unittest.skipUnless(os.environ.get("NOVARIA_SUMO") == "1", "essai réel : NOVARIA_SUMO=1 et l'image construite (dev.py ml-sumo image)")
class EssaiReel(unittest.TestCase):
    def test_dix_minutes_de_sumo_donnent_des_evenements_conformes(self):
        if not execution.image_presente():
            self.skipTest("image absente")
        with tempfile.TemporaryDirectory(dir=support.RACINE / "var") as d:
            dossier = Path(d)
            reseau.ecrire(dossier, debut_s=6 * 3600, duree_s=600, graine=1, capacite_vph=reseau.CAPACITE_MESUREE_VEH_H)
            execution.lancer(dossier)
            manifeste = exporter.ecrire(dossier, debut_s=6 * 3600, graine=1)
            self.assertEqual(manifeste["messages"], 4 * 60)
            self.assertEqual(rejeu.rejouer_moteur(rejeu.charger(dossier))["ecarts"], [])


if __name__ == "__main__":
    unittest.main()
