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

## Cadrage et règle de référence (IA-01)

Le [cadrage ML](../docs/06-ia-mlops/cadrage-ml.md) fixe, avant tout entraînement, la cible, les quatre métriques, les seuils de l'ADR-028 et le seuil d'acceptation. `src/mesures/` en contient le code : `metriques.py` (F1 macro, rappel de `CONGESTED`, délai de détection, fausses alertes par tronçon et par jour ; fonctions pures) et `reference.py` (la règle du traitement en flux rejouée sur le jeu). **L'ensemble de test n'est pas lisible** par cet outil : IA-03 l'ouvre une seule fois, après le choix du candidat.

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Mesurer la règle sur l'entraînement et la validation (environ 11 s) | `python3 scripts/dev/dev.py reference-mesure` ou `make reference-mesure` | `py -3 scripts/dev/dev.py reference-mesure` |
| Avec les variations d'un réglage à la fois | `make reference-mesure SENS=1` | `py -3 scripts/dev/dev.py reference-mesure --sensibilite` |
