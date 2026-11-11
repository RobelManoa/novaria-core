# RPA (Robotic Process Automation) avec Robot Framework

Robot de rapport hebdomadaire (IA-07, [ADR-019](../../docs/01-architecture/adr/ADR-019-rpa-automatisation.md)) : appelle l'API, génère le rapport PDF, le dépose et notifie. La page « Rapports » du front-end (FE-06) l'affiche.

Documentation complète, preuves et limites : [Rapports automatiques](../../docs/03-donnees/rapports-automatiques.md).

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Installer Robot Framework (facultatif) | `pip install -r automation/rpa/requirements.txt` | `py -3 -m pip install -r automation\rpa\requirements.txt` |
| Produire le rapport (pile démarrée, compte dans `.env`) | `python3 scripts/dev/dev.py rpa-report` | `py -3 scripts/dev/dev.py rpa-report` |
| Tests | `python3 -m unittest discover -s automation/rpa/tests -t automation/rpa` | `py -3 -m unittest discover -s automation\rpa\tests -t automation\rpa` |

| Fichier | Rôle |
|---|---|
| `rapport_hebdomadaire.robot` | la suite Robot Framework |
| `NovariaRapport.py` | bibliothèque : un mot-clé par étape |
| `rapport/` | le travail, en bibliothèque standard : `periode`, `api`, `synthese`, `contenu`, `pdf`, `depot`, `chaine` |
| `tests/` | tests unitaires, dont `test_robot.py` qui lance la suite Robot Framework |

Sécurité : compte de service **en lecture seule** ; mot de passe dans l'environnement seulement ; aucun secret dans `output.xml`, `log.html`, les rapports ou les notifications (testé). Le robot ne commande aucun équipement.

**Pas encore fait :** planification hebdomadaire, étape d'interface (capture du tableau de bord), notification autre qu'un fichier de journal.
