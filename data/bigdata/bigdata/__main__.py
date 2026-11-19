"""`python -m bigdata` : générer le jeu, lancer un moteur, vérifier ses résultats, mesurer.

    generer   --dossier D --jours N [--capteurs C] [--debut AAAA-MM-JJ] [--processus P]
    nettoyer  --moteur python-sequentiel|python-parallele|spark --dossier D --jours N [--coeurs C] [--sortie S]
    verifier  --moteur ... --dossier D --jours N [--coeurs C] [--sortie S]
    mesurer   --dossier D --jours 1,7,30 --moteurs python-sequentiel,python-parallele:4,spark:4 [--repetitions R]
    rapport   --entree mesure.json     (tableaux Markdown d'un rapport de mesure)

Chaque sous-commande rend un document JSON sur la dernière ligne de sortie. À lancer dans l'image `novaria-bigdata`
(`python3 scripts/dev/dev.py bigdata ...`), où Java et PySpark sont installés.
"""

import argparse
import json
import multiprocessing
import sys
import time
from datetime import date
from pathlib import Path

from bigdata import empreinte, generer, jeu

MOTEURS = ("python-sequentiel", "python-parallele", "spark")


def commande_generer(arguments: argparse.Namespace) -> dict:
    debut = date.fromisoformat(arguments.debut)
    jours = [date.fromordinal(debut.toordinal() + i) for i in range(arguments.jours)]
    travaux = [(str(arguments.dossier), jour, arguments.capteurs, arguments.graine) for jour in jours]
    depart = time.perf_counter()
    with multiprocessing.get_context("spawn").Pool(arguments.processus) as groupe:
        resultats = groupe.map(generer._travail, travaux)
    jeu.enregistrer_attendu(arguments.dossier, {nom: attendu for _, nom, _, attendu in resultats})
    octets = sum(r[2] for r in resultats)
    lignes = sum(r[3]["rows_read"] for r in resultats)
    return {"fichiers": len(resultats), "lignes": lignes, "octets": octets, "secondes": round(time.perf_counter() - depart, 2)}


def _maintenant():
    return generer.MAINTENANT


def commande_nettoyer(arguments: argparse.Namespace) -> dict:
    fichiers = jeu.fichiers_du_jeu(arguments.dossier, arguments.jours)
    debut = time.perf_counter()
    demarrage = 0.0
    if arguments.moteur == "python-sequentiel":
        from bigdata import nettoyage_python

        bilan = nettoyage_python.sequentiel(fichiers, _maintenant())
    elif arguments.moteur == "python-parallele":
        from bigdata import nettoyage_python

        bilan = nettoyage_python.parallele(fichiers, _maintenant(), arguments.coeurs)
    else:
        from bigdata import nettoyage_spark

        session = nettoyage_spark.ouvrir_session(arguments.coeurs, arguments.memoire_spark, arguments.temporaire)
        demarrage = time.perf_counter() - debut
        try:
            bilan = nettoyage_spark.nettoyer(session, [str(f) for f in fichiers], sortie_spark(arguments), _maintenant())
        finally:
            session.stop()
    secondes = time.perf_counter() - debut
    return {
        "moteur": arguments.moteur, "coeurs": arguments.coeurs if arguments.moteur != "python-sequentiel" else 1,
        "jours": arguments.jours, "fichiers": len(fichiers), "secondes": round(secondes, 3),
        "secondes_demarrage": round(demarrage, 3), "bilan": {k: v for k, v in bilan.items() if k != "reject_rate"},
    }


def sortie_spark(arguments: argparse.Namespace) -> Path:
    return Path(arguments.sortie) / f"spark-{arguments.jours}j-{arguments.coeurs}c"


def commande_verifier(arguments: argparse.Namespace) -> dict:
    fichiers = jeu.fichiers_du_jeu(arguments.dossier, arguments.jours)
    noms = [f.name for f in fichiers]
    if arguments.moteur == "spark":
        from bigdata import nettoyage_spark

        session = nettoyage_spark.ouvrir_session(arguments.coeurs, arguments.memoire_spark, arguments.temporaire)
        try:
            resultat = empreinte.depuis_la_sortie_spark(session, sortie_spark(arguments), noms)
        finally:
            session.stop()
    else:
        resultat = empreinte.depuis_les_sorties_python(Path(arguments.dossier), noms)
    resultat["attendu"] = jeu.attendu_des(arguments.dossier, fichiers)
    return resultat


def commande_mesurer(arguments: argparse.Namespace) -> dict:
    from bigdata import mesure

    return mesure.mesurer(arguments)


def commande_rapport(arguments: argparse.Namespace) -> dict:
    from bigdata import rapport

    print(rapport.rendre(arguments.entree))
    return {"entree": str(arguments.entree)}


def construire_parseur() -> argparse.ArgumentParser:
    parseur = argparse.ArgumentParser(prog="python -m bigdata", description=__doc__.splitlines()[0])
    sous = parseur.add_subparsers(dest="commande", required=True)
    rapport = sous.add_parser("rapport")
    rapport.add_argument("--entree", type=Path, required=True, help="rapport JSON : la sortie de « mesurer » redirigée vers un fichier")
    for nom in ("generer", "nettoyer", "verifier", "mesurer"):
        s = sous.add_parser(nom)
        s.add_argument("--dossier", type=Path, default=Path("/data/paris"), help="fichiers bruts (et leur vérité terrain)")
        if nom == "generer":
            s.add_argument("--jours", type=int, required=True)
            s.add_argument("--debut", default=generer.DEBUT_PAR_DEFAUT.isoformat())
            s.add_argument("--capteurs", type=int, default=generer.CAPTEURS_PAR_DEFAUT)
            s.add_argument("--graine", type=int, default=generer.GRAINE_PAR_DEFAUT)
            s.add_argument("--processus", type=int, default=4)
            continue
        if nom == "mesurer":
            s.add_argument("--jours", default="1,7,30", help="tailles à mesurer : nombre de jours, séparés par des virgules")
            s.add_argument("--moteurs", default="python-sequentiel,python-parallele:4,spark:1,spark:4")
            s.add_argument("--repetitions", type=int, default=1)
        else:
            s.add_argument("--moteur", choices=MOTEURS, required=True)
            s.add_argument("--jours", type=int, required=True)
            s.add_argument("--coeurs", type=int, default=4)
        s.add_argument("--sortie", type=Path, default=Path("/data/sortie"))
        s.add_argument("--memoire-spark", default="3g")
        s.add_argument("--temporaire", default="/data/spark-tmp")
    return parseur


def main(argv: list[str] | None = None) -> int:
    arguments = construire_parseur().parse_args(argv)
    commandes = {
        "generer": commande_generer, "nettoyer": commande_nettoyer, "verifier": commande_verifier, "mesurer": commande_mesurer,
        "rapport": commande_rapport,
    }
    try:
        resultat = commandes[arguments.commande](arguments)
    except (ValueError, FileNotFoundError) as erreur:
        print(f"Échec : {erreur}", file=sys.stderr)
        return 1
    print(json.dumps(resultat, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
