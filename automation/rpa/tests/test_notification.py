"""Notification du robot : le journal toujours ; le courriel en plus, sans jamais faire échouer le rapport."""

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from rapport import courriel, notification

QUAND = datetime(2026, 10, 26, 6, 0, tzinfo=UTC)
COURRIEL = {"NOVARIA_RPA_SMTP": "127.0.0.1:1025", "NOVARIA_RPA_DESTINATAIRE": "equipe@example.org"}


class SmtpEnregistre:
    envois: list = []

    def __init__(self, hote, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def ehlo(self):
        pass

    def send_message(self, message):
        SmtpEnregistre.envois.append(message)


class SmtpEnPanne(SmtpEnregistre):
    def send_message(self, message):
        raise ConnectionResetError("secret-smtp-12 coupé")


class Notification(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dossier = Path(self._tmp.name)
        SmtpEnregistre.envois = []

    def lignes(self):
        return [json.loads(ligne) for ligne in (self.dossier / "notifications.log").read_text(encoding="utf-8").splitlines()]

    def test_sans_courriel_seul_le_journal_est_ecrit(self):
        notification.notifier(self.dossier, "INFO", "rapport déposé", QUAND, {}, fabrique=SmtpEnregistre)
        self.assertEqual([(ligne["niveau"], ligne["message"]) for ligne in self.lignes()], [("INFO", "rapport déposé")])
        self.assertEqual(SmtpEnregistre.envois, [])

    def test_avec_courriel_le_journal_puis_le_courriel(self):
        notification.notifier(self.dossier, "INFO", "rapport 2026-S43 déposé", QUAND, COURRIEL, fabrique=SmtpEnregistre)
        self.assertEqual([ligne["niveau"] for ligne in self.lignes()], ["INFO", "INFO"])
        self.assertIn("courriel envoyé à equipe@example.org", self.lignes()[1]["message"])
        (message,) = SmtpEnregistre.envois
        self.assertEqual(message["To"], "equipe@example.org")
        self.assertIn("déposé", message["Subject"])
        self.assertIn("2026-S43", message.get_content())

    def test_le_sujet_d_une_erreur_le_dit(self):
        notification.notifier(self.dossier, "ERREUR", "rapport non produit : API injoignable", QUAND, COURRIEL, fabrique=SmtpEnregistre)
        self.assertIn("NON produit", SmtpEnregistre.envois[0]["Subject"])

    def test_le_courriel_ne_contient_aucune_donnee_du_rapport(self):
        notification.notifier(self.dossier, "INFO", "rapport déposé", QUAND, COURRIEL, fabrique=SmtpEnregistre)
        self.assertIn("aucune donnée", SmtpEnregistre.envois[0].get_content())
        self.assertEqual(SmtpEnregistre.envois[0].get_content_type(), "text/plain")  # pas de pièce jointe

    def test_un_courriel_impossible_ne_leve_rien_et_se_note_sans_secret(self):
        env = {**COURRIEL, "NOVARIA_RPA_SMTP_UTILISATEUR": "robot", "NOVARIA_RPA_SMTP_MOT_DE_PASSE": "secret-smtp-12"}
        notification.notifier(self.dossier, "INFO", "rapport déposé", QUAND, env, fabrique=SmtpEnPanne)
        niveaux = [ligne["niveau"] for ligne in self.lignes()]
        self.assertEqual(niveaux, ["INFO", "AVERTISSEMENT"])
        self.assertNotIn("secret-smtp-12", (self.dossier / "notifications.log").read_text(encoding="utf-8"))

    def test_un_reglage_invalide_se_note_sans_faire_echouer(self):
        notification.notifier(self.dossier, "INFO", "rapport déposé", QUAND, {"NOVARIA_RPA_SMTP": "pas-de-port"}, fabrique=SmtpEnregistre)
        self.assertEqual([ligne["niveau"] for ligne in self.lignes()], ["INFO", "AVERTISSEMENT"])
        self.assertEqual(SmtpEnregistre.envois, [])

    def test_le_message_n_est_pas_affecte_par_une_injection_dans_le_texte(self):
        notification.notifier(self.dossier, "ERREUR", "échec\nBcc: pirate@example.org", QUAND, COURRIEL, fabrique=SmtpEnregistre)
        self.assertIsNone(SmtpEnregistre.envois[0]["Bcc"])

    def test_les_sujets_connus(self):
        self.assertEqual(set(notification.SUJETS), {"INFO", "ERREUR"})
        self.assertTrue(issubclass(courriel.ErreurCourriel, Exception))


if __name__ == "__main__":
    unittest.main()
