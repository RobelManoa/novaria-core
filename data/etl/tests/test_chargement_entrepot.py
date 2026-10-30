"""Tests du chargement des fenêtres, du rejeu, du lot planifié et de l'empaquetage (DAT-06). Aucun accès au réseau.

    python -m unittest discover -s data/etl/tests

L'entrepôt est remplacé par un faux en mémoire qui garde la sémantique de la table : une ligne par clé primaire (tronçon,
début, taille, run_id), « insérer ou mettre à jour ». Le SQL réel est contrôlé contre la migration 0002 et, si
NOVARIA_TEST_POSTGRES_URL désigne une base migrée, exécuté pour de bon (classe `AvecPostgresReel`).
"""

import hashlib
import io
import os
import re
import sys
import tempfile
import tomllib
import unittest
import unittest.mock
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "data" / "etl"))

import echantillon_fenetres as ef  # noqa: E402
from pipelines import charger_entrepot as ce  # noqa: E402
from pipelines import empaqueter, lot, rejouer  # noqa: E402
from pipelines.sorties import ErreurSortie  # noqa: E402
from transforms import fenetres_trafic as ft  # noqa: E402
from transforms import paris_qualite as q  # noqa: E402

try:
    import psycopg
except ImportError:
    psycopg = None

REFERENTIELS = ft.Referentiels(
    segments={f"ROAD_{n:03d}" for n in range(1, 25)}, etats={"UNKNOWN", "FREE_FLOW", "SLOW", "CONGESTED"}, sources={"SIMULATED", "REAL_HISTORICAL"},
)
BASE = dict(zip(ef.ENTETE, ef.ligne(1, 1), strict=True))  # une fenêtre valide : ROAD_001 à 06:05, 13 véhicules
MAINTENANT = datetime(2026, 10, 30, 0, 30, tzinfo=UTC)


def brut(**champs) -> dict:
    return {**BASE, **champs}


def controler(**champs):
    return ft.Controleur(REFERENTIELS).traiter(1, brut(**champs))


class FauxEntrepot:
    """Table en mémoire, mêmes règles d'écriture que la vraie : une ligne par clé, la ligne identique n'est pas réécrite."""

    def __init__(self, references=REFERENTIELS):
        self.lignes: dict[tuple, tuple] = {}
        self.references = references
        self.fermee = False
        self.ecritures = 0

    def referentiels(self):
        return self.references

    def charger(self, run_id, lot_):
        avant = len(self.lignes)
        for f in lot_:
            valeurs = (f.source_type, f.vehicle_count, f.flow_veh_per_min, f.average_speed_kmh, f.occupancy_rate, f.max_queue_length_m,
                       f.speed_ratio, f.sample_count, f.expected_sample_count, f.congestion_state, f.classifier_version)
            if self.lignes.get((*f.grain, run_id)) != valeurs:
                self.ecritures += 1
                self.lignes[(*f.grain, run_id)] = valeurs
        return len(self.lignes) - avant

    def totaux(self, run_id):
        du_run = sorted((cle, valeurs) for cle, valeurs in self.lignes.items() if cle[3] == run_id)
        return ce.Totaux(len(du_run), sum(v[1] for _, v in du_run), str(sum((v[2] for _, v in du_run), Decimal(0))),
                         hashlib.md5(repr(du_run).encode(), usedforsecurity=False).hexdigest())

    def supprimer(self, run_id, nombre=None):
        cles = sorted(cle for cle in self.lignes if cle[3] == run_id)[:nombre]
        for cle in cles:
            del self.lignes[cle]
        return len(cles)

    def fermer(self):
        self.fermee = True


class FauxRejets:
    def __init__(self):
        self.appels = []

    def remplacer(self, dataset, fichier, rejets):
        self.appels.append((dataset, fichier, list(rejets)))
        return len(self.appels[-1][2])


class AvecDossier(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.dossier = Path(dossier.name)

    def fichier(self, avec_defauts=False, nom="fenetres.csv") -> Path:
        chemin = self.dossier / nom
        chemin.write_bytes(ef.fabriquer_fenetres(avec_defauts))
        return chemin

    def executer(self, fonction, *args, **kwargs):
        sortie, erreur = io.StringIO(), io.StringIO()
        with redirect_stdout(sortie), redirect_stderr(erreur):
            code = fonction(*args, **kwargs)
        return code, sortie.getvalue(), erreur.getvalue()


# --- Règles de contrôle : une par règle, plus les bornes ---------------------------------------------------------------
class ReglesDesFenetres(unittest.TestCase):
    def test_une_fenetre_valide_est_typee(self):
        f = controler()
        self.assertIsInstance(f, ft.Fenetre)
        self.assertEqual((f.road_segment_id, f.window_size_s, f.vehicle_count, f.flow_veh_per_min), ("ROAD_001", 300, 13, Decimal("2.60")))
        self.assertEqual(f.window_start, datetime(2026, 10, 30, 6, 5, tzinfo=UTC))

    def test_une_valeur_obligatoire_vide_ou_absente_est_refusee(self):
        for colonne in ft.OBLIGATOIRES:
            with self.subTest(colonne=colonne):
                for valeur in ("", "  "):
                    r = controler(**{colonne: valeur})
                    self.assertEqual((r.regle, colonne in r.motif), (q.MISSING_REQUIRED, True))
        absent = {c: v for c, v in BASE.items() if c != "congestion_state"}
        self.assertEqual(ft.Controleur(REFERENTIELS).traiter(1, absent).regle, q.MISSING_REQUIRED)

    def test_les_valeurs_facultatives_vides_sont_acceptees(self):
        f = controler(average_speed_kmh="", occupancy_rate="", max_queue_length_m="", speed_ratio="")
        self.assertEqual((f.average_speed_kmh, f.occupancy_rate, f.max_queue_length_m, f.speed_ratio), (None,) * 4)

    def test_un_type_invalide_est_refuse(self):
        cas = {
            "road_segment_id": "SEG_1", "window_start": "hier", "vehicle_count": "treize", "flow_veh_per_min": "2,6",
            "average_speed_kmh": "vite", "occupancy_rate": "0x1", "sample_count": "1.5", "window_size_s": "cinq",
        }
        for colonne, valeur in cas.items():
            with self.subTest(colonne=colonne):
                r = controler(**{colonne: valeur})
                self.assertEqual((r.regle, colonne in r.motif), (q.TYPE_INVALID, True))

    def test_un_instant_sans_fuseau_est_refuse_et_un_decalage_est_ramene_en_utc(self):
        self.assertEqual(controler(window_start="2026-10-30T06:05:00").regle, q.TYPE_INVALID)
        self.assertEqual(controler(window_start="2026-10-30T08:05:00+02:00").window_start, datetime(2026, 10, 30, 6, 5, tzinfo=UTC))

    def test_les_bornes_sont_incluses_et_leur_depassement_est_refuse(self):
        limites = {
            "vehicle_count": ("0", "-1"), "flow_veh_per_min": ("999999.99", "1000000"), "average_speed_kmh": ("200", "200.1"),
            "occupancy_rate": ("1", "1.001"), "max_queue_length_m": ("999999.9", "-0.1"), "speed_ratio": ("9.999", "10"),
            "sample_count": ("32767", "32768"), "expected_sample_count": ("1", "0"),
        }
        for colonne, (dedans, dehors) in limites.items():
            with self.subTest(colonne=colonne):
                autres = {"average_speed_kmh": "", "speed_ratio": ""} if colonne == "vehicle_count" else {}
                self.assertIsInstance(controler(**{colonne: dedans}, **autres), ft.Fenetre)
                self.assertEqual(controler(**{colonne: dehors}).regle, q.OUT_OF_RANGE)

    def test_seules_les_fenetres_de_une_et_cinq_minutes_sont_admises(self):
        self.assertEqual(controler(window_size_s="60").window_size_s, 60)
        for taille in ("3600", "0", "120"):
            self.assertEqual(controler(window_size_s=taille).regle, q.OUT_OF_RANGE, taille)

    def test_une_fenetre_non_alignee_sur_sa_taille_est_refusee(self):
        self.assertEqual(controler(window_start="2026-10-30T06:11:00Z").regle, ft.NOT_ALIGNED)
        self.assertEqual(controler(window_start="2026-10-30T06:05:01Z").regle, ft.NOT_ALIGNED)
        self.assertEqual(controler(window_start="2026-10-30T06:05:00.5Z").regle, ft.NOT_ALIGNED)
        self.assertIsInstance(controler(window_start="2026-10-30T06:11:00Z", window_size_s="60"), ft.Fenetre)

    def test_une_vitesse_sans_vehicule_est_refusee(self):
        r = controler(vehicle_count="0", average_speed_kmh="30.0")
        self.assertEqual(r.regle, ft.SPEED_WITHOUT_VEHICLE)
        self.assertIsInstance(controler(vehicle_count="0", average_speed_kmh="", speed_ratio=""), ft.Fenetre)

    def test_une_reference_inconnue_est_refusee(self):
        for colonne, valeur in (("road_segment_id", "ROAD_999"), ("congestion_state", "GRIDLOCK"), ("source_type", "REAL_LIVE")):
            with self.subTest(colonne=colonne):
                r = controler(**{colonne: valeur})
                self.assertEqual((r.regle, valeur in r.motif), (ft.UNKNOWN_REFERENCE, True))

    def test_un_doublon_dans_le_fichier_est_refuse_et_le_premier_est_retenu(self):
        controleur = ft.Controleur(REFERENTIELS)
        self.assertIsInstance(controleur.traiter(1, brut()), ft.Fenetre)
        r = controleur.traiter(2, brut(vehicle_count="99"))
        self.assertEqual((r.regle, r.ligne, "ligne 1" in r.motif), (q.DUPLICATE_KEY, 2, True))
        self.assertIsInstance(controleur.traiter(3, brut(window_start="2026-10-30T06:10:00Z")), ft.Fenetre)  # autre fenêtre
        self.assertIsInstance(controleur.traiter(4, brut(road_segment_id="ROAD_002")), ft.Fenetre)  # autre tronçon
        self.assertIsInstance(controleur.traiter(5, brut(window_size_s="60")), ft.Fenetre)  # autre taille

    def test_un_doublon_refuse_par_une_autre_regle_n_occupe_pas_la_cle(self):
        controleur = ft.Controleur(REFERENTIELS)
        self.assertEqual(controleur.traiter(1, brut(vehicle_count="-5")).regle, q.OUT_OF_RANGE)
        self.assertIsInstance(controleur.traiter(2, brut()), ft.Fenetre)

    def test_la_premiere_regle_violee_l_emporte_dans_l_ordre_annonce(self):
        self.assertEqual(ft.REGLES[0], q.MISSING_REQUIRED)
        self.assertEqual(controler(vehicle_count="", window_start="hier").regle, q.MISSING_REQUIRED)
        self.assertEqual(controler(window_start="hier", window_size_s="3600").regle, q.TYPE_INVALID)
        self.assertEqual(controler(window_size_s="3600", road_segment_id="ROAD_999").regle, q.OUT_OF_RANGE)
        self.assertEqual(controler(window_start="2026-10-30T06:11:00Z", road_segment_id="ROAD_999").regle, ft.NOT_ALIGNED)
        self.assertEqual(controler(vehicle_count="0", average_speed_kmh="30", road_segment_id="ROAD_999").regle, ft.SPEED_WITHOUT_VEHICLE)

    def test_le_rejet_garde_la_ligne_brute(self):
        r = controler(vehicle_count="-1")
        self.assertEqual((r.ligne, r.brut["vehicle_count"]), (1, "-1"))

    def test_l_en_tete_doit_contenir_toutes_les_colonnes(self):
        ft.verifier_entete([*ft.COLONNES, "autre"])
        with self.assertRaisesRegex(ft.ErreurFenetre, "congestion_state"):
            ft.verifier_entete([c for c in ft.COLONNES if c != "congestion_state"])

    def test_les_colonnes_du_controle_sont_celles_de_la_table(self):
        migration = (RACINE / "db" / "postgres" / "migrations" / "0002_dwh_faits.sql").read_text(encoding="utf-8")
        bloc = re.search(r"CREATE TABLE dwh\.fact_traffic_window \((.*?)\n\);", migration, re.S).group(1)
        colonnes = set(re.findall(r"^    (\w+)\s", bloc, re.M))
        self.assertTrue(set(ft.COLONNES) - {"road_segment_id"} <= colonnes)
        # chaque colonne obligatoire sans défaut ni génération de la table est fournie par le fichier ou par le chargement (clé, run_id)
        a_fournir = {m.group(1) for m in re.finditer(r"^    (\w+)\s+(?!.*GENERATED)(?!.*DEFAULT).*NOT NULL", bloc, re.M)}
        self.assertEqual(a_fournir - set(ft.COLONNES), {"road_segment_key", "run_id"})


# --- Chargement ---------------------------------------------------------------------------------------------------------
class Chargement(AvecDossier):
    def test_toutes_les_lignes_valides_sont_chargees(self):
        entrepot = FauxEntrepot()
        r = ce.charger_fichier(self.fichier(), "run-1", entrepot=entrepot)
        self.assertEqual((r.lues, r.chargees, r.rejetees, r.inserees, r.deja_presentes), (864, 864, 0, 864, 0))
        self.assertEqual(r.totaux.lignes, 864)
        self.assertEqual(r.totaux, entrepot.totaux("run-1"))
        self.assertEqual(r.sha256, hashlib.sha256(ef.fabriquer_fenetres()).hexdigest())

    def test_les_lignes_refusees_sont_decomptees_par_regle_et_transmises_avec_leur_motif(self):
        rejets = FauxRejets()
        r = ce.charger_fichier(self.fichier(avec_defauts=True), "run-1", entrepot=FauxEntrepot(), rejets_pg=rejets)
        self.assertEqual((r.lues, r.chargees, r.rejetees), (868, 864, 4))
        self.assertEqual(dict(r.par_regle), {q.DUPLICATE_KEY: 1, ft.UNKNOWN_REFERENCE: 1, ft.NOT_ALIGNED: 1, q.MISSING_REQUIRED: 1})
        (dataset, nom, ecrits), = rejets.appels
        self.assertEqual((dataset, nom, len(ecrits)), ("fenetres_trafic", "fenetres.csv", 4))
        self.assertEqual(sorted(e["source_ref"] for e in ecrits), [f"fenetres.csv#{n}" for n in range(865, 869)])
        self.assertTrue(all(e["reason"] and e["payload"]["road_segment_id"] for e in ecrits))

    def test_sans_rejet_les_anciens_rejets_du_fichier_sont_quand_meme_remplaces(self):
        rejets = FauxRejets()
        ce.charger_fichier(self.fichier(), "run-1", entrepot=FauxEntrepot(), rejets_pg=rejets)
        self.assertEqual(rejets.appels[0][2], [])

    def test_les_rejets_ne_sont_pas_ecrits_sans_sortie(self):
        self.assertEqual(ce.charger_fichier(self.fichier(True), "run-1", entrepot=FauxEntrepot()).rejetees, 4)

    def test_rejouer_le_meme_fichier_ne_change_aucun_total(self):
        entrepot = FauxEntrepot()
        fichier = self.fichier(avec_defauts=True)
        premier = ce.charger_fichier(fichier, "run-1", entrepot=entrepot)
        ecritures = entrepot.ecritures
        for _ in range(3):
            rejeu = ce.charger_fichier(fichier, "run-1", entrepot=entrepot)
            self.assertEqual(rejeu.totaux, premier.totaux)
            self.assertEqual((rejeu.inserees, rejeu.deja_presentes), (0, 864))
        self.assertEqual(entrepot.ecritures, ecritures)  # le rejeu n'a rien réécrit

    def test_un_run_different_ne_touche_pas_au_premier(self):
        entrepot = FauxEntrepot()
        fichier = self.fichier()
        premier = ce.charger_fichier(fichier, "run-1", entrepot=entrepot).totaux
        second = ce.charger_fichier(fichier, "run-2", entrepot=entrepot)
        self.assertEqual((second.inserees, entrepot.totaux("run-1")), (864, premier))
        self.assertEqual(len(entrepot.lignes), 1728)

    def test_une_valeur_corrigee_dans_le_fichier_met_la_ligne_a_jour_sans_la_dupliquer(self):
        entrepot = FauxEntrepot()
        ce.charger_fichier(self.fichier(), "run-1", entrepot=entrepot)
        avant = entrepot.totaux("run-1")
        corrige = self.dossier / "corrige.csv"
        debut = "ROAD_001,2026-10-30T06:05:00Z,300,SIMULATED,"
        corrige.write_text(ef.fabriquer_fenetres().decode().replace(debut + "13,", debut + "14,", 1), encoding="utf-8")
        apres = ce.charger_fichier(corrige, "run-1", entrepot=entrepot)
        self.assertEqual((apres.inserees, apres.totaux.lignes, apres.totaux.vehicules), (0, 864, avant.vehicules + 1))
        self.assertNotEqual(apres.totaux.empreinte, avant.empreinte)

    def test_un_fichier_avec_bom_et_fins_de_ligne_windows_est_lu(self):
        fichier = self.dossier / "bom.csv"
        fichier.write_bytes(b"\xef\xbb\xbf" + ef.fabriquer_fenetres().replace(b"\n", b"\r\n"))
        self.assertEqual(ce.charger_fichier(fichier, "run-1", entrepot=FauxEntrepot()).chargees, 864)

    def test_une_colonne_en_trop_dans_une_ligne_ne_fait_pas_echouer_le_chargement(self):
        fichier = self.dossier / "long.csv"
        lignes = ef.fabriquer_fenetres().decode().splitlines()
        lignes[1] += ",surplus"
        fichier.write_text("\n".join(lignes) + "\n", encoding="utf-8")
        self.assertEqual(ce.charger_fichier(fichier, "run-1", entrepot=FauxEntrepot()).chargees, 864)

    def test_un_run_id_invalide_est_refuse_avant_toute_lecture(self):
        for run_id in ("", " ", "a b", "x" * 81, "../evil", "é"):
            with self.subTest(run_id=run_id), self.assertRaisesRegex(ce.ErreurChargement, "run_id"):
                ce.charger_fichier(self.fichier(), run_id, entrepot=FauxEntrepot())
        self.assertEqual(ce.charger_fichier(self.fichier(), "x" * 80, entrepot=FauxEntrepot()).run_id, "x" * 80)

    def test_un_fichier_introuvable_ou_sans_les_bonnes_colonnes_ou_illisible_ne_charge_rien(self):
        entrepot = FauxEntrepot()
        with self.assertRaisesRegex(ce.ErreurChargement, "introuvable"):
            ce.charger_fichier(self.dossier / "absent.csv", "run-1", entrepot=entrepot)
        court = self.dossier / "court.csv"
        court.write_text("road_segment_id,window_start\nROAD_001,2026-10-30T06:00:00Z\n", encoding="utf-8")
        with self.assertRaisesRegex(ce.ErreurChargement, "Colonnes absentes"):
            ce.charger_fichier(court, "run-1", entrepot=entrepot)
        binaire = self.dossier / "binaire.csv"
        binaire.write_bytes(b"road_segment_id\n\xff\xfe\x00\n")
        with self.assertRaisesRegex(ce.ErreurChargement, "UTF-8"):
            ce.charger_fichier(binaire, "run-1", entrepot=entrepot)
        self.assertEqual(entrepot.lignes, {})

    def test_un_fichier_vide_de_donnees_ne_charge_rien_mais_reussit(self):
        fichier = self.dossier / "vide.csv"
        fichier.write_text(",".join(ft.COLONNES) + "\n", encoding="utf-8")
        r = ce.charger_fichier(fichier, "run-1", entrepot=FauxEntrepot())
        self.assertEqual((r.lues, r.chargees, r.totaux.lignes), (0, 0, 0))

    def test_un_nombre_de_rejets_ecrits_different_du_nombre_de_refus_est_une_erreur_et_rien_n_est_charge(self):
        class Infidele(FauxRejets):
            def remplacer(self, dataset, fichier, rejets):
                return super().remplacer(dataset, fichier, rejets) - 1

        entrepot = FauxEntrepot()
        with self.assertRaisesRegex(ce.ErreurChargement, "3 rejets écrits pour 4"):
            ce.charger_fichier(self.fichier(True), "run-1", entrepot=entrepot, rejets_pg=Infidele())
        self.assertEqual(entrepot.lignes, {})


class ConfinementDesChemins(AvecDossier):
    """Un chemin donné en argument ne peut pas faire lire ou écrire un autre fichier que ceux du dossier prévu."""

    def test_un_fichier_est_designe_par_son_nom_ou_par_un_chemin_qui_mene_au_dossier(self):
        self.assertEqual(ce.fichier_fenetres(self.dossier, "f.csv"), self.dossier / "f.csv")
        self.assertEqual(ce.fichier_fenetres(self.dossier, str(self.dossier / "f.csv")), self.dossier / "f.csv")

    def test_un_chemin_vers_un_autre_dossier_est_refuse(self):
        for texte in (str(self.dossier.parent / "f.csv"), "../f.csv", "sous/f.csv", "/etc/passwd.csv", str(self.dossier / ".." / "f.csv")):
            with self.subTest(texte=texte), self.assertRaisesRegex(ce.ErreurChargement, "hors du dossier"):
                ce.fichier_fenetres(self.dossier, texte)

    def test_un_nom_qui_n_est_pas_un_csv_simple_est_refuse(self):
        for texte in ("", "f.txt", "f", ".f.csv", "f csv.csv", "é.csv", "f.csv\n", "a" * 101 + ".csv", "..", "con:.csv"):
            with self.subTest(texte=texte), self.assertRaisesRegex(ce.ErreurChargement, "Nom de fichier refusé"):
                ce.fichier_fenetres(self.dossier, texte)
        self.assertEqual(ce.fichier_fenetres(self.dossier, "a" * 99 + ".csv").name, "a" * 99 + ".csv")

    def test_un_lien_ne_sort_pas_du_dossier_par_le_nom(self):
        with self.assertRaises(ce.ErreurChargement):
            ce.fichier_fenetres(self.dossier, "x/../../f.csv")

    def test_les_dossiers_par_defaut_sont_ceux_de_la_documentation(self):
        self.assertEqual(ce.FENETRES, RACINE / "data" / "datasets" / "fenetres")
        self.assertEqual(rejouer.RAPPORT, RACINE / "docs" / "03-donnees" / "rapport-rejeu-etl.md")
        gitignore = (RACINE / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/datasets/*", gitignore)

    def test_la_ligne_de_commande_refuse_un_chemin_hors_du_dossier_sans_rien_lire(self):
        autre = self.dossier / "autre"
        autre.mkdir()
        (autre / "f.csv").write_bytes(ef.fabriquer_fenetres())
        entrepot = FauxEntrepot()
        code, _, erreur = self.executer(ce.principal, ["--file", str(autre / "f.csv"), "--run-id", "run-1"], entrepot=entrepot, dossier=self.dossier)
        self.assertEqual((code, entrepot.lignes), (1, {}))
        self.assertIn("hors du dossier", erreur)
        code, _, erreur = self.executer(rejouer.principal, ["--file", str(autre / "f.csv"), "--run-id", "run-1", "--report"],
                                        entrepot=entrepot, dossier=self.dossier, rapport_md=self.dossier / "rapport-x.md")
        self.assertEqual(code, 1)
        self.assertFalse((self.dossier / "rapport-x.md").exists())  # un rejeu refusé n'écrit aucun rapport

    def test_le_rapport_n_a_pas_de_chemin_en_argument(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            rejouer.principal(["--file", "f.csv", "--run-id", "run-1", "--report", "autre.md"], entrepot=FauxEntrepot(), dossier=self.dossier)


class LigneDeCommandeDuChargement(AvecDossier):
    def test_le_chargement_affiche_le_resume_et_ferme_l_entrepot(self):
        entrepot = FauxEntrepot()
        code, sortie, _ = self.executer(ce.principal, ["--file", self.fichier(True).name, "--run-id", "run-1"], entrepot=entrepot,
                                        rejets_pg=FauxRejets(), dossier=self.dossier)
        self.assertEqual(code, 0)
        self.assertIn("868 lues = 864 chargées + 4 rejetées", sortie)
        self.assertIn("864 créées, 0 déjà présentes", sortie)
        self.assertIn("UNKNOWN_REFERENCE", sortie)
        self.assertIn(f"empreinte {entrepot.totaux('run-1').empreinte}", sortie)
        self.assertTrue(entrepot.fermee)

    def test_une_erreur_donne_le_code_1_et_un_message_sur_stderr(self):
        code, sortie, erreur = self.executer(ce.principal, ["--file", "absent.csv", "--run-id", "run-1"], entrepot=FauxEntrepot(), dossier=self.dossier)
        self.assertEqual((code, sortie), (1, ""))
        self.assertIn("ERREUR : Fichier de fenêtres introuvable", erreur)

    def test_sans_adresse_postgresql_le_message_nomme_la_commande_dev(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("POSTGRES_URL", None)
            code, _, erreur = self.executer(ce.principal, ["--file", self.fichier().name, "--run-id", "run-1"], dossier=self.dossier)
        self.assertEqual(code, 1)
        self.assertIn("dev.py etl-charger", erreur)

    def test_une_panne_de_la_base_devient_un_code_1(self):
        class EnPanne(FauxEntrepot):
            def charger(self, run_id, lot_):
                raise ErreurSortie("PostgreSQL a refusé l'écriture")

        code, _, erreur = self.executer(ce.principal, ["--file", self.fichier().name, "--run-id", "run-1"], entrepot=EnPanne(), dossier=self.dossier)
        self.assertEqual((code, "refusé l'écriture" in erreur), (1, True))


# --- SQL réel contrôlé contre la migration, avec une connexion simulée ------------------------------------------------
class FauxCurseur:
    def __init__(self, connexion):
        self.connexion = connexion

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def _enregistrer(self, genre, sql, params):
        self.connexion.journal.append((genre, " ".join(sql.split()), params))
        if self.connexion.panne:
            raise self.connexion.panne

    def execute(self, sql, params=None):
        self._enregistrer("execute", sql, params)
        self.derniere = " ".join(sql.split())

    def executemany(self, sql, lot_):
        self._enregistrer("executemany", sql, list(lot_))

    def fetchall(self):
        return [(v,) for v in self.connexion.reponses[self.derniere]]

    def fetchone(self):
        return self.connexion.reponses[self.derniere]

    @property
    def rowcount(self):
        return 7


class FausseConnexion:
    def __init__(self, reponses=None, panne=None):
        self.journal, self.reponses, self.panne, self.fermee = [], reponses or {}, panne, False

    def transaction(self):
        connexion = self

        class Transaction:
            def __enter__(self):
                connexion.journal.append(("begin",))

            def __exit__(self, type_, valeur, trace):
                connexion.journal.append(("rollback" if type_ else "commit",))
                return False

        return Transaction()

    def cursor(self):
        return FauxCurseur(self)

    def close(self):
        self.fermee = True


COMPTE = "SELECT count(*) FROM dwh.fact_traffic_window WHERE run_id = %s"


@unittest.skipIf(psycopg is None, "psycopg absent : pip install -r data/etl/requirements.txt")
class SqlDeLEntrepot(unittest.TestCase):
    def migration(self):
        texte = (RACINE / "db" / "postgres" / "migrations" / "0002_dwh_faits.sql").read_text(encoding="utf-8")
        return re.search(r"CREATE TABLE dwh\.fact_traffic_window \((.*?)\n\);", texte, re.S).group(1)

    def test_l_ecriture_cible_les_colonnes_et_la_cle_de_la_migration(self):
        bloc = self.migration()
        colonnes = set(re.findall(r"^    (\w+)\s", bloc, re.M))
        ecrites = re.search(r"INSERT INTO dwh\.fact_traffic_window AS f \((.*?)\)", ce.SQL_ECRITURE).group(1).split(", ")
        self.assertTrue(set(ecrites) <= colonnes, set(ecrites) - colonnes)
        generees = {m.group(1) for m in re.finditer(r"^    (\w+)\s.*GENERATED", bloc, re.M)}
        self.assertTrue(generees and not set(ecrites) & generees, "une colonne générée ne s'écrit pas")
        self.assertNotIn("loaded_at", ecrites)  # défaut now() à la création, mise à jour explicite au changement
        cle = re.search(r"PRIMARY KEY \((.*?)\)", bloc).group(1)
        self.assertIn(f"ON CONFLICT ({cle})", ce.SQL_ECRITURE)
        obligatoires = {m.group(1) for m in re.finditer(r"^    (\w+)\s+(?!.*GENERATED)(?!.*DEFAULT).*NOT NULL", bloc, re.M)}
        self.assertTrue(obligatoires <= set(ecrites), obligatoires - set(ecrites))

    def test_une_ligne_identique_n_est_pas_reecrite(self):
        mise_a_jour = ce.SQL_ECRITURE.split("DO UPDATE SET ")[1]
        self.assertIn("WHERE (f.source_type", mise_a_jour)
        self.assertIn("IS DISTINCT FROM (EXCLUDED.source_type", mise_a_jour)
        self.assertEqual(ce.A_METTRE_A_JOUR, tuple(c for c in ce.COLONNES_SQL if c not in ("window_start", "window_size_s", "run_id")))

    def test_le_nombre_de_parametres_correspond_aux_marqueurs(self):
        f = ft.Controleur(REFERENTIELS).traiter(1, brut())
        parametres = ce.EntrepotPostgres._parametres("run-1", f)
        self.assertEqual(ce.SQL_ECRITURE.count("%s"), len(parametres))
        self.assertEqual((parametres[2], parametres[-1]), ("run-1", "ROAD_001"))
        self.assertEqual(len(parametres), len(ce.COLONNES_SQL) + 1)

    def test_charger_ecrit_par_lots_dans_une_transaction_et_compte_les_lignes_creees(self):
        connexion = FausseConnexion()
        compteur = iter([(3,), (5,)])
        with unittest.mock.patch.object(FauxCurseur, "fetchone", lambda self: next(compteur)), unittest.mock.patch.object(ce, "LOT", 2):
            fenetres_ = [ft.Controleur(REFERENTIELS).traiter(n, brut(window_start=f"2026-10-30T0{6 + n // 12}:{n % 12 * 5:02d}:00Z")) for n in range(5)]
            creees = ce.EntrepotPostgres(connexion).charger("run-1", fenetres_)
        self.assertEqual(creees, 2)
        self.assertEqual([e[0] for e in connexion.journal], ["begin", "execute", "executemany", "executemany", "executemany", "execute", "commit"])
        self.assertEqual([len(e[2]) for e in connexion.journal if e[0] == "executemany"], [2, 2, 1])
        self.assertEqual(connexion.journal[1][1:], (COMPTE, ("run-1",)))

    def test_charger_sans_ligne_ne_fait_aucune_ecriture_mais_compte(self):
        connexion = FausseConnexion()
        with unittest.mock.patch.object(FauxCurseur, "fetchone", lambda self: (0,)):
            self.assertEqual(ce.EntrepotPostgres(connexion).charger("run-1", []), 0)
        self.assertNotIn("executemany", [e[0] for e in connexion.journal])

    def test_une_erreur_du_pilote_annule_la_transaction(self):
        connexion = FausseConnexion(panne=psycopg.errors.CheckViolation("violates check constraint"))
        with self.assertRaisesRegex(ErreurSortie, "CheckViolation"):
            ce.EntrepotPostgres(connexion).charger("run-1", [])
        self.assertEqual(connexion.journal[-1], ("rollback",))

    def test_les_referentiels_sont_lus_dans_les_trois_dimensions(self):
        connexion = FausseConnexion({
            "SELECT road_segment_id FROM dwh.dim_road_segment": ["ROAD_001"],
            "SELECT state_code FROM dwh.dim_congestion_state": ["FREE_FLOW", "SLOW"],
            "SELECT source_type FROM dwh.dim_source": ["SIMULATED"],
        })
        r = ce.EntrepotPostgres(connexion).referentiels()
        self.assertEqual((r.segments, r.etats, r.sources), (frozenset({"ROAD_001"}), frozenset({"FREE_FLOW", "SLOW"}), frozenset({"SIMULATED"})))
        with self.assertRaisesRegex(ErreurSortie, "Lecture des référentiels"):
            ce.EntrepotPostgres(FausseConnexion(panne=psycopg.errors.InsufficientPrivilege("denied"))).referentiels()

    def test_les_totaux_sont_calcules_par_la_base_pour_ce_run(self):
        connexion = FausseConnexion({ce.SQL_TOTAUX: (864, 58695, "11739.00", "abc")})
        totaux = ce.EntrepotPostgres(connexion).totaux("run-1")
        self.assertEqual(totaux, ce.Totaux(864, 58695, "11739.00", "abc"))
        self.assertEqual(connexion.journal[0][2], ("run-1",))
        with self.assertRaisesRegex(ErreurSortie, "totaux"):
            ce.EntrepotPostgres(FausseConnexion(panne=psycopg.errors.UndefinedTable("x"))).totaux("run-1")

    def test_les_totaux_excluent_l_instant_de_chargement_et_trient_les_lignes(self):
        self.assertNotIn("loaded_at", ce.SQL_TOTAUX)
        self.assertIn("ORDER BY s.road_segment_id, f.window_start, f.window_size_s", ce.SQL_TOTAUX)
        self.assertIn("WHERE f.run_id = %s", ce.SQL_TOTAUX)

    def test_la_connexion_est_ouverte_en_autocommit_pour_que_les_transactions_soient_reelles(self):
        with unittest.mock.patch("psycopg.connect") as connecter:
            ce.EntrepotPostgres.depuis_url("postgresql://u:p@h/db")
        self.assertIs(connecter.call_args.kwargs["autocommit"], True)
        with unittest.mock.patch("psycopg.connect", side_effect=psycopg.OperationalError("refused")), self.assertRaisesRegex(ErreurSortie, "injoignable"):
            ce.EntrepotPostgres.depuis_url("postgresql://u:p@h/db")

    def test_la_suppression_du_rejeu_ne_touche_que_le_run_demande(self):
        connexion = FausseConnexion()
        entrepot = rejouer.EntrepotPostgresRejouable(connexion)
        self.assertEqual(entrepot.supprimer("run-1"), 7)
        self.assertEqual(entrepot.supprimer("run-1", 3), 7)
        (_, tout, p_tout), (_, partiel, p_partiel) = [e for e in connexion.journal if e[0] == "execute"]
        self.assertEqual((p_tout, p_partiel), (("run-1", "run-1"), ("run-1", 3, "run-1")))
        self.assertNotIn("LIMIT", tout)
        self.assertIn("ORDER BY window_start, road_segment_key, window_size_s LIMIT %s", partiel)
        for sql in (tout, partiel):
            self.assertEqual(sql.count("run_id = %s"), 2)
        with self.assertRaisesRegex(ErreurSortie, "Suppression"):
            rejouer.EntrepotPostgresRejouable(FausseConnexion(panne=psycopg.errors.InsufficientPrivilege("denied"))).supprimer("run-1")


# --- Rejeu et rapport de comparaison -----------------------------------------------------------------------------------
class RejeuDuChargement(AvecDossier):
    def test_les_trois_passes_donnent_les_memes_totaux(self):
        entrepot = FauxEntrepot()
        c = rejouer.rejouer(self.fichier(True), "run-1", entrepot=entrepot, repartir_de_zero=True)
        self.assertTrue(c.identiques)
        self.assertEqual([p.nom for p in c.passes], ["Chargement initial", "Rejeu à l'identique", "Reprise après suppression"])
        self.assertEqual([p.resultat.inserees for p in c.passes], [864, 0, 86])
        self.assertEqual([p.retirees for p in c.passes], [0, 0, 86])
        self.assertEqual(len({t.empreinte for t in c.totaux}), 1)

    def test_une_reprise_qui_ne_retablit_pas_les_lignes_supprimees_est_detectee(self):
        class Paresseux(FauxEntrepot):
            def charger(self, run_id, lot_):  # ne recharge rien si le run a déjà des lignes : une reprise partielle reste partielle
                return 0 if any(cle[3] == run_id for cle in self.lignes) else super().charger(run_id, lot_)

        c = rejouer.rejouer(self.fichier(), "run-1", entrepot=Paresseux(), repartir_de_zero=True)
        self.assertEqual(c.totaux[0], c.totaux[1])  # le rejeu seul ne le voit pas
        self.assertFalse(c.identiques)

    def test_la_reprise_retire_un_dixieme_des_lignes_et_au_moins_une(self):
        petit = self.dossier / "petit.csv"
        petit.write_text(",".join(ft.COLONNES) + "\n" + ",".join(ef.ligne(1, 1)) + "\n", encoding="utf-8")
        c = rejouer.rejouer(petit, "run-1", entrepot=FauxEntrepot())
        self.assertEqual((c.passes[2].retirees, c.passes[2].resultat.inserees, c.identiques), (1, 1, True))

    def test_repartir_de_zero_supprime_le_run_et_pas_les_autres(self):
        entrepot = FauxEntrepot()
        fichier = self.fichier()
        ce.charger_fichier(fichier, "autre", entrepot=entrepot)
        ce.charger_fichier(fichier, "run-1", entrepot=entrepot)
        c = rejouer.rejouer(fichier, "run-1", entrepot=entrepot, repartir_de_zero=True)
        self.assertEqual((c.purge, c.passes[0].resultat.inserees, entrepot.totaux("autre").lignes), (864, 864, 864))
        self.assertIsNone(rejouer.rejouer(fichier, "run-1", entrepot=entrepot).purge)

    def test_sans_repartir_de_zero_le_rapport_le_dit(self):
        entrepot = FauxEntrepot()
        fichier = self.fichier()
        c = rejouer.rejouer(fichier, "run-1", entrepot=entrepot)
        texte = rejouer.rapport(c, fichier=fichier, run_id="run-1", instant=MAINTENANT)
        self.assertIn("conservé tel quel", texte)

    def test_un_chargement_qui_n_est_pas_idempotent_est_detecte(self):
        class Duplicateur(FauxEntrepot):
            def charger(self, run_id, lot_):  # ajoute une ligne de plus à chaque passage : ce que ferait un INSERT sans clé
                creees = super().charger(run_id, lot_)
                self.lignes[("fantome", datetime.now(UTC), 300, run_id)] = ("SIMULATED", 1, Decimal(1), None, None, None, None, 1, 1, "SLOW", "v")
                return creees

        entrepot = Duplicateur()
        c = rejouer.rejouer(self.fichier(), "run-1", entrepot=entrepot, repartir_de_zero=True)
        self.assertFalse(c.identiques)
        texte = rejouer.rapport(c, fichier=self.fichier(), run_id="run-1", instant=MAINTENANT)
        self.assertIn("Totaux DIFFÉRENTS", texte)
        self.assertNotIn("Totaux identiques", texte)

    def test_une_valeur_modifiee_a_nombre_de_lignes_egal_est_detectee_par_l_empreinte(self):
        class Alterateur(FauxEntrepot):
            passages = 0

            def charger(self, run_id, lot_):
                creees = super().charger(run_id, lot_)
                Alterateur.passages += 1
                cle = min(self.lignes)
                valeurs = list(self.lignes[cle])
                valeurs[1] += Alterateur.passages  # un véhicule de plus à chaque passage, sans changer le nombre de lignes
                self.lignes[cle] = tuple(valeurs)
                return creees

        c = rejouer.rejouer(self.fichier(), "run-1", entrepot=Alterateur(), repartir_de_zero=True)
        self.assertEqual(len({t.lignes for t in c.totaux}), 1)
        self.assertFalse(c.identiques)

    def test_le_rapport_donne_le_tableau_le_verdict_et_la_position_sur_glue(self):
        fichier = self.fichier(True)
        c = rejouer.rejouer(fichier, "run-1", entrepot=FauxEntrepot(), repartir_de_zero=True)
        texte = rejouer.rapport(c, fichier=fichier, run_id="run-1", instant=MAINTENANT)
        self.assertIn("# Rapport de comparaison", texte)
        self.assertIn("- Date : 2026-10-30 00:30 UTC", texte)
        self.assertIn("`fenetres.csv`", texte)
        self.assertNotIn(str(self.dossier), texte)  # aucun chemin du poste
        self.assertIn("run supprimé avant la première passe (0 lignes)", texte)
        self.assertEqual(texte.count("| Rejeu à l'identique | 0 | 864 | 4 | 0 | 864 |"), 1)
        self.assertIn("**Totaux identiques**", texte)
        self.assertIn("**non exécuté**", texte)
        empreinte = c.totaux[0].empreinte
        self.assertEqual(texte.count(f"`{empreinte}`"), 3)

    def test_la_ligne_de_commande_ecrit_le_rapport_et_rend_0(self):
        rapport = self.dossier / "rapport-essai.md"
        code, sortie, _ = self.executer(
            rejouer.principal, ["--file", self.fichier().name, "--run-id", "run-1", "--from-scratch", "--report"],
            entrepot=FauxEntrepot(), maintenant=MAINTENANT, dossier=self.dossier, rapport_md=rapport)
        self.assertEqual(code, 0)
        self.assertEqual(sortie, rapport.read_text(encoding="utf-8") + "\n")  # le rapport écrit est celui qui est affiché
        self.assertNotIn("\r", rapport.read_text(encoding="utf-8"))

    def test_des_totaux_differents_donnent_le_code_2(self):
        class Duplicateur(FauxEntrepot):
            def charger(self, run_id, lot_):
                self.lignes[("x", datetime.now(UTC), 300, run_id)] = ("SIMULATED", 1, Decimal(1), None, None, None, None, 1, 1, "SLOW", "v")
                return super().charger(run_id, lot_)

        code, sortie, _ = self.executer(rejouer.principal, ["--file", self.fichier().name, "--run-id", "run-1"], entrepot=Duplicateur(), maintenant=MAINTENANT,
                                         dossier=self.dossier)
        self.assertEqual(code, 2)
        self.assertIn("Totaux DIFFÉRENTS", sortie)

    def test_les_erreurs_donnent_le_code_1(self):
        code, _, erreur = self.executer(rejouer.principal, ["--file", "absent.csv", "--run-id", "run-1"], entrepot=FauxEntrepot(), dossier=self.dossier)
        self.assertEqual(code, 1)
        self.assertIn("introuvable", erreur)
        with unittest.mock.patch.dict(os.environ):
            os.environ.pop("POSTGRES_URL", None)
            code, _, erreur = self.executer(rejouer.principal, ["--file", self.fichier().name, "--run-id", "run-1"], dossier=self.dossier)
        self.assertEqual(code, 1)
        self.assertIn("dev.py etl-rejouer", erreur)


# --- Lot planifié ------------------------------------------------------------------------------------------------------
class LotPlanifie(AvecDossier):
    def etapes(self, codes=None):
        codes = codes or {}
        self.appels = []

        def etape(nom):
            def lancer(options):
                self.appels.append((nom, list(options)))
                return codes.get(nom, 0)
            return lancer

        return {"ingestion": etape("ingestion"), "nettoyage": etape("nettoyage"), "chargement": etape("chargement")}

    def test_sans_jour_le_lot_traite_la_veille_en_utc(self):
        self.assertEqual(lot.la_veille(datetime(2026, 10, 30, 0, 30, tzinfo=UTC)), date(2026, 10, 29))
        self.assertEqual(lot.la_veille(datetime(2026, 1, 1, 0, 0, tzinfo=UTC)), date(2025, 12, 31))
        from datetime import timedelta, timezone
        paris = timezone(timedelta(hours=2))
        self.assertEqual(lot.la_veille(datetime(2026, 10, 30, 1, 30, tzinfo=paris)), date(2026, 10, 28))  # 23:30 UTC le 29 : la veille est le 28

    def test_l_ingestion_puis_le_nettoyage_du_meme_jour(self):
        code, sortie, _ = self.executer(lot.principal, [], maintenant=lambda: MAINTENANT, **self.etapes())
        self.assertEqual(code, 0)
        self.assertEqual(self.appels, [("ingestion", ["--day", "2026-10-29"]), ("nettoyage", ["--day", "2026-10-29"])])
        self.assertIn("Lot ETL du 2026-10-29", sortie)
        self.assertRegex(sortie, r"Chargement des fenêtres\s+: sautée \(aucun fichier de fenêtres demandé")

    def test_un_jour_explicite_l_emporte(self):
        self.executer(lot.principal, ["--day", "2026-10-17"], maintenant=lambda: MAINTENANT, **self.etapes())
        self.assertEqual(self.appels[0], ("ingestion", ["--day", "2026-10-17"]))

    def test_les_fenetres_sont_chargees_avec_leur_run_id(self):
        code, sortie, _ = self.executer(lot.principal, ["--windows", "f.csv", "--run-id", "run-9"], maintenant=lambda: MAINTENANT, **self.etapes())
        self.assertEqual(code, 0)
        self.assertEqual(self.appels[-1], ("chargement", ["--file", "f.csv", "--run-id", "run-9"]))
        self.assertRegex(sortie, r"Chargement des fenêtres\s+: réussie")

    def test_un_echec_d_ingestion_saute_le_nettoyage_mais_pas_le_chargement(self):
        code, sortie, _ = self.executer(lot.principal, ["--windows", "f.csv", "--run-id", "r"], maintenant=lambda: MAINTENANT, **self.etapes({"ingestion": 1}))
        self.assertEqual(code, 1)
        self.assertEqual([nom for nom, _ in self.appels], ["ingestion", "chargement"])
        self.assertRegex(sortie, r"Nettoyage de Paris\s+: sautée \(pas de fichier brut")
        self.assertRegex(sortie, r"Ingestion de Paris\s+: ÉCHEC")

    def test_un_echec_de_nettoyage_ou_de_chargement_donne_le_code_1(self):
        for nom in ("nettoyage", "chargement"):
            with self.subTest(nom=nom):
                code, sortie, _ = self.executer(lot.principal, ["--windows", "f.csv", "--run-id", "r"], maintenant=lambda: MAINTENANT, **self.etapes({nom: 3}))
                self.assertEqual(code, 1)
                self.assertEqual(sortie.count("ÉCHEC"), 1)

    def test_des_fenetres_sans_run_id_sont_refusees(self):
        with self.assertRaises(SystemExit) as sortie, redirect_stderr(io.StringIO()):
            lot.principal(["--windows", "f.csv"], **self.etapes())
        self.assertEqual(sortie.exception.code, 2)
        self.assertEqual(self.appels, [])

    def test_les_etapes_par_defaut_sont_les_pipelines_eux_memes(self):
        import inspect

        defauts = {nom: p.default for nom, p in inspect.signature(lot.executer).parameters.items() if nom in ("ingestion", "nettoyage", "chargement")}
        self.assertEqual({n: f.__module__ for n, f in defauts.items()},
                         {"ingestion": "pipelines.ingerer_paris", "nettoyage": "pipelines.nettoyer_paris", "chargement": "pipelines.charger_entrepot"})


# --- Empaquetage ---------------------------------------------------------------------------------------------------------
class Empaquetage(AvecDossier):
    def test_l_archive_est_reproductible(self):
        premiere = empaqueter.construire(sortie=self.dossier / "a")
        seconde = empaqueter.construire(sortie=self.dossier / "b")
        self.assertEqual(empaqueter.empreinte(premiere), empaqueter.empreinte(seconde))
        self.assertEqual(premiere.name, f"novaria-etl-{empaqueter.version()}.zip")

    def test_l_ordre_des_fichiers_ne_depend_pas_de_celui_du_systeme_de_fichiers(self):
        rglob = Path.rglob
        with unittest.mock.patch.object(Path, "rglob", lambda self, motif: reversed(sorted(rglob(self, motif)))):
            archive = empaqueter.construire(sortie=self.dossier / "inverse")
        self.assertEqual(empaqueter.empreinte(archive), empaqueter.empreinte(empaqueter.construire(sortie=self.dossier / "normal")))

    def test_l_archive_contient_le_code_et_le_manifeste_mais_ni_cache_ni_tests(self):
        archive = empaqueter.construire(sortie=self.dossier)
        with zipfile.ZipFile(archive) as z:
            noms = z.namelist()
            manifeste = z.read(empaqueter.MANIFESTE).decode()
            for nom in noms:
                if nom != empaqueter.MANIFESTE:
                    self.assertIn(f"{hashlib.sha256(z.read(nom)).hexdigest()}  {nom}\n", manifeste)
            self.assertEqual({i.date_time for i in z.infolist()}, {empaqueter.DATE_FIXE})
        for attendu in ("pipelines/lot.py", "pipelines/charger_entrepot.py", "pipelines/rejouer.py", "transforms/fenetres_trafic.py", "requirements.txt"):
            self.assertIn(attendu, noms)
        self.assertFalse([n for n in noms if "__pycache__" in n or n.endswith(".pyc") or n.startswith("tests/")])
        self.assertEqual(noms[-1], empaqueter.MANIFESTE)

    def test_une_modification_du_code_change_l_empreinte_de_l_archive(self):
        copie = self.dossier / "etl"
        for relatif in empaqueter.fichiers_a_empaqueter():
            (copie / relatif).parent.mkdir(parents=True, exist_ok=True)
            (copie / relatif).write_bytes((empaqueter.RACINE_ETL / relatif).read_bytes())
        (copie / "pyproject.toml").write_bytes((empaqueter.RACINE_ETL / "pyproject.toml").read_bytes())
        avant = empaqueter.empreinte(empaqueter.construire(copie, self.dossier / "o1"))
        with (copie / "pipelines" / "lot.py").open("a", encoding="utf-8") as fichier:
            fichier.write("\n# modifié\n")
        self.assertNotEqual(avant, empaqueter.empreinte(empaqueter.construire(copie, self.dossier / "o2")))

    def test_les_dependances_du_paquet_sont_celles_de_requirements(self):
        projet = tomllib.loads((RACINE / "data" / "etl" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        lignes = (RACINE / "data" / "etl" / "requirements.txt").read_text(encoding="utf-8").splitlines()
        requirements = [ligne for ligne in lignes if ligne and not ligne.startswith("#")]
        self.assertEqual(sorted(projet["dependencies"]), sorted(requirements))

    def test_les_commandes_du_paquet_existent(self):
        import importlib

        projet = tomllib.loads((RACINE / "data" / "etl" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        for commande, cible in projet["scripts"].items():
            with self.subTest(commande=commande):
                module, fonction = cible.split(":")
                self.assertTrue(callable(getattr(importlib.import_module(module), fonction)))

    def test_la_ligne_de_commande_affiche_le_chemin_et_l_empreinte(self):
        with unittest.mock.patch.object(empaqueter, "SORTIE", self.dossier):
            code, sortie, _ = self.executer(empaqueter.principal, [])
            self.assertEqual(code, 0)
            archive = self.dossier / f"novaria-etl-{empaqueter.version()}.zip"
            self.assertIn(f"sha256 {empaqueter.empreinte(archive)}", sortie)
            self.assertRegex(sortie, r": \d+ fichiers,")

    def test_la_sortie_de_l_archive_n_est_pas_un_argument_de_la_ligne_de_commande(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            empaqueter.principal(["--out", str(self.dossier)])
        self.assertEqual(empaqueter.SORTIE, RACINE / "dist")


# --- Planification ---------------------------------------------------------------------------------------------------------
class Planification(unittest.TestCase):
    DOSSIER = RACINE / "data" / "etl" / "planification"

    def test_la_ligne_cron_lance_le_lot_par_dev_py_chaque_jour(self):
        lignes = [ligne for ligne in (self.DOSSIER / "novaria-etl.cron").read_text(encoding="utf-8").splitlines() if ligne and not ligne.startswith("#")]
        self.assertEqual(len(lignes), 1)
        minute, heure, jour, mois, semaine, *commande = lignes[0].split()
        self.assertEqual((jour, mois, semaine), ("*", "*", "*"))
        self.assertTrue(0 <= int(minute) < 60 and 0 <= int(heure) < 24)
        self.assertIn("scripts/dev/dev.py etl-lot", " ".join(commande))
        self.assertIn(">> var/log/etl-lot.log 2>&1", " ".join(commande))
        self.assertIn("/CHEMIN/VERS/novaria-core", lignes[0])  # le chemin est à remplacer, pas celui d'un poste

    def test_la_tache_windows_lance_la_meme_commande_et_peut_etre_retiree(self):
        script = (self.DOSSIER / "installer-tache-windows.ps1").read_bytes()
        self.assertTrue(script.startswith(b"\xef\xbb\xbf"), "BOM UTF-8 : Windows PowerShell 5.1 lit sinon les accents en ANSI")
        texte = script.decode("utf-8-sig")
        self.assertIn(r"py -3 scripts\dev\dev.py etl-lot >> var\log\etl-lot.log 2>&1", texte)
        self.assertIn("-Supprimer", texte)
        self.assertIn("Unregister-ScheduledTask", texte)
        self.assertIn("-MultipleInstances IgnoreNew", texte)  # deux lots ne se chevauchent pas
        self.assertNotRegex(texte, r"(?i)-Password|-RunLevel Highest|-LogonType Password")  # aucun mot de passe, aucune élévation

    def test_cron_et_tache_windows_programment_la_meme_heure_par_defaut(self):
        cron = next(ligne for ligne in (self.DOSSIER / "novaria-etl.cron").read_text(encoding="utf-8").splitlines() if ligne and not ligne.startswith("#"))
        minute, heure = cron.split()[:2]
        self.assertIn(f"$Heure = '{int(heure):02d}:{int(minute):02d}'", (self.DOSSIER / "installer-tache-windows.ps1").read_text(encoding="utf-8-sig"))

    def test_les_donnees_et_journaux_du_planificateur_sont_ignores_par_git(self):
        gitignore = (RACINE / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("var/", gitignore)


# --- SQL exécuté pour de bon, si une base migrée est fournie ------------------------------------------------------------
@unittest.skipUnless(psycopg and os.environ.get("NOVARIA_TEST_POSTGRES_URL"), "NOVARIA_TEST_POSTGRES_URL absent : base migrée requise")
class AvecPostgresReel(AvecDossier):
    def setUp(self):
        super().setUp()
        self.run_id = f"test-{os.getpid()}"
        self.entrepot = rejouer.EntrepotPostgresRejouable.depuis_url(os.environ["NOVARIA_TEST_POSTGRES_URL"])
        self.addCleanup(self.entrepot.fermer)
        self.addCleanup(self.entrepot.supprimer, self.run_id)

    def test_le_rejeu_et_la_reprise_gardent_les_memes_totaux_dans_la_vraie_table(self):
        c = rejouer.rejouer(self.fichier(True), self.run_id, entrepot=self.entrepot, repartir_de_zero=True)
        self.assertTrue(c.identiques, [p.resultat.totaux for p in c.passes])
        self.assertEqual([p.resultat.inserees for p in c.passes], [864, 0, 86])
        self.assertEqual(c.totaux[0].lignes, 864)

    def test_une_valeur_corrigee_met_la_ligne_a_jour_dans_la_vraie_table_sans_la_dupliquer(self):
        ce.charger_fichier(self.fichier(), self.run_id, entrepot=self.entrepot)
        debut = "ROAD_001,2026-10-30T06:05:00Z,300,SIMULATED,"
        corrige = self.dossier / "corrige.csv"
        corrige.write_text(ef.fabriquer_fenetres().decode().replace(debut + "13,", debut + "14,", 1), encoding="utf-8")
        apres = ce.charger_fichier(corrige, self.run_id, entrepot=self.entrepot)
        self.assertEqual((apres.inserees, apres.totaux.lignes), (0, 864))
        with self.entrepot.connexion.cursor() as curseur:
            curseur.execute("SELECT vehicle_count FROM dwh.fact_traffic_window f JOIN dwh.dim_road_segment s USING (road_segment_key) "
                            "WHERE f.run_id = %s AND s.road_segment_id = 'ROAD_001' AND f.window_start = '2026-10-30T06:05:00Z'", (self.run_id,))
            self.assertEqual(curseur.fetchone()[0], 14)

    def test_le_faux_et_la_vraie_table_donnent_les_memes_totaux_sur_le_meme_fichier(self):
        fichier = self.fichier()
        reel = ce.charger_fichier(fichier, self.run_id, entrepot=self.entrepot).totaux
        faux = ce.charger_fichier(fichier, "r", entrepot=FauxEntrepot()).totaux
        self.assertEqual((reel.lignes, reel.vehicules, Decimal(reel.debit)), (faux.lignes, faux.vehicules, Decimal(faux.debit)))


if __name__ == "__main__":
    unittest.main()
