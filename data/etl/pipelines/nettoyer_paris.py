"""Nettoyage d'un fichier brut du comptage routier de Paris : lignes propres, lignes refusées avec leur règle, taux de rejet.

    cd data/etl
    python -m pipelines.nettoyer_paris --day 2026-10-17

Entrée : le fichier brut rangé par DAT-03 (jamais modifié). Sorties, reconstruites à chaque exécution et identiques
d'une exécution à l'autre :
  - propre/<fichier>.csv   lignes retenues, typées ;
  - rejets/<fichier>.jsonl lignes refusées : source_ref, règle, motif et ligne d'origine ;
  - dwh.etl_reject (PostgreSQL, option --postgres-url) : les mêmes rejets ;
  - processing_stats (MongoDB, option --mongo-url) : le bilan et le taux de rejet.
Le chargement dans l'entrepôt est DAT-05. Documentation : docs/03-donnees/nettoyage-paris.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import secrets
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from transforms import paris_qualite as qualite

from pipelines import paris_comptages as paris
from pipelines.sorties import ErreurSortie, RejetsPostgres, SortieBilan, SortieRejets, lire_rejets

NOM_BRUT = re.compile(r"(\d{8}T\d{6}Z)_(\d{8}T\d{6}Z)_([0-9a-f]{12})\.csv")
RACINE = Path(__file__).resolve().parents[3]
DONNEES = RACINE / "data" / "datasets"
SEUIL_ALERTE = 0.5  # valeur de départ ; le taux observé le 17/10/2026 est de 41 %, presque tout par absence de débit
COLONNES_PROPRES = (
    "road_segment_id", "label", "hour_utc", "vehicle_count", "occupancy_pct", "traffic_state", "barrier_state",
    "upstream_node_id", "downstream_node_id", "quality_flags", "source_line",
)


class ErreurNettoyage(Exception):
    """Le fichier brut n'est pas utilisable (nom, empreinte, introuvable)."""


@dataclass(frozen=True)
class Resultat:
    brut: Path
    propre: Path
    rejets: Path
    sha256: str
    bilan: qualite.Bilan
    alerte: bool
    rejets_postgres: int | None  # None : pas d'adresse PostgreSQL
    bilan_journalise: bool


def lire_lignes(chemin: Path) -> Iterator[tuple[int, dict[str, str]]]:
    """Lignes de données du fichier brut : (rang à partir de 1, valeurs textuelles par colonne)."""
    with chemin.open(encoding="utf-8-sig", newline="") as fichier:
        yield from enumerate(csv.DictReader(fichier, delimiter=";"), start=1)


def ligne_csv(ligne: qualite.LignePropre) -> list[str]:
    def texte(valeur) -> str:
        if valeur is None:
            return ""
        return repr(valeur) if isinstance(valeur, float) else str(valeur)

    return [
        ligne.road_segment_id, ligne.libelle, ligne.heure.strftime("%Y-%m-%dT%H:%M:%SZ"), texte(ligne.vehicle_count),
        texte(ligne.occupancy_pct), texte(ligne.traffic_state), texte(ligne.barrier_state), ligne.upstream_node_id,
        ligne.downstream_node_id, ",".join(ligne.flags), str(ligne.ligne),
    ]


def ligne_rejet(rejet: qualite.Rejet, nom_brut: str) -> str:
    return json.dumps(
        {"source_ref": f"{nom_brut}#{rejet.ligne}", "rule": rejet.regle, "reason": rejet.motif, "payload": rejet.brut},
        ensure_ascii=False, sort_keys=True,
    )


def verifier_brut(brut: Path) -> tuple[str, datetime]:
    """Contrôle le nom et l'empreinte du fichier brut ; rend son SHA-256 et le début de sa fenêtre."""
    correspondance = NOM_BRUT.fullmatch(brut.name)
    if correspondance is None:
        raise ErreurNettoyage(f"Nom inattendu : {brut.name} (attendu : <début>_<fin>_<12 caractères du SHA-256>.csv, voir DAT-03).")
    if not brut.is_file():
        raise ErreurNettoyage(f"Fichier brut introuvable : {brut}.")
    empreinte = paris.sha256_du_fichier(brut)
    if not empreinte.startswith(correspondance.group(3)):
        raise ErreurNettoyage(f"{brut.name} ne correspond plus à l'empreinte de son nom : le brut a été modifié, le ré-ingérer.")
    return empreinte, datetime.strptime(correspondance.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def nettoyer_fichier(
    brut: Path,
    *,
    rejets_pg: SortieRejets | None = None,
    bilan_mongo: SortieBilan | None = None,
    maintenant: Callable[[], datetime] = lambda: datetime.now(UTC),
    seuil_alerte: float = SEUIL_ALERTE,
    run_id: str | None = None,
) -> Resultat:
    empreinte, debut = verifier_brut(brut)
    paris.analyser(brut)  # forme du fichier : en-tête et nombre de colonnes (levé par DAT-03 à l'ingestion, rejoué ici)
    dossier_propre, dossier_rejets = brut.parent / "propre", brut.parent / "rejets"
    propre, rejets = dossier_propre / f"{brut.stem}.csv", dossier_rejets / f"{brut.stem}.jsonl"
    dossier_propre.mkdir(exist_ok=True)
    dossier_rejets.mkdir(exist_ok=True)
    provisoires = (propre.with_suffix(".csv.part"), rejets.with_suffix(".jsonl.part"))

    nettoyeur = qualite.Nettoyeur(maintenant())
    try:
        with provisoires[0].open("w", encoding="utf-8", newline="") as sortie_propre, provisoires[1].open("w", encoding="utf-8", newline="\n") as sortie_rejets:
            ecrivain = csv.writer(sortie_propre, delimiter=";", lineterminator="\n")
            ecrivain.writerow(COLONNES_PROPRES)
            for rang, ligne in lire_lignes(brut):
                resultat = nettoyeur.traiter(rang, ligne)
                if isinstance(resultat, qualite.Rejet):
                    sortie_rejets.write(ligne_rejet(resultat, brut.name) + "\n")
                else:
                    ecrivain.writerow(ligne_csv(resultat))
        nettoyeur.bilan.verifier()
        os.replace(provisoires[0], propre)
        os.replace(provisoires[1], rejets)
    finally:
        for provisoire in provisoires:
            provisoire.unlink(missing_ok=True)

    bilan = nettoyeur.bilan
    envoyes = None
    if rejets_pg is not None:
        envoyes = rejets_pg.remplacer(paris.DATASET_ID, brut.name, lire_rejets(rejets))
        if envoyes != bilan.rejetees:
            raise ErreurSortie(f"{envoyes} rejets écrits dans PostgreSQL pour {bilan.rejetees} attendus.")
    alerte = bilan.taux_rejet > seuil_alerte
    if bilan_mongo is not None:
        instant = maintenant()
        bilan_mongo.enregistrer(
            {
                "dataset": paris.DATASET_ID, "source_file": brut.name, "source_sha256": empreinte, **bilan.en_dict(),
                "alert_threshold": seuil_alerte, "alert": alerte, "cleaned_at": instant,
                "run_id": run_id or f"net-{instant:%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}",
            },
            fenetre_debut=debut, sha256=empreinte,
        )
    return Resultat(brut, propre, rejets, empreinte, bilan, alerte, envoyes, bilan_mongo is not None)


def retrouver_brut(donnees: Path, jour: date) -> Path:
    modele = f"{jour:%Y%m%d}T000000Z_{jour + timedelta(days=1):%Y%m%d}T000000Z_*.csv"
    trouves = sorted((donnees / paris.DATASET_ID).glob(modele))
    if not trouves:
        raise ErreurNettoyage(f"Aucun fichier brut pour le {jour} sous {donnees / paris.DATASET_ID} : ingérer d'abord (etl-paris --day {jour}).")
    if len(trouves) > 1:
        noms = ", ".join(p.name for p in trouves)
        raise ErreurNettoyage(f"Plusieurs fichiers bruts pour ce jour (donnée corrigée à la source) : choisir avec --file parmi {noms}")
    return trouves[0]


def fichier_brut_nomme(donnees: Path, texte: str) -> Path:
    """Un fichier brut du dossier des données, désigné par son nom.

    Seul le nom (`os.path.basename`) sert à construire le chemin, et il doit être un nom de fichier brut de DAT-03 : un
    chemin donné en argument ne peut pas faire ouvrir un autre fichier (`../`, chemin absolu, lien vers ailleurs). Si la
    valeur contient un dossier, ce dossier doit être celui des fichiers bruts.
    """
    nom = os.path.basename(texte)
    if NOM_BRUT.fullmatch(nom) is None:
        raise ErreurNettoyage(f"Nom inattendu : {nom!r} (attendu : <début>_<fin>_<12 caractères du SHA-256>.csv, voir DAT-03).")
    dossier = donnees / paris.DATASET_ID
    dossier_donne = os.path.dirname(texte)
    if dossier_donne and Path(dossier_donne).resolve() != dossier.resolve():
        raise ErreurNettoyage(f"Fichier hors du dossier des fichiers bruts ({dossier}) : {texte!r}.")
    return dossier / nom


def lire_jour(texte: str) -> date:
    try:
        return date.fromisoformat(texte)
    except ValueError as erreur:
        raise argparse.ArgumentTypeError(f"jour illisible : {texte!r} (exemple : 2026-10-17)") from erreur


def construire_parseur() -> argparse.ArgumentParser:
    parseur = argparse.ArgumentParser(prog="pipelines.nettoyer_paris", description=__doc__.splitlines()[0])
    source = parseur.add_mutually_exclusive_group(required=True)
    source.add_argument("--day", type=lire_jour, metavar="AAAA-MM-JJ", help="le fichier brut du jour entier ingéré par DAT-03")
    source.add_argument("--file", help=f"un fichier brut précis du dossier {DONNEES / paris.DATASET_ID} (son nom suffit)")
    parseur.add_argument("--mongo-url", default=os.environ.get("MONGO_URL"), help="adresse MongoDB du bilan (sinon variable MONGO_URL)")
    parseur.add_argument("--postgres-url", default=os.environ.get("POSTGRES_URL"), help="adresse PostgreSQL des rejets (sinon variable POSTGRES_URL)")
    parseur.add_argument("--alert-threshold", type=float, default=SEUIL_ALERTE, metavar="TAUX",
                         help=f"taux de rejet au-delà duquel alerter, de 0 à 1 ({SEUIL_ALERTE})")
    return parseur


def principal(argv: Sequence[str] | None = None, *, donnees: Path = DONNEES, rejets_pg: SortieRejets | None = None,
              bilan_mongo: SortieBilan | None = None) -> int:
    """`donnees` (le dossier des fichiers) n'est pas une option de la ligne de commande : seuls les tests le changent."""
    arguments = construire_parseur().parse_args(argv)
    if not 0 <= arguments.alert_threshold <= 1:
        print("ERREUR : --alert-threshold doit être entre 0 et 1.", file=sys.stderr)
        return 1
    try:
        brut = fichier_brut_nomme(donnees, arguments.file) if arguments.file else retrouver_brut(donnees, arguments.day)
        if rejets_pg is None and arguments.postgres_url:
            rejets_pg = RejetsPostgres.depuis_url(arguments.postgres_url)
        if bilan_mongo is None and arguments.mongo_url:
            from pipelines.sorties import BilanMongo

            bilan_mongo = BilanMongo.depuis_url(arguments.mongo_url)
        resultat = nettoyer_fichier(brut, rejets_pg=rejets_pg, bilan_mongo=bilan_mongo, seuil_alerte=arguments.alert_threshold)
    except (ErreurNettoyage, ErreurSortie, paris.ErreurSource, qualite.ErreurBilan) as erreur:
        print(f"ERREUR : {erreur}", file=sys.stderr)
        return 1
    finally:
        if rejets_pg is not None and hasattr(rejets_pg, "fermer"):
            rejets_pg.fermer()
    afficher(resultat)
    return 0


def afficher(resultat: Resultat) -> None:
    bilan = resultat.bilan
    print(f"Fichier brut : {resultat.brut} (empreinte vérifiée)")
    print(f"Lignes lues  : {bilan.lues}")
    print(f"Propres      : {bilan.propres} -> {resultat.propre}")
    print(f"Rejetées     : {bilan.rejetees} ({bilan.taux_rejet:.2%}) -> {resultat.rejets}")
    for regle, nombre in sorted(bilan.par_regle.items()):
        print(f"  {regle:<17}: {nombre}")
    for drapeau, nombre in sorted(bilan.drapeaux.items()):
        print(f"Retenues avec le drapeau {drapeau} : {nombre}")
    pg = f"{resultat.rejets_postgres} lignes écrites" if resultat.rejets_postgres is not None else "non écrit (pas d'adresse PostgreSQL)"
    mongo = "journalisé dans MongoDB processing_stats (kind rejects)" if resultat.bilan_journalise else "affiché seulement (pas d'adresse MongoDB)"
    print(f"dwh.etl_reject : {pg}")
    print(f"Taux de rejet : {mongo}")
    if resultat.alerte:
        print(f"ALERTE : taux de rejet {bilan.taux_rejet:.2%} au-dessus du seuil.")


if __name__ == "__main__":
    sys.exit(principal())
