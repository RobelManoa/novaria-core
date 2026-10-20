"""Contrôle de la politique de vulnérabilités (issue CLD-23) : bibliothèque standard seulement.

Vérifie que chaque exception de .snyk a une raison, une expiration et une entrée au registre des risques,
et qu'un scan planifié hebdomadaire existe dans ci.yml.
Lancement : python3 -m unittest discover -s scripts/dev   (Windows : py -3 -m unittest discover -s scripts/dev)
"""
import re
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOUTENANCE = date(2026, 12, 10)
DUREE_MAX = timedelta(days=30)


def lire(chemin: str) -> str:
    return (ROOT / chemin).read_text(encoding="utf-8")


def exceptions_snyk() -> dict[str, dict[str, str]]:
    """Exceptions de .snyk : {identifiant: {"reason": ..., "expires": ...}} (les commentaires sont ignorés)."""
    resultat: dict[str, dict[str, str]] = {}
    courant = None
    for ligne in lire(".snyk").splitlines():
        if ligne.lstrip().startswith("#"):
            continue
        identifiant = re.match(r"^  (SNYK-[\w-]+):\s*$", ligne)
        if identifiant:
            courant = identifiant[1]
            resultat[courant] = {}
            continue
        champ = re.match(r"^\s+(reason|expires):\s*(.+?)\s*$", ligne)
        if champ and courant:
            resultat[courant][champ[1]] = champ[2]
    return resultat


def exceptions_documentees() -> dict[str, dict[str, str]]:
    """Lignes du tableau « Exceptions actives » de docs/04-devsecops/exceptions.md."""
    resultat = {}
    for ligne in lire("docs/04-devsecops/exceptions.md").splitlines():
        cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
        if ligne.startswith("|") and cellules[0].startswith("SNYK-") and len(cellules) == 7:
            resultat[cellules[0]] = {"creee": cellules[4], "expire": cellules[5], "registre": cellules[6]}
    return resultat


def jour(texte: str) -> date:
    return date.fromisoformat(texte[:10])


class ExceptionsSnyk(unittest.TestCase):
    def setUp(self):
        self.snyk = exceptions_snyk()
        self.docs = exceptions_documentees()
        self.registre = lire("docs/07-gestion/registre-risques.md")

    def test_chaque_exception_a_une_raison_et_une_expiration(self):
        for identifiant, champs in self.snyk.items():
            with self.subTest(exception=identifiant):
                self.assertTrue(champs.get("reason"), "raison absente")
                self.assertTrue(champs.get("expires"), "expiration absente")

    def test_chaque_expiration_est_avant_la_soutenance(self):
        for identifiant, champs in self.snyk.items():
            with self.subTest(exception=identifiant):
                self.assertLess(jour(champs["expires"]), SOUTENANCE)

    def test_chaque_exception_est_documentee_avec_la_meme_expiration_et_30_jours_au_plus(self):
        for identifiant, champs in self.snyk.items():
            with self.subTest(exception=identifiant):
                self.assertIn(identifiant, self.docs, "absente du tableau de exceptions.md")
                ligne = self.docs[identifiant]
                self.assertEqual(jour(ligne["expire"]), jour(champs["expires"]))
                self.assertLessEqual(jour(ligne["expire"]) - jour(ligne["creee"]), DUREE_MAX)

    def test_chaque_exception_a_une_entree_au_registre_des_risques(self):
        for identifiant in self.snyk:
            with self.subTest(exception=identifiant):
                self.assertIn(identifiant, self.registre)
                self.assertEqual(self.docs[identifiant]["registre"], "R10")

    def test_aucune_exception_documentee_n_est_absente_de_snyk(self):
        self.assertEqual(sorted(set(self.docs) - set(self.snyk)), [])

    def test_le_registre_a_une_ligne_pour_les_failles_sans_correctif(self):
        self.assertRegex(self.registre, r"(?m)^\| R10 \| Failles de sécurité sans correctif")


class ScanPlanifie(unittest.TestCase):
    def setUp(self):
        self.ci = lire(".github/workflows/ci.yml")

    def test_un_declencheur_schedule_hebdomadaire_existe(self):
        self.assertRegex(self.ci, r"(?m)^  schedule:\s*$")
        cron = re.search(r'(?m)^\s+- cron: "([^"]+)"', self.ci)
        self.assertIsNotNone(cron, "aucune expression cron")
        minute, heure, jour_du_mois, mois, jour_de_semaine = cron[1].split()
        self.assertEqual((jour_du_mois, mois), ("*", "*"))
        self.assertRegex(jour_de_semaine, r"^[0-6]$", "le scan doit tourner un seul jour par semaine")
        self.assertRegex(minute + heure, r"^\d+$")

    def test_les_jobs_snyk_et_docker_tournent_pendant_le_scan_planifie(self):
        for job in ("snyk", "docker"):
            with self.subTest(job=job):
                bloc = re.search(rf"(?ms)^  {job}:\n(.*?)(?=^  \w[\w-]*:\n|\Z)", self.ci)
                self.assertIsNotNone(bloc)
                self.assertNotIn("github.event_name != 'schedule'", bloc[1])

    def test_le_scan_planifie_a_son_propre_groupe_de_concurrence(self):
        self.assertIn("github.event_name == 'schedule'", self.ci)


if __name__ == "__main__":
    unittest.main()
