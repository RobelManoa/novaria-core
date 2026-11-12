# Machine Learning et MLOps

`src/` code d'entraînement · `evaluation/` comparaisons et métriques · `registry/` suivi des modèles
(table `model_runs` dans MongoDB, modèles versionnés dans le dossier local `var/models/` ; S3 (Simple Storage Service) documenté, non exécuté) · `notebooks/` exploration uniquement.

Ordre de travail : congestion d'abord, prévision ensuite ([ADR-015](../docs/01-architecture/adr/ADR-015-modeles-ia.md)). Les états et leurs seuils sont définis dans l'[ADR-028](../docs/01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md) et le [dictionnaire de données](../docs/03-donnees/dictionnaire-de-donnees.md) ; le découpage entraînement/test se fait par run et par scénario.

## Jeu d'entraînement v1 (IA-08)

`src/jeu_entrainement/` construit le jeu `novaria-congestion-v1` : il rejoue des runs du simulateur (`simulator/`) dans le moteur de fenêtres du traitement en flux, ajoute la vérité terrain du scénario comme `label_state`, calcule les variables d'historique et les réponses de prévision du [dictionnaire de données](../docs/03-donnees/dictionnaire-de-donnees.md) (section 9), et écrit trois fichiers Parquet (`train`, `validation`, `test`) dans `data/datasets/novaria-congestion-v1/`, avec sa [fiche de provenance](../data/datasets/novaria-congestion-v1/PROVENANCE.md) et ses empreintes SHA-256. Bibliothèque standard seulement, y compris l'écriture Parquet.

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Construire le jeu (environ 40 s) | `python3 ml/src/construire_jeu.py` ou `make dataset-build` | `py -3 ml/src/construire_jeu.py` |
| Vérifier le jeu contre `manifest.json` avant d'entraîner (SHA-256, [cadrage](../docs/06-ia-mlops/cadrage-ml.md), S1) | `python3 ml/src/construire_jeu.py --verifier` | `py -3 ml/src/construire_jeu.py --verifier` |
| Tests (`ml/tests/`) | `python3 -m unittest discover -s ml/tests -t ml` ou `make test-ml` | `py -3 -m unittest discover -s ml\tests -t ml` |
| Tests avec reconstruction complète du jeu (empreinte de la fiche) | `NOVARIA_JEU_COMPLET=1 python3 -m unittest discover -s ml/tests -t ml` | `$env:NOVARIA_JEU_COMPLET = "1"; py -3 -m unittest discover -s ml\tests -t ml` |

| Module | Rôle |
|---|---|
| `catalogue.py` | les 12 runs, leur ensemble, et `verifier` (aucun recouvrement, tous les scénarios dans chaque ensemble) |
| `simulation.py` | exécute un run du simulateur en mémoire |
| `fenetres.py` | rejoue les messages dans `WindowEngine` : fenêtres d'une minute |
| `lignes.py` | variables, historique, réponses, label de la vérité terrain |
| `parquet.py` | écrivain et lecteur Parquet (sous-ensemble étroit, octets identiques à chaque écriture) |
| `construire.py`, `provenance.py` | fichiers, manifeste, empreintes, fiche |

## Registre des modèles (IA-04)

`src/registre/` enregistre chaque entraînement dans `model_runs` (MongoDB, compte `svc_ml`) et stocke les modèles dans `var/models/` derrière le port `ObjectStore` (S3 (Simple Storage Service) documenté, non exécuté). Un modèle en service se relie à son entraînement, à sa révision Git et à l'empreinte de son jeu ; un fichier de modèle altéré est refusé, et aucun `pickle` n'est jamais chargé (format JSON `novaria-modele-lineaire`). Documentation, contrôles de sécurité, limites et preuves : [`registry/README.md`](registry/README.md).

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Écrire le run d'IA-03 dans `model_runs` | `make ml-registre C=importer-ia03` | `py -3 scripts/dev/dev.py ml-registre importer-ia03` |
| Lignée d'un modèle, jeu recalculé | `make ml-registre C="lignee <run> --jeu"` | `py -3 scripts/dev/dev.py ml-registre lignee <run> --jeu` |
| Tests contre un MongoDB jetable (Docker) | `make ml-registre-essai` | `py -3 scripts/dev/dev.py ml-registre-essai` |

## Entraînement et comparaison (IA-03)

`src/entrainement/` compare la règle de seuils et deux candidats scikit-learn (régression logistique, HistGradientBoosting) en suivant le [cadrage ML](../docs/06-ia-mlops/cadrage-ml.md) : réglage sur la validation, validation croisée groupée par run (diagnostic), choix, puis **lecture unique du test**. scikit-learn vit dans `ml/.venv`, installé depuis `requirements.txt` avec ses empreintes (`--require-hashes`) ; le reste de `ml/` reste en bibliothèque standard. Résultats et choix argumenté : [`evaluation/comparaison.md`](evaluation/comparaison.md) (tableaux générés : [`evaluation/resultats.md`](evaluation/resultats.md)).

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Créer l'environnement | `python3 scripts/dev/dev.py ml-env` ou `make ml-env` | `py -3 scripts/dev/dev.py ml-env` |
| Réglage, validation croisée, choix (environ 1 minute) | `make ml-train ETAPE=validation` | `py -3 scripts/dev/dev.py ml-train validation` |
| Lecture unique du test (refusée si `evaluation/resultat-test.json` existe) | `make ml-train ETAPE=test` | `py -3 scripts/dev/dev.py ml-train test` |
| Tableaux `evaluation/resultats.md` | `make ml-train ETAPE=rapport` | `py -3 scripts/dev/dev.py ml-train rapport` |
| Tests avec scikit-learn (sans lui, ceux qui entraînent sont ignorés) | `ml/.venv/bin/python -m unittest discover -s ml/tests -t ml` | `ml\.venv\Scripts\python.exe -m unittest discover -s ml\tests -t ml` |

Aucun fichier de modèle n'est écrit : pas de `pickle`, rien à charger (cadrage, M3). L'enregistrement est l'affaire d'IA-05.

## Variables et découpage (IA-02)

`src/preparation/` transforme le jeu v1 en matrices, sans rien du futur : `variables.py` (quelles colonnes entrent dans la détection ou la prévision, lesquelles sont interdites et pourquoi), `calendrier.py` (heure, jour, week-end, sinus et cosinus calculés depuis l'instant), `historique.py` (décalages et moyennes mobiles du passé, recalculés à part), `ajustement.py` (médianes et catégories apprises sur l'entraînement seul ; un ajustement qui reçoit un autre run est refusé), `decoupage.py` (par run et par scénario, empreinte SHA-256, délai de garde pour la prévision dans l'ordre du temps), `controles.py` (recalcul sur les fichiers). **Le fichier de test n'est pas lu.**

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Vérifier découpage, variables et absence de fuite (environ 3 s) | `python3 scripts/dev/dev.py preparation-check` ou `make preparation-check` | `py -3 scripts/dev/dev.py preparation-check` |
| Rapport JSON | ajouter `--json` | ajouter `--json` |

## Cadrage et règle de référence (IA-01)

Le [cadrage ML](../docs/06-ia-mlops/cadrage-ml.md) fixe, avant tout entraînement, la cible, les quatre métriques, les seuils de l'ADR-028 et le seuil d'acceptation. `src/mesures/` en contient le code : `metriques.py` (F1 macro, rappel de `CONGESTED`, délai de détection, fausses alertes par tronçon et par jour ; fonctions pures) et `reference.py` (la règle du traitement en flux rejouée sur le jeu). **L'ensemble de test n'est pas lisible** par cet outil : IA-03 l'ouvre une seule fois, après le choix du candidat.

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Mesurer la règle sur l'entraînement et la validation (environ 11 s) | `python3 scripts/dev/dev.py reference-mesure` ou `make reference-mesure` | `py -3 scripts/dev/dev.py reference-mesure` |
| Avec les variations d'un réglage à la fois | `make reference-mesure SENS=1` | `py -3 scripts/dev/dev.py reference-mesure --sensibilite` |
