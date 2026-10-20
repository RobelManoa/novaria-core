# Planification

Fichier ProjectLibre : `novaria-core-projectlibre.xml` (jalons, WBS (Work Breakdown Structure, structure de découpage du projet) par équipe, dépendances, ressources, notes par tâche). À importer dans ProjectLibre (Fichier, Ouvrir). Le fichier `novaria-core.pod` d'origine peut être remplacé par cette version après relecture.

| Fichier | Rôle |
|---|---|
| `model.py` | Durées, prédécesseurs, facteur d'assistance, rapport de charge avec capacité |
| `gen.py` | Génère `novaria-core-projectlibre.xml` à partir de `model.py` et du backlog (`scripts/github/`) |
| `novaria-core-projectlibre.xml` | Plan généré (dépendances sans limite de charge : voir `docs/07-gestion/charge-et-calendrier.md`) |

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Rapport de charge | `python3 planning/model.py` | `py -3 planning/model.py` |
| Autre facteur d'assistance | `FACTEUR_ASSISTANCE=0.6 python3 planning/model.py` | `$env:FACTEUR_ASSISTANCE="0.6"; py -3 planning/model.py` |
| Regénérer le plan | `python3 planning/gen.py` | `py -3 planning/gen.py` |
