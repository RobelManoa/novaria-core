"""`python -m registre <commande>` : lire et alimenter le registre des modèles (IA-04).

| commande | effet |
|---|---|
| `importer-ia03` | écrit dans `model_runs` le run d'IA-03 (`ml/evaluation/`), rejeté : trace sans fichier de modèle |
| `lister` | les runs, du plus ancien au plus récent |
| `en-service` | le modèle en service et sa lignée (côté entraînement : MongoDB) |
| `lignee RUN [--jeu]` | la chaîne d'un modèle enregistré : entraînement, code Git, jeu, modèle ; `--jeu` recalcule l'empreinte du jeu |
| `charger` | côté service : charge le modèle du pointeur depuis le magasin, sans MongoDB (aucun droit sur `model_runs`) |

L'adresse MongoDB (compte `svc_ml`) vient de la variable `MONGO_URL` et n'est jamais affichée ; le magasin est `var/models/`
(`STORAGE_BACKEND=local`, seul adaptateur : S3 est documenté, non exécuté).
Code de sortie : 0 conforme, 1 écart ou refus, 2 configuration absente.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from jeu_entrainement.simulation import RACINE
from registre import documents, importer_ia03, lignee, service
from registre.registre import Registre
from registre.runs import MongoRunStore
from stockage import ObjectStore, StockageNonConfigure, ouvrir_magasin

RACINE_DU_MAGASIN = RACINE / "var" / "models"


class Configuration(RuntimeError):
    pass


def magasin() -> ObjectStore:
    try:
        return ouvrir_magasin(RACINE_DU_MAGASIN)
    except StockageNonConfigure as erreur:
        raise Configuration(str(erreur)) from erreur


def registre() -> Registre:
    adresse = os.environ.get("MONGO_URL")
    if not adresse:
        raise Configuration("MONGO_URL est absente (via `dev.py ml-registre`, qui la lit dans .env)")
    return Registre(MongoRunStore.depuis_l_adresse(adresse), magasin())


def _afficher(valeur) -> None:
    print(json.dumps(valeur, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m registre", description=__doc__.splitlines()[0])
    sous = parser.add_subparsers(dest="commande", required=True)
    for nom in ("importer-ia03", "lister", "en-service", "charger"):
        sous.add_parser(nom)
    commande_lignee = sous.add_parser("lignee")
    commande_lignee.add_argument("run")
    commande_lignee.add_argument("--jeu", action="store_true", help="recalcule l'empreinte du jeu de données du disque")
    arguments = parser.parse_args(argv)
    try:
        if arguments.commande == "charger":
            modele = service.charger_le_modele_en_service(magasin())
            _afficher({"run_id": modele.run_id, "lignee": modele.manifeste})
            return 0
        r = registre()
        if arguments.commande == "importer-ia03":
            run_id, document, cree = importer_ia03.importer(r)
            print(f"{'Écrit' if cree else 'Déjà présent'} : {run_id} ({document['status']})")
            return 0
        if arguments.commande == "lister":
            _afficher([{k: v for k, v in documents.en_json(d).items() if k in ("run_id", "status", "created_at", "git_sha", "dataset_sha256", "model_sha256")} for d in r.runs.lister()])
            return 0
        if arguments.commande == "en-service":
            run = r.en_service()
            if run is None:
                print("Aucun modèle enregistré : la règle de seuils reste le classificateur en service (ADR-015).")
                return 0
            _afficher(lignee.verifier_la_chaine(run, r.objets).en_dict())
            return 0
        run = r.runs.obtenir(documents.valider_run_id(arguments.run))
        if run is None:
            print(f"Échec : aucun run « {arguments.run} »", file=sys.stderr)
            return 1
        resultat = lignee.verifier_la_chaine(run, r.objets, jeu=Path(importer_jeu()) if arguments.jeu else None)
        _afficher(resultat.en_dict())
        return 0 if resultat.intacte else 1
    except Configuration as erreur:
        print(f"Configuration : {erreur}", file=sys.stderr)
        return 2
    except (service.ModeleRefuse, documents.DocumentInvalide) as erreur:
        print(f"Refusé : {erreur}", file=sys.stderr)
        return 1


def importer_jeu() -> Path:
    from preparation.donnees import DOSSIER_JEU

    return DOSSIER_JEU


if __name__ == "__main__":
    sys.exit(main())
