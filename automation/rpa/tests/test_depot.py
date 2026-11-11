import hashlib
import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from tests.donnees import RACINE

from rapport import depot, periode

SEMAINE = periode.semaine_de(datetime(2026, 10, 22, tzinfo=UTC).date())
MAINTENANT = datetime(2026, 10, 26, 6, 0, tzinfo=UTC)
PDF = b"%PDF-1.4\n%contenu\n%%EOF\n"


class Depot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dossier = Path(self._tmp.name) / "rapports"

    def deposer(self, pdf=PDF, quand=MAINTENANT):
        return depot.deposer(self.dossier, SEMAINE, "Rapport essai", pdf, quand)

    def test_le_pdf_et_les_metadonnees_sont_deposes_sous_l_identifiant(self):
        resultat = self.deposer()
        self.assertEqual(sorted(p.name for p in self.dossier.iterdir()), sorted([f"{resultat.identifiant}.json", f"{resultat.identifiant}.pdf"]))
        self.assertEqual(resultat.chemin_pdf.read_bytes(), PDF)

    def test_les_metadonnees_decrivent_le_fichier_exactement(self):
        meta = json.loads(self.deposer().chemin_metadonnees.read_text(encoding="utf-8"))
        self.assertEqual(meta["size_bytes"], len(PDF))
        self.assertEqual(meta["sha256"], hashlib.sha256(PDF).hexdigest())
        self.assertEqual(meta["content_type"], "application/pdf")
        self.assertEqual(meta["file_name"], "rapport-hebdomadaire-2026-S43.pdf")
        self.assertEqual((meta["period_start"], meta["period_end"]), ("2026-10-19T00:00:00Z", "2026-10-26T00:00:00Z"))
        self.assertEqual(meta["generated_at"], "2026-10-26T06:00:00Z")
        self.assertEqual(set(meta), {"report_id", "title", "period_start", "period_end", "generated_at", "file_name", "size_bytes", "content_type", "sha256"})

    def test_les_metadonnees_sont_acceptees_par_le_validateur_de_l_api(self):
        racine_api = RACINE.parents[1] / "services" / "traitement"
        sys.path.insert(0, str(racine_api))
        try:
            from app.schemas.reports import ReportMetadata
        except ImportError:
            self.skipTest("les dépendances de l'API (pydantic) ne sont pas installées")
        finally:
            sys.path.remove(str(racine_api))
        meta = json.loads(self.deposer().chemin_metadonnees.read_text(encoding="utf-8"))
        self.assertEqual(str(ReportMetadata.model_validate(meta).report_id), meta["report_id"])

    def test_le_meme_rapport_garde_son_identifiant_et_se_remplace_sans_doublon(self):
        premier = self.deposer()
        second = self.deposer(pdf=PDF + b"%changement\n", quand=datetime(2026, 10, 27, tzinfo=UTC))
        self.assertEqual(premier.identifiant, second.identifiant)
        self.assertEqual((premier.remplace, second.remplace), (False, True))
        self.assertEqual(len(list(self.dossier.glob("*.json"))), 1)
        self.assertEqual(len(list(self.dossier.glob("*.pdf"))), 1)
        meta = json.loads(second.chemin_metadonnees.read_text(encoding="utf-8"))
        self.assertEqual(meta["size_bytes"], len(PDF + b"%changement\n"))
        self.assertEqual(meta["generated_at"], "2026-10-27T00:00:00Z")

    def test_une_autre_periode_donne_un_autre_rapport(self):
        autre = depot.deposer(self.dossier, periode.semaine_de(datetime(2026, 10, 29, tzinfo=UTC).date()), "t", PDF, MAINTENANT)
        self.assertNotEqual(self.deposer().identifiant, autre.identifiant)
        self.assertEqual(len(list(self.dossier.glob("*.json"))), 2)

    def test_l_identifiant_est_stable_d_une_machine_a_l_autre(self):
        self.assertEqual(str(depot.identifiant(SEMAINE)), str(depot.identifiant(periode.semaine_de(datetime(2026, 10, 25, tzinfo=UTC).date()))))

    def test_le_pdf_est_ecrit_avant_les_metadonnees(self):
        ordre = []
        reel = depot._ecrire
        with mock.patch.object(depot, "_ecrire", side_effect=lambda chemin, contenu: (ordre.append(chemin.suffix), reel(chemin, contenu))):
            self.deposer()
        self.assertEqual(ordre, [".pdf", ".json"])

    def test_un_echec_avant_les_metadonnees_ne_laisse_aucun_rapport_listable(self):
        premier = self.deposer()
        reel = depot._ecrire

        def echoue_sur_json(chemin, contenu):
            if chemin.suffix == ".json":
                raise OSError("disque plein")
            reel(chemin, contenu)

        with mock.patch.object(depot, "_ecrire", side_effect=echoue_sur_json), self.assertRaises(OSError):
            self.deposer(pdf=PDF + b"%x\n")
        self.assertFalse(premier.chemin_metadonnees.exists(), "un PDF sans métadonnées valides n'est pas listé")

    def test_aucun_fichier_temporaire_ne_reste(self):
        self.deposer()
        with mock.patch.object(depot.os, "replace", side_effect=OSError("échec")), self.assertRaises(OSError):
            self.deposer(pdf=PDF + b"%y\n")
        self.assertEqual([p.name for p in self.dossier.iterdir() if p.name.startswith(".depot-")], [])

    @unittest.skipIf(sys.platform == "win32", "les droits POSIX n'existent pas sous Windows")
    def test_les_fichiers_sont_lisibles_par_le_compte_du_service_de_lecture(self):
        resultat = self.deposer()
        for chemin in (resultat.chemin_pdf, resultat.chemin_metadonnees):
            self.assertEqual(chemin.stat().st_mode & 0o777, 0o644, chemin.name)

    def test_le_nom_de_fichier_respecte_le_motif_du_contrat(self):
        self.assertRegex(depot.nom_de_fichier(SEMAINE), r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,199}$")

    def test_le_titre_est_borne_a_deux_cents_caracteres(self):
        resultat = depot.deposer(self.dossier, SEMAINE, "x" * 500, PDF, MAINTENANT)
        self.assertEqual(len(resultat.metadonnees["title"]), 200)


class Notification(unittest.TestCase):
    def test_chaque_notification_ajoute_une_ligne_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            dossier = Path(tmp)
            depot.notifier(dossier, "INFO", "premier", MAINTENANT)
            depot.notifier(dossier, "ERREUR", "deuxième", MAINTENANT)
            lignes = [json.loads(x) for x in (dossier / depot.NOM_NOTIFICATIONS).read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(x["niveau"], x["message"]) for x in lignes], [("INFO", "premier"), ("ERREUR", "deuxième")])
        self.assertEqual(lignes[0]["ts"], "2026-10-26T06:00:00Z")

    def test_le_journal_des_notifications_n_est_pas_pris_pour_un_rapport(self):
        self.assertNotEqual(Path(depot.NOM_NOTIFICATIONS).suffix, ".json")


if __name__ == "__main__":
    unittest.main()
