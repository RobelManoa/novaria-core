"""`python -m mesures` : mesure la règle de seuils sur l'entraînement et la validation du jeu v1 (IA-01).

Le test n'est pas lisible. Code de sortie : 0 mesure faite, 1 jeu absent ou ensemble réservé.
"""

import argparse
import json
import sys
from pathlib import Path

from mesures import reference
from mesures.metriques import Mesures


def ligne(nom: str, m: Mesures) -> str:
    a = m.alertes
    delai = "-" if a.delai_median is None else f"{a.delai_median:g}/{a.delai_max}"
    return (f"{nom:<26} F1 macro {m.f1_macro:.3f}  rappel C {m.rappel_congested:.3f}  précision C {m.precision_congested:.3f}"
            f"  délai méd/max {delai:>5}  manqués {a.manques}/{a.episodes}  fausses {a.fausses}/{a.alertes}"
            f" ({a.fausses_par_troncon_et_jour:.2f} par tronçon et jour)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mesures", description=__doc__.splitlines()[0])
    parser.add_argument("--jeu", type=Path, default=reference.DOSSIER_JEU, help="dossier du jeu")
    parser.add_argument("--ensemble", action="append", help="train ou validation (défaut : les deux, mesurés séparément)")
    parser.add_argument("--sensibilite", action="store_true", help="ajoute les variations d'un réglage à la fois")
    parser.add_argument("--json", action="store_true", help="rapport JSON")
    arguments = parser.parse_args(argv)
    noms = arguments.ensemble or list(reference.ENSEMBLES_LISIBLES)
    rapport: dict = {}
    try:
        ensembles = {nom: reference.charger(nom, arguments.jeu) for nom in noms}
    except (reference.EnsembleReserve, FileNotFoundError) as erreur:
        print(f"Échec : {erreur}", file=sys.stderr)
        return 1
    if len(ensembles) > 1:
        ensembles["+".join(ensembles)] = reference.reunir(*ensembles.values())
    for nom, series in ensembles.items():
        mesures = {"regle": reference.mesurer_la_regle(series), "sans_hysteresis": reference.sans_hysteresis(series),
                   "toujours_FREE_FLOW": reference.etat_unique(series)}
        if arguments.sensibilite:
            mesures["variations"] = dict(reference.sensibilite(series))
        rapport[nom] = mesures
        if not arguments.json:
            print(f"== {nom} : {len(series)} séries (run, tronçon)")
            print(ligne("règle (ADR-028)", mesures["regle"]))
            print(ligne("sans durée minimale", mesures["sans_hysteresis"]))
            print(ligne("toujours FREE_FLOW", mesures["toujours_FREE_FLOW"]))
            for reglage, m in mesures.get("variations", {}).items():
                print(ligne(reglage, m))
    if arguments.json:
        def convertir(valeur):
            if isinstance(valeur, Mesures):
                return valeur.en_dict()
            if isinstance(valeur, dict):
                return {k: convertir(v) for k, v in valeur.items()}
            return valeur

        print(json.dumps(convertir(rapport), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
