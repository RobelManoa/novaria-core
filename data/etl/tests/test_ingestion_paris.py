"""Tests de l'ingestion du comptage routier de Paris (DAT-03). Aucun accès au réseau ni à MongoDB.

    python -m unittest discover -s data/etl/tests

L'échantillon est fabriqué : mêmes colonnes, même forme que l'export du portail (BOM, fins de ligne CRLF, séparateur
« ; », q et k vides, forme géographique entre guillemets doublés), valeurs inventées. Aucune donnée réelle n'est versionnée.
"""

import csv
import gzip
import hashlib
import io
import json
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error
import urllib.parse
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "data" / "etl"))

from pipelines import ingerer_paris, journal  # noqa: E402
from pipelines import paris_comptages as paris  # noqa: E402

try:
    import pymongo  # noqa: F401
except ImportError:
    pymongo = None

DEBUT = datetime(2026, 10, 18, 10, tzinfo=UTC)
FIN = DEBUT + timedelta(hours=1)
MAINTENANT = datetime(2026, 10, 29, 12, 0, 5, tzinfo=UTC)
FORME = '{"coordinates": [[2.3103, 48.8625], [2.3111, 48.8627]], "type": "LineString"}'
LIGNES = [
    ("4392", "Quai_d'Orsay", "2026-10-18T10:00:00+00:00", "199.0", "2.03556", "Fluide", "2349", "Pl_de_Finlande", "189",
     "Pt_Alexandre_III_Gauche", "Ouvert", "1996-10-14", "2023-01-01", "48.8627, 2.3118", FORME),
    ("324", "Pt_Alexandre_III", "2026-10-18T10:00:00+00:00", "", "", "Inconnu", "165", "Pt_Alexandre_III_Droite", "189",
     "Pt_Alexandre_III_Gauche", "Invalide", "1996-10-03", "2023-01-01", "48.8637, 2.3134", FORME),
    ("327", "Bd_St_Germain", "2026-10-18T10:00:00+00:00", "1314.0", "10.36056", "Fluide", "186", "Pt_Concorde_Gauche", "190",
     "Bd_St_Germain-A.Briand", "Ouvert", "1996-10-03", "2023-01-01", "48.8623, 2.3193", FORME),
    ("193", "Sts_Peres", "2026-10-18T10:00:00+00:00", "167.0", "", "Fluide", "120", "Bd_St_Germain-Sts_Peres", "117",
     "Sts_Peres-Grenelle", "Ouvert", "1996-10-03", "2023-01-01", "48.8535, 2.3298", FORME),
    ("501", "Bd_Peripherique", "2026-10-18T10:00:00+00:00", "2400.0", "31.5", "Saturé", "7", "Porte_A", "8", "Porte_B",
     "Ouvert", "1996-10-03", "2023-01-01", "48.8000, 2.3000", FORME),
    ("502", "Bd_Peripherique", "2026-10-18T10:00:00+00:00", "100.0", "55.1", "Bloqué", "8", "Porte_B", "9", "Porte_C",
     "Barré", "1996-10-03", "2023-01-01", "48.8100, 2.3100", FORME),
    ("503", "Av_de_la_Republique", "2026-10-18T10:00:00+00:00", "800.0", "22.0", "Pré-saturé", "10", "Pl_A", "11", "Pl_B",
     "Ouvert", "1996-10-03", "2023-01-01", "48.8200, 2.3200", FORME),
    ("504", "Rue_Sans_Etat", "2026-10-18T10:00:00+00:00", "50.0", "1.2", "", "12", "Pl_C", "13", "Pl_D",
     "Ouvert", "1996-10-03", "2023-01-01", "48.8300, 2.3300", FORME),
]


def setUpModule():
    """Garde-fou : un test qui atteindrait le réseau échoue au lieu de télécharger quoi que ce soit."""
    def interdit(*_, **__):
        raise AssertionError("Accès réseau interdit dans les tests de data/etl")

    patcheur = unittest.mock.patch("urllib.request.urlopen", interdit)
    patcheur.start()
    unittest.addModuleCleanup(patcheur.stop)


def fabriquer_csv(lignes=LIGNES, entete=paris.COLONNES, bom=True) -> bytes:
    sortie = io.StringIO(newline="")
    ecrivain = csv.writer(sortie, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow(entete)
    ecrivain.writerows(lignes)
    return (b"\xef\xbb\xbf" if bom else b"") + sortie.getvalue().encode("utf-8")


class FauxPortail:
    """Sert les mêmes octets à chaque appel (comme l'export trié du portail) et note les adresses demandées."""

    def __init__(self, octets: bytes, metadonnees: bool = True):
        self.octets = octets
        self.adresses = []
        self.metadonnees = metadonnees

    def __call__(self, requete, delai):
        self.adresses.append(requete.full_url)
        if requete.full_url == paris.ADRESSE_JEU:
            if not self.metadonnees:
                raise urllib.error.URLError("hors ligne")
            corps = {"metas": {"default": {"data_processed": "2026-10-19T01:02:43+00:00"}}}
            return io.BytesIO(gzip.compress(json.dumps(corps).encode()))
        return io.BytesIO(self.octets)


class FauxJournal:
    def __init__(self):
        self.entrees = {}
        self.executions = {}

    def enregistrer(self, entree, *, maintenant, run_id):
        cle = entree["load_key"]
        self.entrees.setdefault(cle, {**entree, "run_id": run_id, "ingested_at": maintenant})
        self.executions[cle] = self.executions.get(cle, 0) + 1
        return journal.Passage(nouveau=self.executions[cle] == 1, executions=self.executions[cle])


class JournalEnPanne:
    def enregistrer(self, entree, *, maintenant, run_id):
        raise journal.ErreurJournal("MongoDB injoignable")


class AvecDossier(unittest.TestCase):
    def setUp(self):
        temporaire = tempfile.TemporaryDirectory()
        self.addCleanup(temporaire.cleanup)
        self.racine = Path(temporaire.name)
        self.dossier = self.racine / paris.DATASET_ID

    def fichiers(self):
        return sorted(p.name for p in self.dossier.iterdir()) if self.dossier.exists() else []


class FenetreEtAdresse(unittest.TestCase):
    def test_un_jour_va_de_minuit_a_minuit_en_utc(self):
        self.assertEqual(paris.fenetre_du_jour(date(2026, 10, 18)),
                         (datetime(2026, 10, 18, tzinfo=UTC), datetime(2026, 10, 19, tzinfo=UTC)))

    def test_les_bornes_sans_fuseau_sont_refusees(self):
        with self.assertRaisesRegex(ValueError, "fuseau"):
            paris.verifier_fenetre(datetime(2026, 10, 18), FIN)

    def test_une_fenetre_vide_ou_a_l_envers_est_refusee(self):
        for debut, fin in ((DEBUT, DEBUT), (FIN, DEBUT)):
            with self.subTest(fin=fin), self.assertRaisesRegex(ValueError, "suivre"):
                paris.verifier_fenetre(debut, fin)

    def test_sept_jours_passent_et_plus_sont_refuses(self):
        paris.verifier_fenetre(DEBUT, DEBUT + timedelta(days=7))
        with self.assertRaisesRegex(ValueError, "trop longue"):
            paris.verifier_fenetre(DEBUT, DEBUT + timedelta(days=7, seconds=1))

    def test_les_bornes_sont_ramenees_en_utc(self):
        paris_ete = timezone_plus_deux()
        debut, fin = paris.verifier_fenetre(DEBUT.astimezone(paris_ete), FIN.astimezone(paris_ete))
        self.assertEqual((debut, fin), (DEBUT, FIN))
        self.assertEqual(debut.utcoffset(), timedelta(0))

    def test_l_adresse_demande_la_fenetre_triee_en_csv_a_point_virgule(self):
        morceaux = urllib.parse.urlsplit(paris.adresse_export(DEBUT, FIN))
        requete = urllib.parse.parse_qs(morceaux.query)
        self.assertEqual((morceaux.scheme, morceaux.hostname), ("https", "opendata.paris.fr"))
        self.assertTrue(morceaux.path.endswith("/comptages-routiers-permanents/exports/csv"))
        self.assertEqual(requete["where"], ["t_1h >= date'2026-10-18T10:00:00Z' AND t_1h < date'2026-10-18T11:00:00Z'"])
        self.assertEqual(requete["order_by"], ["t_1h, iu_ac"])
        self.assertEqual(requete["delimiter"], [";"])
        self.assertEqual(requete["limit"], ["-1"])


def timezone_plus_deux():
    from datetime import timezone

    return timezone(timedelta(hours=2))


class Telechargement(AvecDossier):
    def test_les_octets_sont_ranges_tels_que_recus_avec_leur_empreinte(self):
        octets = fabriquer_csv()
        resultat = paris.telecharger(paris.adresse_export(DEBUT, FIN), self.dossier, ouvrir=FauxPortail(octets))
        self.assertEqual(resultat.chemin.read_bytes(), octets)
        self.assertEqual(resultat.sha256, hashlib.sha256(octets).hexdigest())
        self.assertEqual(resultat.octets, len(octets))

    def test_une_adresse_hors_du_portail_n_est_jamais_appelee(self):
        for adresse in ("http://opendata.paris.fr/x", "https://example.org/x", "https://opendata.paris.fr.example.org/x",
                        "file:///etc/passwd"):
            portail = FauxPortail(b"x")
            with self.subTest(adresse=adresse), self.assertRaises(paris.ErreurSource):
                paris.telecharger(adresse, self.dossier, ouvrir=portail)
            self.assertEqual(portail.adresses, [])

    def test_un_fichier_trop_gros_interrompt_le_telechargement_sans_rien_laisser(self):
        with self.assertRaisesRegex(paris.ErreurSource, "plus gros"):
            paris.telecharger(paris.adresse_export(DEBUT, FIN), self.dossier, ouvrir=FauxPortail(b"x" * 100), taille_max=99)
        self.assertEqual(self.fichiers(), [])

    def test_une_erreur_reseau_devient_une_erreur_de_source_sans_fichier_provisoire(self):
        def en_panne(requete, delai):
            raise urllib.error.URLError("pas de réseau")

        with self.assertRaisesRegex(paris.ErreurSource, "impossible"):
            paris.telecharger(paris.adresse_export(DEBUT, FIN), self.dossier, ouvrir=en_panne)
        self.assertEqual(self.fichiers(), [])


class Analyse(AvecDossier):
    def analyser(self, octets: bytes) -> int:
        self.dossier.mkdir(parents=True, exist_ok=True)
        chemin = self.dossier / "essai.csv"
        chemin.write_bytes(octets)
        return paris.analyser(chemin)

    def test_l_echantillon_compte_ses_lignes_malgre_le_bom_et_les_guillemets(self):
        self.assertEqual(self.analyser(fabriquer_csv()), len(LIGNES))
        self.assertEqual(self.analyser(fabriquer_csv(bom=False)), len(LIGNES))

    def test_les_valeurs_vides_ne_sont_pas_des_erreurs_du_brut(self):
        # q et k vides, état vide : ce sont des cas du nettoyage (DAT-04), le brut les garde.
        self.assertEqual(self.analyser(fabriquer_csv([LIGNES[1], LIGNES[7]])), 2)

    def test_un_en_tete_different_est_refuse(self):
        for entete in (paris.COLONNES[:-1], paris.COLONNES[::-1], ("Erreur",)):
            with self.subTest(entete=entete), self.assertRaisesRegex(paris.ErreurSource, "En-tête"):
                self.analyser(fabriquer_csv(entete=entete))

    def test_une_ligne_au_mauvais_nombre_de_colonnes_est_refusee(self):
        with self.assertRaisesRegex(paris.ErreurSource, "Ligne de données 2"):
            self.analyser(fabriquer_csv([LIGNES[0], LIGNES[1][:-1]]))

    def test_aucune_ligne_n_est_refuse(self):
        with self.assertRaisesRegex(paris.ErreurSource, "Aucune ligne"):
            self.analyser(fabriquer_csv([]))

    def test_une_page_d_erreur_ou_du_texte_non_utf8_est_refuse(self):
        for octets in (b'{"error_code": "InvalidWhere"}', "é".encode("latin-1") * 3, gzip.compress(fabriquer_csv()), b""):
            with self.subTest(octets=octets[:12]), self.assertRaises(paris.ErreurSource):
                self.analyser(octets)


class Ingestion(AvecDossier):
    def ingerer(self, portail, journal_=None, **options):
        journal_ = journal_ if journal_ is not None else self.journal
        return ingerer_paris.ingerer(DEBUT, FIN, racine=self.racine, journal=journal_, ouvrir=portail,
                                     maintenant=lambda: MAINTENANT, **options)

    def setUp(self):
        super().setUp()
        self.journal = FauxJournal()
        self.octets = fabriquer_csv()

    def test_premiere_execution_range_le_brut_et_ecrit_une_entree(self):
        resultat = self.ingerer(FauxPortail(self.octets), run_id="ing-essai")
        empreinte = hashlib.sha256(self.octets).hexdigest()
        nom = f"20261018T100000Z_20261018T110000Z_{empreinte[:12]}.csv"
        self.assertEqual(self.fichiers(), [nom])
        self.assertEqual((self.dossier / nom).read_bytes(), self.octets)
        self.assertEqual((resultat.fichier_ecrit, resultat.nouveau, resultat.executions), (True, True, 1))
        self.assertEqual(self.journal.entrees[resultat.load_key], {
            "load_key": f"paris-comptages-routiers:20261018T100000Z:20261018T110000Z:{empreinte}",
            "dataset_id": "paris-comptages-routiers",
            "source_type": "REAL_HISTORICAL",
            "source_url": paris.adresse_export(DEBUT, FIN),
            "license": "ODbL",
            "window_start": DEBUT,
            "window_end": FIN,
            "file_path": f"paris-comptages-routiers/{nom}",
            "sha256": empreinte,
            "bytes": len(self.octets),
            "rows": len(LIGNES),
            "source_modified_at": datetime(2026, 10, 19, 1, 2, 43, tzinfo=UTC),
            "run_id": "ing-essai",
            "ingested_at": MAINTENANT,
        })

    def test_la_seconde_execution_ne_cree_ni_fichier_ni_entree(self):
        premiere = self.ingerer(FauxPortail(self.octets))
        date_du_fichier = premiere.fichier.stat().st_mtime_ns
        seconde = self.ingerer(FauxPortail(self.octets))
        self.assertEqual(len(self.fichiers()), 1)
        self.assertEqual(len(self.journal.entrees), 1)
        self.assertEqual(seconde.fichier, premiere.fichier)
        self.assertEqual((seconde.fichier_ecrit, seconde.nouveau, seconde.executions), (False, False, 2))
        self.assertEqual(seconde.fichier.stat().st_mtime_ns, date_du_fichier, "le fichier ne doit pas être réécrit")

    def test_une_donnee_corrigee_a_la_source_donne_un_second_fichier_et_garde_le_premier(self):
        premiere = self.ingerer(FauxPortail(self.octets))
        corrigee = fabriquer_csv(LIGNES[:-1])
        seconde = self.ingerer(FauxPortail(corrigee))
        self.assertNotEqual(premiere.fichier, seconde.fichier)
        self.assertEqual(premiere.fichier.read_bytes(), self.octets)
        self.assertEqual(seconde.fichier.read_bytes(), corrigee)
        self.assertEqual((len(self.fichiers()), len(self.journal.entrees)), (2, 2))
        self.assertTrue(seconde.nouveau)

    def test_un_fichier_modifie_sur_le_disque_est_detecte_et_rien_n_est_journalise(self):
        premiere = self.ingerer(FauxPortail(self.octets))
        premiere.fichier.write_bytes(b"modifie")
        with self.assertRaises(ingerer_paris.ErreurIntegrite):
            self.ingerer(FauxPortail(self.octets))
        self.assertEqual(self.journal.executions[premiere.load_key], 1)
        self.assertEqual([n for n in self.fichiers() if n.endswith(".part")], [])

    def test_un_journal_en_panne_laisse_le_fichier_et_la_relance_complete_l_entree(self):
        with self.assertRaises(journal.ErreurJournal):
            self.ingerer(FauxPortail(self.octets), JournalEnPanne())
        self.assertEqual(len(self.fichiers()), 1)
        relance = self.ingerer(FauxPortail(self.octets))
        self.assertEqual((relance.fichier_ecrit, relance.nouveau), (False, True))
        self.assertEqual(len(self.fichiers()), 1)

    def test_une_reponse_invalide_ne_laisse_rien_et_n_ecrit_rien(self):
        for octets in (fabriquer_csv(entete=("a", "b")), fabriquer_csv([]), b""):
            with self.subTest(octets=octets[:20]), self.assertRaises(paris.ErreurSource):
                self.ingerer(FauxPortail(octets))
            self.assertEqual(self.fichiers(), [])
            self.assertEqual(self.journal.entrees, {})

    def test_une_fenetre_invalide_n_appelle_pas_le_portail(self):
        portail = FauxPortail(self.octets)
        with self.assertRaises(ValueError):
            ingerer_paris.ingerer(FIN, DEBUT, racine=self.racine, journal=self.journal, ouvrir=portail)
        self.assertEqual(portail.adresses, [])

    def test_sans_les_metadonnees_du_portail_l_entree_n_a_pas_de_date_de_mise_a_jour(self):
        resultat = self.ingerer(FauxPortail(self.octets, metadonnees=False))
        self.assertNotIn("source_modified_at", self.journal.entrees[resultat.load_key])

    def test_le_run_id_par_defaut_est_unique_et_horodate(self):
        self.ingerer(FauxPortail(self.octets))
        self.ingerer(FauxPortail(fabriquer_csv(LIGNES[:3])))
        identifiants = {e["run_id"] for e in self.journal.entrees.values()}
        self.assertEqual(len(identifiants), 2)
        self.assertTrue(all(i.startswith("ing-20261029T120005Z-") for i in identifiants))


class LigneDeCommande(AvecDossier):
    def lancer(self, *arguments, journal_=None):
        sortie, erreur = io.StringIO(), io.StringIO()
        from contextlib import redirect_stderr, redirect_stdout

        with redirect_stdout(sortie), redirect_stderr(erreur):
            code = ingerer_paris.principal([*arguments, "--data-dir", str(self.racine)], journal=journal_ or FauxJournal(),
                                           ouvrir=FauxPortail(self.octets))
        return code, sortie.getvalue(), erreur.getvalue()

    def setUp(self):
        super().setUp()
        self.octets = fabriquer_csv()

    def test_un_jour_est_ingere_et_le_resume_donne_volume_et_empreinte(self):
        code, sortie, _ = self.lancer("--day", "2026-10-18")
        self.assertEqual(code, 0)
        self.assertIn(f"{len(self.octets)} octets, {len(LIGNES)} lignes de données", sortie)
        self.assertIn(hashlib.sha256(self.octets).hexdigest(), sortie)
        self.assertIn("nouvelle entrée", sortie)

    def test_start_sans_end_est_refuse(self):
        with self.assertRaises(SystemExit), redirect_stderr_silencieux():
            self.lancer("--start", "2026-10-18T10:00:00Z")

    def test_day_avec_end_est_refuse(self):
        with self.assertRaises(SystemExit), redirect_stderr_silencieux():
            self.lancer("--day", "2026-10-18", "--end", "2026-10-19T00:00:00Z")

    def test_une_fenetre_trop_longue_donne_un_message_et_le_code_1(self):
        code, _, erreur = self.lancer("--start", "2026-10-01T00:00:00Z", "--end", "2026-10-30T00:00:00Z")
        self.assertEqual(code, 1)
        self.assertIn("trop longue", erreur)

    def test_sans_adresse_mongodb_le_message_explique_quoi_faire(self):
        sortie, erreur = io.StringIO(), io.StringIO()
        from contextlib import redirect_stderr, redirect_stdout

        with redirect_stdout(sortie), redirect_stderr(erreur):
            code = ingerer_paris.principal(["--day", "2026-10-18", "--data-dir", str(self.racine), "--mongo-url", ""])
        self.assertEqual(code, 1)
        self.assertIn("MONGO_URL", erreur.getvalue())


def redirect_stderr_silencieux():
    from contextlib import redirect_stderr

    return redirect_stderr(io.StringIO())


class FausseCollection:
    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = []

    def find_one_and_update(self, filtre, mise_a_jour, **options):
        self.appels.append((filtre, mise_a_jour, options))
        reponse = self.reponses.pop(0)
        if isinstance(reponse, Exception):
            raise reponse
        return reponse


ENTREE = {
    "load_key": "paris-comptages-routiers:20261018T100000Z:20261018T110000Z:" + "a" * 64,
    "dataset_id": "paris-comptages-routiers", "source_type": "REAL_HISTORICAL",
    "source_url": "https://opendata.paris.fr/x", "license": "ODbL", "window_start": DEBUT, "window_end": FIN,
    "file_path": "paris-comptages-routiers/x.csv", "sha256": "a" * 64, "bytes": 10, "rows": 2,
}


@unittest.skipIf(pymongo is None, "pymongo absent : pip install -r data/etl/requirements.txt")
class JournalMongo(unittest.TestCase):
    def enregistrer(self, reponses):
        collection = FausseCollection(reponses)
        passage = journal.JournalMongo(collection).enregistrer(ENTREE, maintenant=MAINTENANT, run_id="ing-1")
        return passage, collection

    def test_une_seule_ecriture_atomique_cree_ou_incremente(self):
        passage, collection = self.enregistrer([{"executions": 1}])
        (filtre, mise_a_jour, options), = collection.appels
        self.assertEqual(filtre, {"load_key": ENTREE["load_key"]})
        self.assertTrue(options["upsert"])
        self.assertIs(options["return_document"], pymongo.ReturnDocument.AFTER)
        self.assertEqual(mise_a_jour["$inc"], {"executions": 1})
        self.assertEqual(mise_a_jour["$set"], {"last_seen_at": MAINTENANT, "last_run_id": "ing-1"})
        creation = mise_a_jour["$setOnInsert"]
        self.assertEqual((creation["run_id"], creation["ingested_at"]), ("ing-1", MAINTENANT))
        self.assertNotIn("load_key", creation)
        self.assertTrue(set(creation) | {"load_key"} >= set(ENTREE))
        self.assertEqual(passage, journal.Passage(nouveau=True, executions=1))

    def test_un_fichier_deja_vu_n_est_pas_nouveau(self):
        passage, _ = self.enregistrer([{"executions": 3}])
        self.assertEqual(passage, journal.Passage(nouveau=False, executions=3))

    def test_droits_ou_collection_absents_expliquent_le_db_reset(self):
        from pymongo.errors import OperationFailure

        with self.assertRaisesRegex(journal.ErreurJournal, "db-reset"):
            self.enregistrer([OperationFailure("not authorized", code=13)])

    def test_le_refus_du_validateur_est_signale(self):
        from pymongo.errors import OperationFailure

        with self.assertRaisesRegex(journal.ErreurJournal, "validateur"):
            self.enregistrer([OperationFailure("Document failed validation", code=121)])

    def test_une_base_injoignable_est_signalee(self):
        from pymongo.errors import ServerSelectionTimeoutError

        with self.assertRaisesRegex(journal.ErreurJournal, "injoignable"):
            self.enregistrer([ServerSelectionTimeoutError("timeout")])

    def test_une_course_sur_la_cle_est_rejouee_une_fois(self):
        from pymongo.errors import DuplicateKeyError

        passage, collection = self.enregistrer([DuplicateKeyError("E11000", code=11000), {"executions": 2}])
        self.assertEqual((len(collection.appels), passage.nouveau), (2, False))
        with self.assertRaisesRegex(journal.ErreurJournal, "relancer"):
            self.enregistrer([DuplicateKeyError("E11000", code=11000), DuplicateKeyError("E11000", code=11000)])


def verifier_contre_le_validateur(document: dict, schema: dict):
    """Contrôle minimal d'un document contre un $jsonSchema : champs obligatoires, types, motifs, bornes, énumérations."""
    import re

    manquants = [champ for champ in schema["required"] if champ not in document]
    if manquants:
        raise AssertionError(f"champs obligatoires absents : {manquants}")
    for champ, regle in schema["properties"].items():
        if champ not in document:
            continue
        valeur = document[champ]
        type_attendu = regle.get("bsonType")
        types = {"string": str, "date": datetime, "number": (int, float)}
        if type_attendu and not isinstance(valeur, types[type_attendu]):
            raise AssertionError(f"{champ} : type {type(valeur).__name__} au lieu de {type_attendu}")
        if "enum" in regle and valeur not in regle["enum"]:
            raise AssertionError(f"{champ} : {valeur!r} hors énumération")
        if "pattern" in regle and not re.search(regle["pattern"], valeur):
            raise AssertionError(f"{champ} : {valeur!r} ne respecte pas {regle['pattern']}")
        if "minimum" in regle and valeur < regle["minimum"]:
            raise AssertionError(f"{champ} : {valeur} sous le minimum")
        if "minLength" in regle and len(valeur) < regle["minLength"]:
            raise AssertionError(f"{champ} : trop court")


@unittest.skipIf(pymongo is None, "pymongo absent : pip install -r data/etl/requirements.txt")
class EntreeEtValidateurMongo(unittest.TestCase):
    """Le document écrit par le pipeline respecte le validateur de db/mongo/init (même source que le dictionnaire)."""

    def test_le_document_cree_par_une_premiere_execution_est_accepte_par_le_validateur(self):
        import shutil

        if shutil.which("node") is None:
            self.skipTest("Node.js absent : le script d'initialisation MongoDB n'est pas exécutable")
        sys.path.insert(0, str(RACINE / "scripts" / "dev"))
        from test_dictionnaire import extraire_mongo

        schema = extraire_mongo()["collections"]["ingestion_runs"]
        collection = FausseCollection([{"executions": 1}])
        portail = FauxPortail(fabriquer_csv())
        with tempfile.TemporaryDirectory() as dossier:
            ingerer_paris.ingerer(DEBUT, FIN, racine=Path(dossier), journal=journal.JournalMongo(collection), ouvrir=portail,
                                  maintenant=lambda: MAINTENANT)
        filtre, mise_a_jour, _ = collection.appels[0]
        cree = {**filtre, **mise_a_jour["$setOnInsert"], **mise_a_jour["$set"], "executions": 1}
        verifier_contre_le_validateur(cree, schema)
        self.assertEqual(set(cree) - set(schema["properties"]), set(), "champ écrit mais absent du validateur")

    def test_le_controle_detecte_un_document_hors_validateur(self):
        schema = {"required": ["a"], "properties": {"a": {"bsonType": "string", "pattern": "^x"}}}
        for document in ({}, {"a": 1}, {"a": "y"}):
            with self.subTest(document=document), self.assertRaises(AssertionError):
                verifier_contre_le_validateur(document, schema)


if __name__ == "__main__":
    unittest.main()
