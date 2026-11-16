"""Modèles de planification : la ligne `cron` (Linux) et le script du Planificateur de tâches (Windows) lancent `dev.py rpa-report` chaque semaine."""

import re
import shutil
import subprocess
import unittest
from pathlib import Path

DOSSIER = Path(__file__).resolve().parents[1] / "planification"
CRON = DOSSIER / "novaria-rapport.cron"
POWERSHELL = DOSSIER / "installer-tache-windows.ps1"
BORNES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))  # minute, heure, jour du mois, mois, jour de la semaine


def ligne_cron() -> list[str]:
    lignes = [ligne for ligne in CRON.read_text(encoding="utf-8").splitlines() if ligne.strip() and not ligne.lstrip().startswith("#")]
    assert len(lignes) == 1, "une seule ligne de planification"
    return lignes[0].split(None, 5)


class Cron(unittest.TestCase):
    def test_cinq_champs_valides_chaque_lundi_a_sept_heures(self):
        champs = ligne_cron()
        self.assertEqual(champs[:5], ["0", "7", "*", "*", "1"])
        for valeur, (bas, haut) in zip(champs[:5], BORNES, strict=True):
            if valeur != "*":
                self.assertTrue(bas <= int(valeur) <= haut, valeur)

    def test_la_commande_est_celle_du_robot_avec_un_journal_sous_var(self):
        commande = ligne_cron()[5]
        self.assertIn("cd /CHEMIN/VERS/novaria-core", commande)
        self.assertIn("scripts/dev/dev.py rpa-report", commande)
        self.assertIn(">> var/log/rpa-rapport.log 2>&1", commande)
        self.assertIn("mkdir -p var/log", commande)

    def test_aucun_secret_n_est_ecrit_dans_la_ligne(self):
        texte = CRON.read_text(encoding="utf-8")
        self.assertNotRegex(texte, r"(?i)NOVARIA_RPA_PASSWORD\s*=|password=|--password|--mot-de-passe")
        self.assertNotRegex(texte, r"(?i)(mongodb|postgres(ql)?)://")

    def test_le_fichier_explique_installation_retrait_et_limite_de_fuseau(self):
        texte = CRON.read_text(encoding="utf-8")
        for morceau in ("Installation", "Retrait", "crontab -e", "UTC+7", "var/log/rpa-rapport.log"):
            self.assertIn(morceau, texte)


class PowerShell(unittest.TestCase):
    def setUp(self):
        self.octets = POWERSHELL.read_bytes()
        self.texte = self.octets.decode("utf-8-sig")

    def test_le_fichier_a_une_marque_d_ordre_des_octets_pour_les_accents(self):
        self.assertTrue(self.octets.startswith(b"\xef\xbb\xbf"), "Windows PowerShell 5.1 lit sinon l'UTF-8 comme de l'ANSI")

    def test_declencheur_hebdomadaire_et_reglages_de_reprise(self):
        for morceau in ("New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Jour -At $Heure", "-StartWhenAvailable", "-MultipleInstances IgnoreNew",
                        "Register-ScheduledTask", "Unregister-ScheduledTask", "'Novaria Rapport'"):
            self.assertIn(morceau, self.texte)

    def test_valeurs_par_defaut_lundi_sept_heures(self):
        self.assertIn("[string]$Heure = '07:00'", self.texte)
        self.assertIn("[string]$Jour = 'Monday'", self.texte)

    def test_la_validation_de_l_heure_accepte_et_refuse_les_bonnes_valeurs(self):
        motif = re.search(r"ValidatePattern\('([^']+)'\)", self.texte).group(1)
        for bon in ("00:00", "07:00", "23:59", "19:05"):
            self.assertRegex(bon, motif)
        for mauvais in ("24:00", "7:00", "07:60", "07h00", "07:00; calc", ""):
            self.assertNotRegex(mauvais, motif)

    def test_les_jours_sont_ceux_de_la_semaine(self):
        jours = re.search(r"ValidateSet\(([^)]+)\)", self.texte).group(1)
        self.assertEqual(re.findall(r"'(\w+)'", jours), ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])

    def test_la_commande_est_celle_du_robot_avec_un_journal_sous_var(self):
        self.assertIn(r"py -3 scripts\dev\dev.py rpa-report >> var\log\rpa-rapport.log 2>&1", self.texte)

    def test_aucun_mot_de_passe_ni_droit_eleve_n_est_demande(self):
        self.assertNotRegex(self.texte, r"(?i)-Password|-RunLevel\s+Highest|-LogonType\s+Password|NOVARIA_RPA_PASSWORD\s*=|\$env:NOVARIA_RPA_PASSWORD")
        self.assertIn("aucun mot de passe n'est stocké", self.texte)

    def test_la_syntaxe_powershell_est_valide_quand_pwsh_est_installe(self):
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh absent : syntaxe non vérifiée ici")
        sortie = subprocess.run([pwsh, "-NoProfile", "-Command", f"$null = [scriptblock]::Create((Get-Content -Raw '{POWERSHELL}')); 'ok'"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(sortie.stdout.strip(), "ok", sortie.stderr)


if __name__ == "__main__":
    unittest.main()
