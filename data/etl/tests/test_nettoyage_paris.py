"""Tests du pipeline de nettoyage du comptage routier de Paris (DAT-04). Aucun accès au réseau ni à une base.

    python -m unittest discover -s data/etl/tests

Le fichier brut est fabriqué (échantillon commun) puis rangé sous son nom officiel, avec la vraie empreinte. Les sorties
PostgreSQL et MongoDB sont remplacées par des faux qui se comportent comme elles (remplacer, mettre à jour sur place).
"""

import csv
import hashlib
import io
import json
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, date, datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "data" / "etl"))

from echantillon import LIGNES, fabriquer_csv, verifier_contre_le_validateur  # noqa: E402
from pipelines import nettoyer_paris as np_  # noqa: E402
from pipelines import paris_comptages as paris  # noqa: E402
from pipelines import sorties  # noqa: E402
from transforms import paris_qualite as q  # noqa: E402

try:
    import psycopg
except ImportError:
    psycopg = None
try:
    import pymongo
except ImportError:
    pymongo = None

MAINTENANT = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
BASE = dict(zip(paris.COLONNES, LIGNES[0], strict=True))


def ligne(**champs):
    return tuple({**BASE, **champs}[colonne] for colonne in paris.COLONNES)


# L'échantillon : 7 lignes valides et la 2e (débit vide, refusée) ; puis 4 lignes refusées : débit vide, doublon de la 1re, type, borne.
VALIDES = [ligne_ for rang, ligne_ in enumerate(LIGNES) if rang != 1]
MELANGE = [*LIGNES, ligne(iu_ac="900", q="", k="", etat_trafic="Inconnu"), ligne(), ligne(iu_ac="901", q="abc"),
           ligne(iu_ac="902", k="120", etat_trafic="Bloqué")]
SORTIES_ATTENDUES = {"MISSING_REQUIRED": 2, "DUPLICATE_KEY": 1, "TYPE_INVALID": 1, "OUT_OF_RANGE": 1}


def ranger_brut(dossier: Path, lignes=MELANGE, debut="20261017T000000Z", fin="20261018T000000Z") -> tuple[Path, str]:
    octets = fabriquer_csv(lignes)
    empreinte = hashlib.sha256(octets).hexdigest()
    chemin = dossier / paris.DATASET_ID / f"{debut}_{fin}_{empreinte[:12]}.csv"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(octets)
    return chemin, empreinte


class FauxRejetsPg:
    """Se comporte comme RejetsPostgres.remplacer : les rejets d'un fichier sont remplacés, jamais ajoutés."""

    def __init__(self):
        self.par_fichier = {}
        self.appels = 0

    def remplacer(self, dataset, fichier, rejets):
        self.appels += 1
        self.par_fichier[(dataset, fichier)] = list(rejets)
        return len(self.par_fichier[(dataset, fichier)])


class FauxBilan:
    """Se comporte comme BilanMongo.enregistrer : un document par (fenêtre, empreinte), mis à jour sur place."""

    def __init__(self):
        self.documents = {}
        self.appels = 0

    def enregistrer(self, valeurs, *, fenetre_debut, sha256):
        self.appels += 1
        self.documents[(fenetre_debut, sha256)] = dict(valeurs)


class AvecDossier(unittest.TestCase):
    def setUp(self):
        temporaire = tempfile.TemporaryDirectory()
        self.addCleanup(temporaire.cleanup)
        self.racine = Path(temporaire.name)

    def nettoyer(self, brut, pg=None, mongo=None, **options):
        return np_.nettoyer_fichier(brut, rejets_pg=pg, bilan_mongo=mongo, maintenant=lambda: MAINTENANT, **options)


class Nettoyage(AvecDossier):
    def test_le_fichier_brut_donne_des_lignes_propres_et_des_lignes_refusees(self):
        brut, _ = ranger_brut(self.racine)
        resultat = self.nettoyer(brut)
        bilan = resultat.bilan
        self.assertEqual((bilan.lues, bilan.propres, bilan.rejetees), (12, 7, 5))
        self.assertEqual(dict(bilan.par_regle), SORTIES_ATTENDUES)
        self.assertEqual(resultat.propre, brut.parent / "propre" / f"{brut.stem}.csv")
        self.assertEqual(resultat.rejets, brut.parent / "rejets" / f"{brut.stem}.jsonl")

    def test_le_csv_propre_est_type_et_complet(self):
        brut, _ = ranger_brut(self.racine)
        resultat = self.nettoyer(brut)
        octets = resultat.propre.read_bytes()
        self.assertNotIn(b"\r", octets, "fins de ligne LF")
        lignes = list(csv.reader(io.StringIO(octets.decode("utf-8")), delimiter=";"))
        self.assertEqual(tuple(lignes[0]), np_.COLONNES_PROPRES)
        self.assertEqual(len(lignes) - 1, 7)
        premiere = dict(zip(np_.COLONNES_PROPRES, lignes[1], strict=True))
        self.assertEqual(premiere, {
            "road_segment_id": "4392", "label": "Quai_d'Orsay", "hour_utc": "2026-10-18T10:00:00Z", "vehicle_count": "199.0",
            "occupancy_pct": "2.03556", "traffic_state": "Fluide", "barrier_state": "Ouvert", "upstream_node_id": "2349",
            "downstream_node_id": "189", "quality_flags": "", "source_line": "1"})
        sans_k = next(dict(zip(np_.COLONNES_PROPRES, ligne_, strict=True)) for ligne_ in lignes[1:] if ligne_[0] == "193")
        self.assertEqual((sans_k["occupancy_pct"], sans_k["quality_flags"]), ("", "MISSING_OCCUPANCY"))

    def test_chaque_ligne_refusee_est_ecrite_avec_sa_regle_son_motif_et_sa_ligne_d_origine(self):
        brut, _ = ranger_brut(self.racine)
        resultat = self.nettoyer(brut)
        octets = resultat.rejets.read_bytes()
        self.assertNotIn(b"\r", octets)
        rejets = [json.loads(ligne_) for ligne_ in octets.decode("utf-8").splitlines()]
        self.assertEqual([(r["source_ref"], r["rule"]) for r in rejets], [
            (f"{brut.name}#2", "MISSING_REQUIRED"), (f"{brut.name}#9", "MISSING_REQUIRED"), (f"{brut.name}#10", "DUPLICATE_KEY"),
            (f"{brut.name}#11", "TYPE_INVALID"), (f"{brut.name}#12", "OUT_OF_RANGE")])
        for rejet in rejets:
            self.assertEqual(sorted(rejet), ["payload", "reason", "rule", "source_ref"])
            self.assertTrue(rejet["reason"])
            self.assertEqual(sorted(rejet["payload"]), sorted(paris.COLONNES), "toute la ligne d'origine, colonne par colonne")
        self.assertEqual(rejets[3]["payload"]["q"], "abc", "la valeur fautive est gardée telle quelle")
        self.assertIn("ligne 1", rejets[2]["reason"])

    def test_aucune_ligne_n_est_perdue_ni_comptee_deux_fois(self):
        brut, _ = ranger_brut(self.racine)
        resultat = self.nettoyer(brut)
        propres = len(resultat.propre.read_text(encoding="utf-8").splitlines()) - 1
        rejetees = len(resultat.rejets.read_text(encoding="utf-8").splitlines())
        self.assertEqual(propres + rejetees, resultat.bilan.lues)
        rangs = [int(r.split(";")[-1]) for r in resultat.propre.read_text(encoding="utf-8").splitlines()[1:]]
        rangs += [int(json.loads(r)["source_ref"].split("#")[1]) for r in resultat.rejets.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sorted(rangs), list(range(1, 13)), "chaque ligne du brut ressort une fois, et une seule")

    def test_le_fichier_brut_n_est_jamais_touche(self):
        brut, empreinte = ranger_brut(self.racine)
        date_avant = brut.stat().st_mtime_ns
        self.nettoyer(brut)
        self.assertEqual(hashlib.sha256(brut.read_bytes()).hexdigest(), empreinte)
        self.assertEqual(brut.stat().st_mtime_ns, date_avant)

    def test_rejouer_donne_les_memes_fichiers_octet_pour_octet(self):
        brut, _ = ranger_brut(self.racine)
        premier = self.nettoyer(brut)
        empreintes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (premier.propre, premier.rejets)]
        second = self.nettoyer(brut)
        self.assertEqual([hashlib.sha256(p.read_bytes()).hexdigest() for p in (second.propre, second.rejets)], empreintes)
        self.assertEqual(sorted(p.name for p in brut.parent.rglob("*") if p.is_file()),
                         sorted([brut.name, f"{brut.stem}.csv", f"{brut.stem}.jsonl"]), "aucun fichier provisoire ni en double")

    def test_une_exécution_interrompue_laisse_les_sorties_precedentes_intactes(self):
        brut, _ = ranger_brut(self.racine)
        premier = self.nettoyer(brut)
        avant = (premier.propre.read_bytes(), premier.rejets.read_bytes())
        with unittest.mock.patch.object(q.Nettoyeur, "traiter", side_effect=RuntimeError("panne")), self.assertRaises(RuntimeError):
            self.nettoyer(brut)
        self.assertEqual((premier.propre.read_bytes(), premier.rejets.read_bytes()), avant)
        self.assertEqual([p.name for p in brut.parent.rglob("*.part")], [])

    def test_un_fichier_entierement_valide_n_a_aucun_rejet(self):
        brut, _ = ranger_brut(self.racine, VALIDES)
        resultat = self.nettoyer(brut)
        self.assertEqual((resultat.bilan.rejetees, resultat.bilan.taux_rejet), (0, 0.0))
        self.assertEqual(resultat.rejets.read_text(encoding="utf-8"), "")


class ContrôleDuBrut(AvecDossier):
    def test_un_brut_modifie_est_refuse_et_rien_n_est_ecrit(self):
        brut, _ = ranger_brut(self.racine)
        brut.write_bytes(brut.read_bytes() + b"x")
        with self.assertRaisesRegex(np_.ErreurNettoyage, "empreinte de son nom"):
            self.nettoyer(brut)
        self.assertFalse((brut.parent / "propre").exists() or (brut.parent / "rejets").exists())

    def test_un_nom_inattendu_est_refuse(self):
        brut, _ = ranger_brut(self.racine)
        autre = brut.with_name("export.csv")
        brut.rename(autre)
        with self.assertRaisesRegex(np_.ErreurNettoyage, "Nom inattendu"):
            self.nettoyer(autre)

    def test_un_fichier_absent_est_refuse(self):
        with self.assertRaisesRegex(np_.ErreurNettoyage, "introuvable"):
            self.nettoyer(self.racine / "20261017T000000Z_20261018T000000Z_aaaaaaaaaaaa.csv")

    def test_un_en_tete_change_est_refuse(self):
        octets = fabriquer_csv(LIGNES, entete=paris.COLONNES[:-1])
        empreinte = hashlib.sha256(octets).hexdigest()
        brut = self.racine / paris.DATASET_ID / f"20261017T000000Z_20261018T000000Z_{empreinte[:12]}.csv"
        brut.parent.mkdir(parents=True)
        brut.write_bytes(octets)
        with self.assertRaises(paris.ErreurSource):
            self.nettoyer(brut)


class TauxDeRejetJournalise(AvecDossier):
    def test_le_bilan_est_journalise_avec_le_taux_et_les_motifs(self):
        brut, empreinte = ranger_brut(self.racine)
        mongo = FauxBilan()
        resultat = self.nettoyer(brut, mongo=mongo)
        self.assertTrue(resultat.bilan_journalise)
        (cle, document), = mongo.documents.items()
        self.assertEqual(cle, (datetime(2026, 10, 17, tzinfo=UTC), empreinte))
        self.assertEqual(document["dataset"], "paris-comptages-routiers")
        self.assertEqual(document["source_file"], brut.name)
        self.assertEqual(document["source_sha256"], empreinte)
        self.assertEqual((document["rows_read"], document["rows_clean"], document["rows_rejected"]), (12, 7, 5))
        self.assertAlmostEqual(document["reject_rate"], 5 / 12, places=6)
        self.assertEqual(document["by_rule"], SORTIES_ATTENDUES | {})
        self.assertEqual(document["flags"], {"MISSING_OCCUPANCY": 1})
        self.assertEqual(document["cleaned_at"], MAINTENANT)
        self.assertTrue(document["run_id"].startswith("net-20261029T120000Z-"))

    def test_rejouer_met_le_bilan_a_jour_sans_en_creer_un_second(self):
        brut, _ = ranger_brut(self.racine)
        mongo = FauxBilan()
        self.nettoyer(brut, mongo=mongo)
        self.nettoyer(brut, mongo=mongo)
        self.assertEqual((mongo.appels, len(mongo.documents)), (2, 1))

    def test_le_taux_au_dessus_du_seuil_declenche_l_alerte(self):
        brut, _ = ranger_brut(self.racine)
        for seuil, alerte in ((0.2, True), (5 / 12, False), (0.5, False), (0.0, True)):
            with self.subTest(seuil=seuil):
                mongo = FauxBilan()
                resultat = self.nettoyer(brut, mongo=mongo, seuil_alerte=seuil)
                self.assertIs(resultat.alerte, alerte)
                (document,) = mongo.documents.values()
                self.assertIs(document["alert"], alerte)
                self.assertEqual(document["alert_threshold"], seuil)

    def test_sans_sortie_mongodb_le_taux_reste_calcule_mais_non_journalise(self):
        brut, _ = ranger_brut(self.racine)
        resultat = self.nettoyer(brut)
        self.assertFalse(resultat.bilan_journalise)
        self.assertAlmostEqual(resultat.bilan.taux_rejet, 5 / 12)


class RejetsDansPostgres(AvecDossier):
    def test_les_rejets_sont_remplaces_pas_ajoutes_a_chaque_execution(self):
        brut, _ = ranger_brut(self.racine)
        pg = FauxRejetsPg()
        premier = self.nettoyer(brut, pg=pg)
        self.nettoyer(brut, pg=pg)
        (cle, rejets), = pg.par_fichier.items()
        self.assertEqual((pg.appels, cle, len(rejets), premier.rejets_postgres), (2, ("paris-comptages-routiers", brut.name), 5, 5))
        self.assertEqual([r["rule"] for r in rejets], ["MISSING_REQUIRED", "MISSING_REQUIRED", "DUPLICATE_KEY", "TYPE_INVALID", "OUT_OF_RANGE"])

    def test_un_nombre_de_rejets_ecrits_different_est_une_erreur(self):
        brut, _ = ranger_brut(self.racine)

        class Infidele:
            def remplacer(self, dataset, fichier, rejets):
                list(rejets)
                return 3

        with self.assertRaisesRegex(sorties.ErreurSortie, "3 rejets écrits dans PostgreSQL pour 5"):
            self.nettoyer(brut, pg=Infidele())

    def test_une_sortie_en_panne_laisse_les_fichiers_et_la_relance_aboutit(self):
        brut, _ = ranger_brut(self.racine)

        class EnPanne:
            def remplacer(self, dataset, fichier, rejets):
                raise sorties.ErreurSortie("PostgreSQL injoignable")

        with self.assertRaises(sorties.ErreurSortie):
            self.nettoyer(brut, pg=EnPanne())
        self.assertTrue((brut.parent / "propre" / f"{brut.stem}.csv").exists())
        pg = FauxRejetsPg()
        self.assertEqual(self.nettoyer(brut, pg=pg).rejets_postgres, 5)


class ChoixDuFichier(AvecDossier):
    def test_le_jour_retrouve_son_fichier_brut(self):
        brut, _ = ranger_brut(self.racine)
        self.assertEqual(np_.retrouver_brut(self.racine, date(2026, 10, 17)), brut)

    def test_un_jour_sans_fichier_demande_d_ingerer_d_abord(self):
        with self.assertRaisesRegex(np_.ErreurNettoyage, "etl-paris --day 2026-10-17"):
            np_.retrouver_brut(self.racine, date(2026, 10, 17))

    def test_deux_fichiers_pour_un_jour_demandent_de_choisir(self):
        ranger_brut(self.racine)
        ranger_brut(self.racine, LIGNES)
        with self.assertRaisesRegex(np_.ErreurNettoyage, "--file"):
            np_.retrouver_brut(self.racine, date(2026, 10, 17))

    def test_un_autre_jour_ne_correspond_pas(self):
        ranger_brut(self.racine, debut="20261018T000000Z", fin="20261019T000000Z")
        with self.assertRaises(np_.ErreurNettoyage):
            np_.retrouver_brut(self.racine, date(2026, 10, 17))


class LigneDeCommande(AvecDossier):
    def lancer(self, *arguments, pg=None, mongo=None):
        sortie, erreur = io.StringIO(), io.StringIO()
        environnement = {"MONGO_URL": "", "POSTGRES_URL": ""}
        with unittest.mock.patch.dict("os.environ", environnement), redirect_stdout(sortie), redirect_stderr(erreur):
            code = np_.principal(list(arguments), rejets_pg=pg, bilan_mongo=mongo)
        return code, sortie.getvalue(), erreur.getvalue()

    def test_le_resume_donne_les_volumes_les_regles_et_ou_le_taux_est_journalise(self):
        brut, _ = ranger_brut(self.racine)
        code, sortie, _ = self.lancer("--file", str(brut), pg=FauxRejetsPg(), mongo=FauxBilan())
        self.assertEqual(code, 0)
        for attendu in ("Lignes lues  : 12", "Propres      : 7", "Rejetées     : 5 (41.67%)", "MISSING_REQUIRED : 2", "DUPLICATE_KEY    : 1",
                        "MISSING_OCCUPANCY : 1", "dwh.etl_reject : 5 lignes écrites", "journalisé dans MongoDB processing_stats"):
            self.assertIn(attendu, sortie)
        self.assertNotIn("ALERTE", sortie)

    def test_sans_adresse_le_resume_dit_ce_qui_n_est_pas_ecrit(self):
        brut, _ = ranger_brut(self.racine)
        _, sortie, _ = self.lancer("--file", str(brut))
        self.assertIn("non écrit (pas d'adresse PostgreSQL)", sortie)
        self.assertIn("affiché seulement (pas d'adresse MongoDB)", sortie)

    def test_l_alerte_est_affichee_au_dessus_du_seuil(self):
        brut, _ = ranger_brut(self.racine)
        _, sortie, _ = self.lancer("--file", str(brut), "--alert-threshold", "0.1")
        self.assertIn("ALERTE : taux de rejet 41.67% au-dessus du seuil", sortie)

    def test_le_jour_est_retrouve_dans_le_dossier_des_donnees(self):
        brut, _ = ranger_brut(self.racine)
        code, sortie, _ = self.lancer("--day", "2026-10-17", "--data-dir", str(self.racine))
        self.assertEqual(code, 0)
        self.assertIn(brut.name, sortie)

    def test_les_erreurs_donnent_un_message_et_le_code_1(self):
        brut, _ = ranger_brut(self.racine)
        for arguments, fragment in (
            (("--day", "2026-10-01", "--data-dir", str(self.racine)), "Aucun fichier brut"),
            (("--file", str(brut), "--alert-threshold", "2"), "entre 0 et 1"),
            (("--file", str(self.racine / "x.csv")), "Nom inattendu"),
        ):
            with self.subTest(arguments=arguments):
                code, _, erreur = self.lancer(*arguments)
                self.assertEqual(code, 1)
                self.assertIn(fragment, erreur)

    def test_jour_et_fichier_s_excluent(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            np_.principal(["--day", "2026-10-17", "--file", "x.csv"])
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            np_.principal([])


# --- Sorties réelles, pilotes remplacés par des faux ---------------------------------------------------------------------
class FauxCurseur:
    def __init__(self, journal):
        self.journal = journal

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.journal.append(("execute", " ".join(sql.split()), params))

    def executemany(self, sql, lot):
        lot = list(lot)
        self.journal.append(("executemany", " ".join(sql.split()), lot))
        if getattr(self, "panne", None):
            raise self.panne


class FausseConnexion:
    def __init__(self, panne=None):
        self.journal = []
        self.panne = panne
        self.fermee = False

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
        curseur = FauxCurseur(self.journal)
        curseur.panne = self.panne
        return curseur

    def close(self):
        self.fermee = True


REJETS = [{"source_ref": f"f.csv#{n}", "rule": "MISSING_REQUIRED", "reason": "q vide", "payload": {"q": "", "n": str(n)}} for n in range(1, 6)]


@unittest.skipIf(psycopg is None, "psycopg absent : pip install -r data/etl/requirements.txt")
class SortiePostgres(unittest.TestCase):
    def test_remplacer_supprime_puis_insere_dans_une_seule_transaction(self):
        connexion = FausseConnexion()
        with unittest.mock.patch.object(sorties, "LOT", 2):
            ecrits = sorties.RejetsPostgres(connexion).remplacer("paris-comptages-routiers", "f.csv", iter(REJETS))
        self.assertEqual(ecrits, 5)
        self.assertEqual([e[0] for e in connexion.journal], ["begin", "execute", "executemany", "executemany", "executemany", "commit"])
        self.assertEqual(connexion.journal[1][1:], ("DELETE FROM dwh.etl_reject WHERE dataset = %s AND starts_with(source_ref, %s)",
                                                    ("paris-comptages-routiers", "f.csv#")))
        lots = [e[2] for e in connexion.journal if e[0] == "executemany"]
        self.assertEqual([len(lot) for lot in lots], [2, 2, 1])
        dataset, source_ref, regle, motif, payload = lots[0][0]
        self.assertEqual((dataset, source_ref, regle, motif), ("paris-comptages-routiers", "f.csv#1", "MISSING_REQUIRED", "q vide"))
        self.assertEqual(payload.obj, {"q": "", "n": "1"})

    def test_sans_rejet_l_ancien_contenu_du_fichier_est_quand_meme_supprime(self):
        connexion = FausseConnexion()
        self.assertEqual(sorties.RejetsPostgres(connexion).remplacer("d", "f.csv", iter([])), 0)
        self.assertEqual([e[0] for e in connexion.journal], ["begin", "execute", "commit"])

    def test_une_erreur_du_pilote_annule_la_transaction_et_devient_une_erreur_de_sortie(self):
        connexion = FausseConnexion(panne=psycopg.errors.InsufficientPrivilege("permission denied for table etl_reject"))
        with self.assertRaisesRegex(sorties.ErreurSortie, "InsufficientPrivilege"):
            sorties.RejetsPostgres(connexion).remplacer("d", "f.csv", iter(REJETS))
        self.assertEqual(connexion.journal[-1], ("rollback",))

    def test_les_colonnes_ecrites_existent_dans_la_migration(self):
        migration = (RACINE / "db" / "postgres" / "migrations" / "0002_dwh_faits.sql").read_text(encoding="utf-8")
        import re

        bloc = re.search(r"CREATE TABLE dwh\.etl_reject \((.*?)\n\);", migration, re.S).group(1)
        colonnes = {m.group(1): m.group(2) for m in re.finditer(r"^\s+(\w+)\s+(.*?),?$", bloc, re.M)}
        connexion = FausseConnexion()
        sorties.RejetsPostgres(connexion).remplacer("d", "f.csv", iter(REJETS[:1]))
        insertion = next(e[1] for e in connexion.journal if e[0] == "executemany")
        ecrites = [c.strip() for c in re.search(r"INSERT INTO dwh\.etl_reject \((.*?)\)", insertion).group(1).split(",")]
        self.assertTrue(set(ecrites) <= set(colonnes), set(ecrites) - set(colonnes))
        obligatoires = {c for c, definition in colonnes.items() if "NOT NULL" in definition and "DEFAULT" not in definition}
        self.assertTrue(obligatoires <= set(ecrites), f"colonnes obligatoires non écrites : {obligatoires - set(ecrites)}")


class FausseCollection:
    def __init__(self, panne=None):
        self.appels = []
        self.panne = panne

    def update_one(self, filtre, mise_a_jour, **options):
        self.appels.append((filtre, mise_a_jour, options))
        if self.panne:
            raise self.panne


@unittest.skipIf(pymongo is None, "pymongo absent : pip install -r data/etl/requirements.txt")
class SortieMongo(unittest.TestCase):
    VALEURS = {"dataset": "paris-comptages-routiers", "source_file": "f.csv", "source_sha256": "a" * 64, "rows_read": 12, "rows_clean": 8,
               "rows_rejected": 4, "reject_rate": 0.333333, "by_rule": {"MISSING_REQUIRED": 4}, "flags": {}, "alert_threshold": 0.5,
               "alert": False, "cleaned_at": MAINTENANT, "run_id": "net-1"}
    DEBUT = datetime(2026, 10, 17, tzinfo=UTC)

    def test_une_ecriture_qui_cree_ou_met_a_jour_le_document_du_fichier(self):
        collection = FausseCollection()
        sorties.BilanMongo(collection).enregistrer(self.VALEURS, fenetre_debut=self.DEBUT, sha256="a" * 64)
        (filtre, mise_a_jour, options), = collection.appels
        self.assertEqual(filtre, {"kind": "rejects", "window_start": self.DEBUT, "values.source_sha256": "a" * 64})
        self.assertTrue(options["upsert"])
        champs = mise_a_jour["$set"]
        self.assertEqual(champs["values.rows_read"], 12)
        self.assertEqual(champs["values.by_rule"], {"MISSING_REQUIRED": 4})
        self.assertNotIn("values.source_sha256", champs, "déjà dans le filtre")

    def test_les_erreurs_du_pilote_sont_expliquees(self):
        for panne, fragment in ((pymongo.errors.OperationFailure("not authorized", code=13), "code 13"),
                                (pymongo.errors.ServerSelectionTimeoutError("timeout"), "injoignable")):
            with self.subTest(fragment=fragment), self.assertRaisesRegex(sorties.ErreurSortie, fragment):
                sorties.BilanMongo(FausseCollection(panne)).enregistrer(self.VALEURS, fenetre_debut=self.DEBUT, sha256="a" * 64)

    def test_le_document_cree_respecte_le_validateur_de_processing_stats(self):
        import shutil

        if shutil.which("node") is None:
            self.skipTest("Node.js absent : le script d'initialisation MongoDB n'est pas exécutable")
        sys.path.insert(0, str(RACINE / "scripts" / "dev"))
        from test_dictionnaire import extraire_mongo

        schema = extraire_mongo()["collections"]["processing_stats"]
        collection = FausseCollection()
        brut, _ = ranger_brut(Path(tempfile.mkdtemp()))
        self.addCleanup(lambda: __import__("shutil").rmtree(brut.parents[1], ignore_errors=True))
        np_.nettoyer_fichier(brut, bilan_mongo=sorties.BilanMongo(collection), maintenant=lambda: MAINTENANT)
        filtre, mise_a_jour, _ = collection.appels[0]
        # Ce que MongoDB écrit à la création : les égalités du filtre, puis les champs du $set (chemins pointés).
        document = {"kind": filtre["kind"], "window_start": filtre["window_start"], "values": {"source_sha256": filtre["values.source_sha256"]}}
        for chemin, valeur in mise_a_jour["$set"].items():
            document[chemin.split(".")[0]][chemin.split(".", 1)[1]] = valeur
        verifier_contre_le_validateur(document, schema)
        self.assertEqual(document["kind"], "rejects")
        self.assertEqual(document["values"]["rows_rejected"], 5)


if __name__ == "__main__":
    unittest.main()
