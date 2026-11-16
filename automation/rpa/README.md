# RPA (Robotic Process Automation) avec Robot Framework

Robot de rapport hebdomadaire (IA-07, [ADR-019](../../docs/01-architecture/adr/ADR-019-rpa-automatisation.md)) : appelle l'API (avec reprises), génère le rapport PDF, le dépose et notifie (journal, courriel facultatif), **chaque semaine sans intervention**. La page « Rapports » du front-end (FE-06) l'affiche.

Documentation complète, preuves et limites : [Rapports automatiques](../../docs/03-donnees/rapports-automatiques.md).

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Installer Robot Framework (facultatif) | `pip install -r automation/rpa/requirements.txt` | `py -3 -m pip install -r automation\rpa\requirements.txt` |
| Produire le rapport (pile démarrée, compte dans `.env`) | `python3 scripts/dev/dev.py rpa-report` | `py -3 scripts/dev/dev.py rpa-report` |
| **Le planifier chaque semaine**, sans cron (rattrape un rapport manquant au démarrage) | `python3 scripts/dev/dev.py rpa-planifier` ou `make rpa-planifier` | `py -3 scripts/dev/dev.py rpa-planifier` |
| Le planifier avec le système : ligne `cron` | `automation/rpa/planification/novaria-rapport.cron` (`crontab -e`) | — |
| Le planifier avec le système : tâche Windows | — | `powershell -ExecutionPolicy Bypass -File automation\rpa\planification\installer-tache-windows.ps1` |
| Tests | `python3 -m unittest discover -s automation/rpa/tests -t automation/rpa` | `py -3 -m unittest discover -s automation\rpa\tests -t automation\rpa` |

| Fichier | Rôle |
|---|---|
| `rapport_hebdomadaire.robot` | la suite Robot Framework |
| `NovariaRapport.py` | bibliothèque : un mot-clé par étape |
| `rapport/` | le travail, en bibliothèque standard : `periode`, `api`, `synthese`, `contenu`, `pdf`, `depot`, `chaine` (reprises), `notification`, `courriel`, `planificateur` |
| `planification/` | la ligne `cron` et le script du Planificateur de tâches Windows |
| `preuves/` | transcription de l'essai de planification sans intervention |
| `tests/` | tests unitaires, dont `test_robot.py` qui lance la suite Robot Framework |

Sécurité : compte de service **en lecture seule** ; mot de passe dans l'environnement seulement ; aucun secret dans `output.xml`, `log.html`, les rapports, les notifications ou les courriels (testé). Le courriel est facultatif, chiffré hors de la machine, sans pièce jointe. Le robot ne commande aucun équipement.

**Pas encore fait :** l'étape d'interface (capture du tableau de bord) : le robot reste un automate d'API, plan de repli de l'ADR-019. **Non éprouvés en réel :** la ligne `cron`, la tâche Windows, un serveur de courrier réel.
