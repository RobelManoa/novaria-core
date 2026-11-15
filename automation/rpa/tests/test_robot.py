"""La suite Robot Framework contre une fausse API HTTP locale : un vrai passage par `robot`."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tests.donnees import RACINE, jeu

SUITE = RACINE / "rapport_hebdomadaire.robot"
LIGNES = jeu(3, 12)


class Api(BaseHTTPRequestHandler):
    indisponibilites = 0  # nombre de réponses 503 avant de servir (l'API qui redémarre)

    def log_message(self, *args):
        pass

    def _envoyer(self, statut, corps):
        octets = json.dumps(corps).encode()
        self.send_response(statut)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(octets)))
        self.end_headers()
        self.wfile.write(octets)

    def do_POST(self):
        taille = int(self.headers.get("Content-Length", 0))
        saisie = json.loads(self.rfile.read(taille))
        if saisie.get("password") == "secret-de-test-12":
            self._envoyer(200, {"access_token": "jeton-opaque", "token_type": "bearer"})
        else:
            self._envoyer(401, {"code": "INVALID_CREDENTIALS"})

    def do_GET(self):
        if type(self).indisponibilites > 0:
            type(self).indisponibilites -= 1
            return self._envoyer(503, {"code": "UPSTREAM_UNAVAILABLE"})
        if self.headers.get("Authorization") != "Bearer jeton-opaque":
            return self._envoyer(401, {"code": "UNAUTHENTICATED"})
        self._envoyer(200, {"items": LIGNES, "next_cursor": None})


def robot_disponible() -> bool:
    return subprocess.run([sys.executable, "-m", "robot", "--version"], capture_output=True).returncode in (0, 251)


@unittest.skipUnless(robot_disponible(), "Robot Framework n'est pas installé (pip install -r automation/rpa/requirements.txt)")
class SuiteRobot(unittest.TestCase):
    def setUp(self):
        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Api)
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()
        self.addCleanup(self.serveur.shutdown)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.sortie = Path(self._tmp.name)

    def lancer(self, mot_de_passe="secret-de-test-12", **supplement):
        environnement = {**os.environ, "NOVARIA_RPA_USER": "robot", "NOVARIA_RPA_PASSWORD": mot_de_passe, "NOVARIA_RPA_ATTENTE_S": "0", **supplement}
        return subprocess.run(
            [sys.executable, "-m", "robot", "--outputdir", str(self.sortie / "robot"),
             "--variable", f"API:http://127.0.0.1:{self.serveur.server_port}",
             "--variable", f"DOSSIER:{self.sortie / 'rapports'}",
             "--variable", "DEBUT:2026-10-19", str(SUITE)],
            capture_output=True, text=True, env=environnement, cwd=RACINE,
        )

    def test_la_suite_produit_et_depose_le_rapport(self):
        resultat = self.lancer()
        self.assertEqual(resultat.returncode, 0, resultat.stdout + resultat.stderr)
        self.assertEqual(len(list((self.sortie / "rapports").glob("*.pdf"))), 1)
        meta = json.loads(next((self.sortie / "rapports").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(meta["file_name"], "rapport-hebdomadaire-2026-S43.pdf")

    def test_les_journaux_du_robot_ne_contiennent_aucun_secret(self):
        self.lancer()
        for fichier in (self.sortie / "robot").glob("*"):
            contenu = fichier.read_bytes()
            self.assertNotIn(b"secret-de-test-12", contenu, fichier.name)
            self.assertNotIn(b"jeton-opaque", contenu, fichier.name)

    def test_un_echec_de_connexion_fait_echouer_la_suite_et_notifie_l_erreur(self):
        resultat = self.lancer(mot_de_passe="mauvais")
        self.assertNotEqual(resultat.returncode, 0)
        lignes = (self.sortie / "rapports" / "notifications.log").read_text(encoding="utf-8").splitlines()
        derniere = json.loads(lignes[-1])
        self.assertEqual(derniere["niveau"], "ERREUR")
        self.assertNotIn("mauvais", json.dumps(derniere))
        self.assertEqual(list((self.sortie / "rapports").glob("*.pdf")), [])

    def test_une_api_qui_redemarre_n_empeche_pas_le_rapport(self):
        """ADR-019 : nouvelle tentative limitée. Deux 503 de suite, puis l'API répond : le rapport est déposé, sans intervention."""
        Api.indisponibilites = 2
        self.addCleanup(setattr, Api, "indisponibilites", 0)
        resultat = self.lancer()
        self.assertEqual(resultat.returncode, 0, resultat.stdout + resultat.stderr)
        self.assertEqual(len(list((self.sortie / "rapports").glob("*.pdf"))), 1)
        log = (self.sortie / "robot" / "log.html").read_text(encoding="utf-8")
        self.assertIn("nouvelle tentative", log)

    def test_une_api_qui_ne_revient_pas_echoue_apres_les_tentatives_et_notifie(self):
        Api.indisponibilites = 99
        self.addCleanup(setattr, Api, "indisponibilites", 0)
        resultat = self.lancer(NOVARIA_RPA_TENTATIVES="2")
        self.assertNotEqual(resultat.returncode, 0)
        self.assertEqual(Api.indisponibilites, 97, "deux tentatives, pas plus")
        derniere = json.loads((self.sortie / "rapports" / "notifications.log").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(derniere["niveau"], "ERREUR")

    def test_le_mot_de_passe_du_courriel_n_entre_dans_aucun_journal_du_robot(self):
        """Compte SMTP sur un serveur non chiffré : refusé, noté en avertissement, et le secret ne fuit nulle part."""
        resultat = self.lancer(NOVARIA_RPA_SMTP="127.0.0.1:9", NOVARIA_RPA_DESTINATAIRE="equipe@example.org",
                               NOVARIA_RPA_SMTP_UTILISATEUR="robot-courrier", NOVARIA_RPA_SMTP_MOT_DE_PASSE="secret-smtp-12")
        self.assertEqual(resultat.returncode, 0, "un courriel impossible ne fait pas échouer le rapport")
        niveaux = [json.loads(ligne)["niveau"] for ligne in (self.sortie / "rapports" / "notifications.log").read_text(encoding="utf-8").splitlines()]
        self.assertIn("AVERTISSEMENT", niveaux)
        for fichier in [*(self.sortie / "robot").glob("*"), self.sortie / "rapports" / "notifications.log", *(self.sortie / "rapports").glob("*.json")]:
            self.assertNotIn(b"secret-smtp-12", fichier.read_bytes(), fichier.name)
        self.assertNotIn("secret-smtp-12", resultat.stdout + resultat.stderr)


if __name__ == "__main__":
    unittest.main()
