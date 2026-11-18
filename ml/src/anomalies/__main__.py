"""`python -m anomalies` : campagne complète (apprentissage, seuil, évaluation) et écriture des résultats (IA-09).

Code de sortie : 0 résultats écrits, 1 scikit-learn absent. Compter environ une minute.
"""

import sys
import time

from anomalies import isolation, rapport


def main() -> int:
    debut = time.time()
    try:
        r = rapport.ecrire()
    except isolation.SklearnAbsent as erreur:
        print(f"Refusé : {erreur}", file=sys.stderr)
        return 1
    for nom, d in r["detecteurs"].items():
        rappels = ", ".join(f"{t} {v['rappel']:.0%}" for t, v in d["par_type"].items())
        print(f"{nom:<17} précision {d['precision']:.0%}  fausses/h {d['fausses_par_heure']:.2f}  rappel : {rappels}")
    print(f"Écrit : {rapport.JSON}\nÉcrit : {rapport.MARKDOWN}\n({time.time() - debut:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
