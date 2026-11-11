# Machine Learning et MLOps

`src/` code d'entraînement · `evaluation/` comparaisons et métriques · `registry/` suivi des modèles
(table `model_runs` dans MongoDB, modèles versionnés dans le dossier local `var/models/` ; S3 (Simple Storage Service) documenté, non exécuté) · `notebooks/` exploration uniquement.

Ordre de travail : congestion d'abord, prévision ensuite ([ADR-015](../docs/01-architecture/adr/ADR-015-modeles-ia.md)). Les états et leurs seuils sont définis dans l'[ADR-028](../docs/01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md) et le [dictionnaire de données](../docs/03-donnees/dictionnaire-de-donnees.md) ; le découpage entraînement/test se fait par run et par scénario.

## Jeu d'entraînement v1 (IA-08)

`src/jeu_entrainement/` construit le jeu `novaria-congestion-v1` : il rejoue des runs du simulateur (`simulator/`) dans le moteur de fenêtres du traitement en flux, ajoute la vérité terrain du scénario comme `label_state`, calcule les variables d'historique et les réponses de prévision du [dictionnaire de données](../docs/03-donnees/dictionnaire-de-donnees.md) (section 9), et écrit trois fichiers Parquet (`train`, `validation`, `test`) dans `data/datasets/novaria-congestion-v1/`, avec sa [fiche de provenance](../data/datasets/novaria-congestion-v1/PROVENANCE.md) et ses empreintes SHA-256. Bibliothèque standard seulement, y compris l'écriture Parquet.

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Construire le jeu (environ 40 s) | `python3 ml/src/construire_jeu.py` ou `make dataset-build` | `py -3 ml/src/construire_jeu.py` |
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
