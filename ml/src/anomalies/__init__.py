"""Détection d'anomalies de capteur et de circulation (IA-09).

Règles robustes d'abord, Isolation Forest en comparaison, sur les **mêmes variables** (ADR-015, cas d'usage 2).
Les règles, les variables et l'évaluation n'utilisent que la bibliothèque standard ; scikit-learn n'est importé que par
`isolation.py` (environnement `ml/.venv`, `python3 scripts/dev/dev.py ml-env`).

- `campagne.py`  : runs du simulateur, messages tels que livrés, anomalies injectées (la vérité de l'évaluation) ;
- `variables.py` : les variables calculées message par message (écart à la médiane glissante, plateau, silence, retard…) ;
- `regles.py`    : les règles, des seuils sur ces variables ;
- `isolation.py` : Isolation Forest sur les mêmes variables ;
- `evaluation.py`: rappel, précision et délai de détection par type d'anomalie ;
- `rapport.py`   : `ml/evaluation/anomalies.json` et `ml/evaluation/anomalies-resultats.md`.
"""

SEED = 42  # cadrage ML, section 7
