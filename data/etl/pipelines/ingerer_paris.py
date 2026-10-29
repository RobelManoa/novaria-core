"""Ingestion du comptage routier de Paris : télécharge une fenêtre de temps, garde le fichier brut, journalise dans MongoDB.

    cd data/etl
    python -m pipelines.ingerer_paris --day 2026-10-18

Rejouable : un fichier identique à un fichier déjà reçu (même SHA-256) n'est ni réécrit ni journalisé une seconde fois.
Tout ce qui suit le dépôt du brut (nettoyage, rejets, entrepôt) relève de DAT-04 et DAT-05. Documentation :
docs/03-donnees/ingestion-paris.md.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from pipelines import paris_comptages as paris
from pipelines.journal import ErreurJournal, Journal, JournalMongo

RACINE = Path(__file__).resolve().parents[3]
DONNEES = RACINE / "data" / "datasets"


class ErreurIntegrite(Exception):
    """Un fichier déjà rangé sous ce nom n'a pas l'empreinte annoncée par son nom : il a été modifié."""


@dataclass(frozen=True)
class Resultat:
    load_key: str
    fichier: Path
    fichier_ecrit: bool  # faux si le même fichier était déjà rangé
    nouveau: bool  # faux si ce fichier était déjà journalisé
    executions: int
    sha256: str
    octets: int
    lignes: int


def maintenant_utc() -> datetime:
    return datetime.now(UTC)


def horodate(valeur: datetime) -> str:
    return valeur.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def ranger(telechargement: paris.Telechargement, definitif: Path) -> bool:
    """Déplace le fichier reçu à sa place définitive. Rend faux si un fichier identique s'y trouvait déjà."""
    if definitif.exists():
        if paris.sha256_du_fichier(definitif) != telechargement.sha256:
            raise ErreurIntegrite(f"{definitif} ne correspond plus à l'empreinte de son nom : fichier modifié ou corrompu.")
        return False
    os.replace(telechargement.chemin, definitif)
    return True


def ingerer(
    debut: datetime,
    fin: datetime,
    *,
    racine: Path,
    journal: Journal,
    ouvrir: paris.Ouvrir = paris.ouvrir_par_defaut,
    maintenant: Callable[[], datetime] = maintenant_utc,
    run_id: str | None = None,
) -> Resultat:
    """Télécharge [début, fin[, range le fichier brut sous `racine`, puis l'inscrit au journal.

    Le fichier est rangé avant l'écriture au journal : si le journal échoue, la relance retrouve le fichier et
    n'écrit que l'entrée manquante. Le nom du fichier contient les 12 premiers caractères de son SHA-256 : une
    donnée corrigée à la source donne un nouveau fichier, l'ancien reste.
    """
    debut, fin = paris.verifier_fenetre(debut, fin)
    adresse = paris.adresse_export(debut, fin)
    dossier = racine / paris.DATASET_ID
    telechargement = paris.telecharger(adresse, dossier, ouvrir=ouvrir)
    try:
        lignes = paris.analyser(telechargement.chemin)
        nom = f"{horodate(debut)}_{horodate(fin)}_{telechargement.sha256[:12]}.csv"
        ecrit = ranger(telechargement, dossier / nom)
    finally:
        telechargement.chemin.unlink(missing_ok=True)

    entree = {
        "load_key": f"{paris.DATASET_ID}:{horodate(debut)}:{horodate(fin)}:{telechargement.sha256}",
        "dataset_id": paris.DATASET_ID,
        "source_type": paris.SOURCE_TYPE,
        "source_url": adresse,
        "license": paris.LICENCE,
        "window_start": debut,
        "window_end": fin,
        "file_path": f"{paris.DATASET_ID}/{nom}",
        "sha256": telechargement.sha256,
        "bytes": telechargement.octets,
        "rows": lignes,
    }
    modifiee = paris.date_de_modification_source(ouvrir=ouvrir)
    if modifiee is not None:
        entree["source_modified_at"] = modifiee
    instant = maintenant()
    passage = journal.enregistrer(entree, maintenant=instant, run_id=run_id or f"ing-{horodate(instant)}-{secrets.token_hex(4)}")
    return Resultat(entree["load_key"], dossier / nom, ecrit, passage.nouveau, passage.executions, telechargement.sha256,
                    telechargement.octets, lignes)


def lire_instant(texte: str) -> datetime:
    try:
        return datetime.fromisoformat(texte)
    except ValueError as erreur:
        raise argparse.ArgumentTypeError(f"date illisible : {texte!r} (exemple : 2026-10-18T10:00:00Z)") from erreur


def lire_jour(texte: str) -> date:
    try:
        return date.fromisoformat(texte)
    except ValueError as erreur:
        raise argparse.ArgumentTypeError(f"jour illisible : {texte!r} (exemple : 2026-10-18)") from erreur


def construire_parseur() -> argparse.ArgumentParser:
    parseur = argparse.ArgumentParser(prog="pipelines.ingerer_paris", description=__doc__.splitlines()[0])
    fenetre = parseur.add_mutually_exclusive_group(required=True)
    fenetre.add_argument("--day", type=lire_jour, metavar="AAAA-MM-JJ", help="un jour entier, de 00:00 à 24:00 UTC")
    fenetre.add_argument("--start", type=lire_instant, metavar="INSTANT", help="début inclus, avec fuseau (…T10:00:00Z)")
    parseur.add_argument("--end", type=lire_instant, metavar="INSTANT", help="fin exclue, avec fuseau (avec --start)")
    parseur.add_argument("--data-dir", type=Path, default=DONNEES, help=f"dossier des fichiers bruts ({DONNEES})")
    parseur.add_argument("--mongo-url", default=os.environ.get("MONGO_URL"), help="adresse MongoDB (sinon variable MONGO_URL)")
    return parseur


def principal(argv: Sequence[str] | None = None, *, journal: Journal | None = None,
              ouvrir: paris.Ouvrir = paris.ouvrir_par_defaut) -> int:
    parseur = construire_parseur()
    arguments = parseur.parse_args(argv)
    if arguments.day and arguments.end:
        parseur.error("--end s'emploie avec --start, pas avec --day")
    if arguments.day:
        debut, fin = paris.fenetre_du_jour(arguments.day)
    elif arguments.end:
        debut, fin = arguments.start, arguments.end
    else:
        parseur.error("--start demande aussi --end")
    try:
        if journal is None:
            if not arguments.mongo_url:
                raise ErreurJournal("Adresse MongoDB absente : variable MONGO_URL ou option --mongo-url "
                                    "(python scripts/dev/dev.py etl-paris la construit depuis .env).")
            journal = JournalMongo.depuis_url(arguments.mongo_url)
        resultat = ingerer(debut, fin, racine=arguments.data_dir, journal=journal, ouvrir=ouvrir)
    except (ValueError, paris.ErreurSource, ErreurIntegrite, ErreurJournal) as erreur:
        print(f"ERREUR : {erreur}", file=sys.stderr)
        return 1
    print(f"Fichier   : {resultat.fichier} ({'écrit' if resultat.fichier_ecrit else 'déjà présent, identique'})")
    print(f"Volume    : {resultat.octets} octets, {resultat.lignes} lignes de données")
    print(f"Empreinte : sha256 {resultat.sha256}")
    print("Journal   : " + ("nouvelle entrée" if resultat.nouveau else "déjà journalisé") + f" (reçu {resultat.executions} fois)")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
