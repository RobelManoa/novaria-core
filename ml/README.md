# Machine Learning et MLOps

`src/` code d'entraînement · `evaluation/` comparaisons et métriques · `registry/` suivi des modèles
(table `model_runs` dans MongoDB, modèles versionnés dans le dossier local `var/models/` derrière le port `ObjectStore` de `src/stockage/` ; S3 (Simple Storage Service) documenté, non exécuté ; [stockage d'objets](../docs/03-donnees/stockage-objets.md)) · `notebooks/` exploration uniquement.

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

## Pipeline MLSecOps (IA-05)

`src/pipeline/` entraîne la configuration figée par IA-03, l'évalue, applique le seuil et des contrôles de sécurité (jeu intact, artefact relu, format sans `pickle`, dépendances auditées, fiche relue, code commité, métriques reproduites), puis ferme une **porte** : un modèle sous le seuil n'est pas enregistré (code de sortie 1). Le flux de travail `.github/workflows/mlsecops.yml` le lance à la main, sans aucun paramètre. Documentation, équivalent SageMaker (non exécuté) et limites : [pipeline MLSecOps](../docs/06-ia-mlops/pipeline-mlsecops.md).

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Pipeline complet (code 1 si la porte est fermée) | `make ml-pipeline` | `py -3 scripts/dev/dev.py ml-pipeline` |
| Avec le registre MongoDB | `make ml-pipeline MONGO=1` | `py -3 scripts/dev/dev.py ml-pipeline --mongo` |

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

## Prévision de vitesse sur METR-LA (IA-10)

`src/prevision/` compare trois références (persistance, moyenne glissante d'une heure, naïf saisonnier) à deux modèles (Ridge, HistGradientBoosting) sur les vitesses réelles de METR-LA, aux horizons 5, 15 et 30 minutes, avec MAE, RMSE et un intervalle de confiance par jour, dans l'ordre du temps (70 / 15 / 15, délai de garde de 30 minutes). La chaîne est ensuite essayée, sans réapprentissage, sur trois runs simulés. Le jeu **n'est pas versionné** (licence non établie, jamais redistribué) : il se télécharge et son empreinte SHA-256 est contrôlée ([fiche de provenance](../data/datasets/metr-la/PROVENANCE.md)). Résultats, choix et **limite de validité** : [`evaluation/prevision-comparaison.md`](evaluation/prevision-comparaison.md) ; tableaux générés : [`evaluation/prevision-resultats.md`](evaluation/prevision-resultats.md). `h5py` ne sert qu'à lire le fichier HDF5 (`requirements.txt`).

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Télécharger METR-LA (57 Mo) et contrôler taille et SHA-256 (sans `ml-env`) | `python3 scripts/dev/dev.py ml-prevision telecharger` | `py -3 scripts/dev/dev.py ml-prevision telecharger` |
| Contrôler le fichier déjà là (sans réseau) | `python3 scripts/dev/dev.py ml-prevision verifier` | `py -3 scripts/dev/dev.py ml-prevision verifier` |
| Campagne complète (environ 3 minutes) : réécrit `prevision.json` et `prevision-resultats.md` | `python3 scripts/dev/dev.py ml-prevision evaluer` ou `make ml-prevision ETAPE=evaluer` | `py -3 scripts/dev/dev.py ml-prevision evaluer` |
| Tests (`test_prevision.py`, sans METR-LA ni réseau ; sans numpy et scikit-learn, les tests de la chaîne sont ignorés) | `ml/.venv/bin/python -m unittest discover -s ml/tests -t ml -p test_prevision.py` | `ml\.venv\Scripts\python.exe -m unittest discover -s ml\tests -t ml -p test_prevision.py` |

| Module | Rôle |
|---|---|
| `source.py` | adresse, taille et empreinte attendues ; téléchargement et contrôle (bibliothèque standard) |
| `donnees.py` | lecture du HDF5 ; conversion d'un run simulé en pas de 5 minutes (mph) |
| `variables.py`, `references.py` | variables sans fuite du futur ni identité du capteur ; les trois références |
| `modeles.py`, `evaluation.py`, `rapport.py` | Ridge et HistGradientBoosting ; MAE, RMSE, intervalle par jour ; exécution et écriture des résultats |

## Détection d'anomalies (IA-09)

`src/anomalies/` compare des **règles robustes** (écart à la médiane glissante, plateau, capteur muet, chute de débit, plus retard et doublon) à **Isolation Forest** sur les mêmes onze variables, avec les anomalies injectées par le simulateur : rappel, précision par épisode d'alerte et délai de détection, à budget de fausses alertes égal (une par heure de réseau). Le jeu `novaria-congestion-v1` n'est pas lu. Seul `isolation.py` importe scikit-learn (`ml/.venv`) ; le reste est en bibliothèque standard. Choix argumenté, limites et historique des réglages : [`evaluation/anomalies-comparaison.md`](evaluation/anomalies-comparaison.md) ; tableaux générés : [`evaluation/anomalies-resultats.md`](evaluation/anomalies-resultats.md).

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Campagne complète (environ 1 minute) : réécrit `anomalies.json` et `anomalies-resultats.md` | `python3 scripts/dev/dev.py ml-anomalies` ou `make ml-anomalies` | `py -3 scripts/dev/dev.py ml-anomalies` |
| Tests (`test_anomalies.py` ; sans scikit-learn, ceux d'Isolation Forest et du rapport sont ignorés) | `ml/.venv/bin/python -m unittest discover -s ml/tests -t ml -p test_anomalies.py` | `ml\.venv\Scripts\python.exe -m unittest discover -s ml\tests -t ml -p test_anomalies.py` |

| Module | Rôle |
|---|---|
| `campagne.py` | runs d'apprentissage, de validation et d'évaluation ; messages livrés ; anomalies injectées (vérité) ; plateau et chute ajoutés après coup |
| `variables.py` | onze variables par message (écart à la médiane, ratios, plateau, silence, retard, copies) |
| `regles.py`, `isolation.py` | les règles ; Isolation Forest sur les mêmes variables |
| `evaluation.py`, `rapport.py` | métriques ; exécution complète et écriture des résultats |

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
