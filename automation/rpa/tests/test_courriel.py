"""Notification par courriel : réglages stricts, chiffrement exigé hors de la machine, aucun secret dans les messages d'erreur."""

import smtplib
import socketserver
import threading
import unittest
from email import message_from_bytes
from unittest import mock

from rapport import courriel

BASE = {"NOVARIA_RPA_SMTP": "127.0.0.1:1025", "NOVARIA_RPA_DESTINATAIRE": "equipe@example.org"}


class Reglages(unittest.TestCase):
    def test_sans_serveur_le_courriel_est_desactive(self):
        self.assertIsNone(courriel.reglages({}))
        self.assertIsNone(courriel.reglages({"NOVARIA_RPA_SMTP": "  "}))

    def test_reglages_valides(self):
        r = courriel.reglages(BASE)
        self.assertEqual((r.hote, r.port, r.destinataire, r.expediteur, r.utilisateur), ("127.0.0.1", 1025, "equipe@example.org", "novaria-rpa@localhost", None))
        self.assertFalse(r.chiffre)

    def test_un_serveur_distant_est_chiffre(self):
        self.assertTrue(courriel.reglages({**BASE, "NOVARIA_RPA_SMTP": "smtp.example.org:587"}).chiffre)
        self.assertFalse(courriel.reglages({**BASE, "NOVARIA_RPA_SMTP": "localhost:25"}).chiffre)

    def test_les_reglages_invalides_sont_refuses(self):
        for nom, valeur in (("NOVARIA_RPA_SMTP", "pas-de-port"), ("NOVARIA_RPA_SMTP", "hote:0"), ("NOVARIA_RPA_SMTP", "hote:70000"),
                            ("NOVARIA_RPA_SMTP", "ho ste:25"), ("NOVARIA_RPA_SMTP", "hote:vingt"),
                            ("NOVARIA_RPA_DESTINATAIRE", ""), ("NOVARIA_RPA_DESTINATAIRE", "a@b.c, d@e.f"),
                            ("NOVARIA_RPA_DESTINATAIRE", "a@b.c\nBcc: x@y.z"), ("NOVARIA_RPA_DESTINATAIRE", "pas-une-adresse"),
                            ("NOVARIA_RPA_EXPEDITEUR", "x y@z.org")):
            with self.subTest(nom=nom, valeur=valeur), self.assertRaises(courriel.CourrielNonConfigure):
                courriel.reglages({**BASE, nom: valeur})

    def test_un_compte_demande_utilisateur_et_mot_de_passe_ensemble(self):
        for env in ({"NOVARIA_RPA_SMTP_UTILISATEUR": "robot"}, {"NOVARIA_RPA_SMTP_MOT_DE_PASSE": "x"}):
            with self.subTest(env=env), self.assertRaises(courriel.CourrielNonConfigure):
                courriel.reglages({**BASE, **env})
        r = courriel.reglages({**BASE, "NOVARIA_RPA_SMTP_UTILISATEUR": "robot", "NOVARIA_RPA_SMTP_MOT_DE_PASSE": "secret-smtp-12"})
        self.assertEqual((r.utilisateur, r.mot_de_passe), ("robot", "secret-smtp-12"))

    def test_le_mot_de_passe_n_apparait_pas_dans_la_representation_du_reglage_des_erreurs(self):
        env = {**BASE, "NOVARIA_RPA_SMTP": "pas-de-port", "NOVARIA_RPA_SMTP_UTILISATEUR": "robot", "NOVARIA_RPA_SMTP_MOT_DE_PASSE": "secret-smtp-12"}
        with self.assertRaises(courriel.CourrielNonConfigure) as e:
            courriel.reglages(env)
        self.assertNotIn("secret-smtp-12", str(e.exception))


class Composition(unittest.TestCase):
    def test_le_sujet_tient_sur_une_ligne_et_les_en_tetes_sont_ceux_demandes(self):
        r = courriel.reglages(BASE)
        m = courriel.composer(r, "[Novaria] rapport\nBcc: pirate@example.org", "corps")
        self.assertNotIn("\n", m["Subject"])
        self.assertIsNone(m["Bcc"])
        self.assertEqual((m["To"], m["From"]), ("equipe@example.org", "novaria-rpa@localhost"))

    def test_un_sujet_trop_long_est_coupe(self):
        self.assertEqual(len(courriel.composer(courriel.reglages(BASE), "x" * 500, "c")["Subject"]), 200)


class FausseSmtp:
    """Un client SMTP factice qui note les appels."""

    appels: list

    def __init__(self, hote, port, timeout=None):
        FausseSmtp.appels = [("connexion", hote, port, timeout)]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def ehlo(self):
        self.appels.append(("ehlo",))

    def starttls(self, context=None):
        self.appels.append(("starttls", context is not None))

    def login(self, utilisateur, mot_de_passe):
        self.appels.append(("login", utilisateur, mot_de_passe))

    def send_message(self, message):
        self.appels.append(("envoi", message["To"]))


class Envoi(unittest.TestCase):
    def test_serveur_local_sans_compte_pas_de_chiffrement_ni_connexion(self):
        courriel.envoyer(courriel.reglages(BASE), "s", "c", fabrique=FausseSmtp)
        self.assertEqual([a[0] for a in FausseSmtp.appels], ["connexion", "ehlo", "envoi"])

    def test_serveur_distant_starttls_avant_le_compte_puis_envoi(self):
        env = {**BASE, "NOVARIA_RPA_SMTP": "smtp.example.org:587", "NOVARIA_RPA_SMTP_UTILISATEUR": "robot", "NOVARIA_RPA_SMTP_MOT_DE_PASSE": "secret-smtp-12"}
        courriel.envoyer(courriel.reglages(env), "s", "c", fabrique=FausseSmtp)
        self.assertEqual([a[0] for a in FausseSmtp.appels], ["connexion", "ehlo", "starttls", "ehlo", "login", "envoi"])
        self.assertEqual(FausseSmtp.appels[2], ("starttls", True))

    def test_serveur_distant_sans_compte_est_aussi_chiffre(self):
        courriel.envoyer(courriel.reglages({**BASE, "NOVARIA_RPA_SMTP": "smtp.example.org:587"}), "s", "c", fabrique=FausseSmtp)
        self.assertIn(("starttls", True), FausseSmtp.appels)

    def test_un_compte_n_est_jamais_presente_sur_un_canal_en_clair(self):
        env = {**BASE, "NOVARIA_RPA_SMTP_UTILISATEUR": "robot", "NOVARIA_RPA_SMTP_MOT_DE_PASSE": "secret-smtp-12"}
        fabrique = mock.Mock()
        with self.assertRaises(courriel.ErreurCourriel) as e:
            courriel.envoyer(courriel.reglages(env), "s", "c", fabrique=fabrique)
        fabrique.assert_not_called()
        self.assertNotIn("secret-smtp-12", str(e.exception))

    def test_un_echec_reseau_ou_smtp_ne_montre_ni_secret_ni_contenu(self):
        env = {**BASE, "NOVARIA_RPA_SMTP": "smtp.example.org:587", "NOVARIA_RPA_SMTP_UTILISATEUR": "robot", "NOVARIA_RPA_SMTP_MOT_DE_PASSE": "secret-smtp-12"}
        for erreur in (smtplib.SMTPAuthenticationError(535, b"secret-smtp-12 refuse"), ConnectionRefusedError("secret-smtp-12"), TimeoutError("x")):
            class Casse(FausseSmtp):
                def login(self, *_):
                    raise erreur

            with self.subTest(erreur=type(erreur).__name__), self.assertRaises(courriel.ErreurCourriel) as e:
                courriel.envoyer(courriel.reglages(env), "s", "corps-confidentiel", fabrique=Casse)
            self.assertNotIn("secret-smtp-12", str(e.exception))
            self.assertNotIn("corps-confidentiel", str(e.exception))

    def test_connexion_refusee(self):
        class Refuse:
            def __init__(self, *_a, **_k):
                raise ConnectionRefusedError("refusé")

        with self.assertRaises(courriel.ErreurCourriel):
            courriel.envoyer(courriel.reglages(BASE), "s", "c", fabrique=Refuse)


class ServeurSmtpDEssai(socketserver.StreamRequestHandler):
    """Un serveur SMTP minimal (EHLO, MAIL, RCPT, DATA, QUIT) qui garde le message reçu."""

    recus: list = []

    def reponse(self, texte):
        self.wfile.write(texte.encode() + b"\r\n")

    def handle(self):
        self.reponse("220 serveur d'essai")
        donnees = False
        morceaux = []
        for ligne in self.rfile:
            ligne = ligne.decode("utf-8", "replace").rstrip("\r\n")
            if donnees:
                if ligne == ".":
                    donnees = False
                    ServeurSmtpDEssai.recus.append("\n".join(morceaux))
                    self.reponse("250 reçu")
                else:
                    morceaux.append(ligne)
                continue
            commande = ligne.upper()
            if commande.startswith("EHLO") or commande.startswith("HELO"):
                self.reponse("250 essai")
            elif commande.startswith(("MAIL", "RCPT")):
                self.reponse("250 ok")
            elif commande == "DATA":
                donnees = True
                morceaux = []
                self.reponse("354 envoyer")
            elif commande == "QUIT":
                self.reponse("221 au revoir")
                return
            else:
                self.reponse("250 ok")


class VraiServeurLocal(unittest.TestCase):
    def test_un_courriel_arrive_a_un_vrai_serveur_smtp_local(self):
        ServeurSmtpDEssai.recus = []
        with socketserver.ThreadingTCPServer(("127.0.0.1", 0), ServeurSmtpDEssai) as serveur:
            threading.Thread(target=serveur.serve_forever, daemon=True).start()
            r = courriel.reglages({**BASE, "NOVARIA_RPA_SMTP": f"127.0.0.1:{serveur.server_address[1]}"})
            courriel.envoyer(r, "[Novaria] rapport déposé", "INFO : rapport 2026-S43 déposé")
            serveur.shutdown()
        self.assertEqual(len(ServeurSmtpDEssai.recus), 1)
        message = message_from_bytes(ServeurSmtpDEssai.recus[0].encode("utf-8"))
        self.assertEqual(message["To"], "equipe@example.org")
        self.assertIn("rapport", message["Subject"])
        self.assertIn("2026-S43", message.get_payload(decode=True).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
