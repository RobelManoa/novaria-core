"""Chargement idempotent de fenêtres de trafic dans `dwh.fact_traffic_window` (DAT-06, rejeu du chargement de DAT-05).

    cd data/etl
    python -m pipelines.charger_entrepot --file fenetres.csv --run-id demo-2026-10-30

Le fichier (CSV UTF-8 séparé par des virgules, colonnes de `transforms.fenetres_trafic.COLONNES`) est contrôlé ligne à
ligne ; les lignes refusées vont dans `dwh.etl_reject` (jeu `fenetres_trafic`), les autres sont écrites en une seule
transaction par « insérer ou mettre à jour » sur la clé primaire de la table (tronçon, début, taille, run_id). Rejouer le
même fichier avec le même run_id ne crée aucune ligne et ne change aucune valeur : les totaux sont identiques.

Les jeux réels (Paris) ne sont pas chargés ici : ils ne contiennent ni état de congestion ni tronçon d'approche (ADR-027,
section 3.2). Documentation : docs/03-donnees/etl-planifie-local.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from transforms import fenetres_trafic as fenetres
from transforms.paris_qualite import Rejet

from pipelines.sorties import ErreurSortie, RejetsPostgres, SortieRejets

RACINE = Path(__file__).resolve().parents[3]
FENETRES = RACINE / "data" / "datasets" / "fenetres"  # dossier des fichiers de fenêtres (ignoré par git avec data/datasets/)
NOM_FENETRES = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.csv", re.ASCII)
DATASET = "fenetres_trafic"
LOT = 5000
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", re.ASCII)  # CHECK de la table : 1 à 80 caractères


class ErreurChargement(Exception):
    """Le chargement n'a pas eu lieu (fichier, paramètre ou base)."""


def fichier_fenetres(dossier: Path, texte: str) -> Path:
    """Un fichier de fenêtres du dossier prévu, désigné par son nom.

    Seul le nom (`os.path.basename`) sert à construire le chemin, et il doit être un nom de CSV simple : un chemin donné en
    argument ne peut pas faire ouvrir un autre fichier (`../`, chemin absolu, lien vers ailleurs). Si la valeur contient un
    dossier, ce dossier doit être celui des fichiers de fenêtres.
    """
    nom = os.path.basename(texte)
    if NOM_FENETRES.fullmatch(nom) is None:
        raise ErreurChargement(f"Nom de fichier refusé : {nom!r} (attendu : un nom de fichier .csv simple, lettres, chiffres, . _ -).")
    dossier_donne = os.path.dirname(texte)
    if dossier_donne and Path(dossier_donne).resolve() != dossier.resolve():
        raise ErreurChargement(f"Fichier hors du dossier des fichiers de fenêtres ({dossier}) : {texte!r}.")
    return dossier / nom


@dataclass(frozen=True)
class Totaux:
    """Ce que l'entrepôt contient pour un run : de quoi comparer deux chargements sans lire les lignes une à une."""

    lignes: int
    vehicules: int  # somme de vehicle_count
    debit: str  # somme de flow_veh_per_min, en texte (décimal exact)
    empreinte: str  # MD5 des lignes triées (hors loaded_at) : détecte aussi une valeur modifiée à nombre égal


@dataclass
class Resultat:
    fichier: Path
    sha256: str
    run_id: str
    lues: int = 0
    chargees: int = 0
    rejetees: int = 0
    par_regle: Counter = field(default_factory=Counter)
    inserees: int = 0
    totaux: Totaux | None = None

    @property
    def deja_presentes(self) -> int:
        return self.chargees - self.inserees


class Entrepot(Protocol):
    def referentiels(self) -> fenetres.Referentiels: ...

    def charger(self, run_id: str, lot: Iterable[fenetres.Fenetre]) -> int:
        """Écrit toutes les fenêtres en une transaction ; rend le nombre de lignes créées (les autres existaient déjà)."""

    def totaux(self, run_id: str) -> Totaux: ...


# Une colonne de la ligne par `%s`, dans l'ordre de COLONNES_SQL, puis l'identifiant métier du tronçon dont on retrouve la clé.
COLONNES_SQL = (
    "window_start", "window_size_s", "run_id", "source_type", "vehicle_count", "flow_veh_per_min", "average_speed_kmh",
    "occupancy_rate", "max_queue_length_m", "speed_ratio", "sample_count", "expected_sample_count", "congestion_state",
    "classifier_version",
)
A_METTRE_A_JOUR = COLONNES_SQL[3:]  # tout sauf la clé primaire
# Le WHERE du DO UPDATE fait d'un rejeu une absence d'écriture : une ligne identique n'est pas réécrite (loaded_at reste celui du premier chargement).
# Noms de colonnes constants, valeurs par paramètres (S608 ne s'applique pas).
SQL_ECRITURE = (
    f"INSERT INTO dwh.fact_traffic_window AS f (road_segment_key, {', '.join(COLONNES_SQL)}) "  # noqa: S608
    f"SELECT s.road_segment_key, {', '.join(['%s'] * len(COLONNES_SQL))} FROM dwh.dim_road_segment s WHERE s.road_segment_id = %s "
    "ON CONFLICT (road_segment_key, window_start, window_size_s, run_id) DO UPDATE SET "
    + ", ".join(f"{colonne} = EXCLUDED.{colonne}" for colonne in A_METTRE_A_JOUR)
    + ", loaded_at = now() WHERE ("
    + ", ".join(f"f.{colonne}" for colonne in A_METTRE_A_JOUR)
    + ") IS DISTINCT FROM ("
    + ", ".join(f"EXCLUDED.{colonne}" for colonne in A_METTRE_A_JOUR)
    + ")"
)
SQL_TOTAUX = (
    "SELECT count(*), coalesce(sum(f.vehicle_count), 0), coalesce(sum(f.flow_veh_per_min), 0)::text, "
    "md5(coalesce(string_agg(concat_ws('|', s.road_segment_id, to_char(f.window_start AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), "
    "f.window_size_s, f.source_type, f.vehicle_count, f.flow_veh_per_min, coalesce(f.average_speed_kmh::text, ''), "
    "coalesce(f.occupancy_rate::text, ''), coalesce(f.max_queue_length_m::text, ''), coalesce(f.speed_ratio::text, ''), "
    "f.sample_count, f.expected_sample_count, f.congestion_state, f.classifier_version), E'\\n' "
    "ORDER BY s.road_segment_id, f.window_start, f.window_size_s), '')) "
    "FROM dwh.fact_traffic_window f JOIN dwh.dim_road_segment s USING (road_segment_key) WHERE f.run_id = %s"
)


class EntrepotPostgres:
    """Écrit avec le compte `svc_traitement` (SELECT, INSERT, UPDATE, DELETE sur le schéma dwh)."""

    def __init__(self, connexion) -> None:
        self._connexion = connexion

    @classmethod
    def depuis_url(cls, url: str) -> EntrepotPostgres:
        import psycopg

        try:
            # autocommit : chaque `transaction()` ouvre et valide une vraie transaction (sinon elle ne serait qu'un point de reprise
            # dans la transaction implicite ouverte par la première lecture, et rien ne serait jamais validé).
            return cls(psycopg.connect(url, connect_timeout=5, autocommit=True))
        except psycopg.Error as erreur:
            raise ErreurSortie(f"PostgreSQL injoignable ou refusé ({type(erreur).__name__}) : lancer db-up.") from erreur

    @property
    def connexion(self):
        return self._connexion

    def referentiels(self) -> fenetres.Referentiels:
        import psycopg

        try:
            with self._connexion.cursor() as curseur:
                lire = {}
                for nom, requete in (("segments", "SELECT road_segment_id FROM dwh.dim_road_segment"),
                                     ("etats", "SELECT state_code FROM dwh.dim_congestion_state"),
                                     ("sources", "SELECT source_type FROM dwh.dim_source")):
                    curseur.execute(requete)
                    lire[nom] = frozenset(ligne[0] for ligne in curseur.fetchall())
        except psycopg.Error as erreur:
            raise ErreurSortie(f"Lecture des référentiels de l'entrepôt impossible ({type(erreur).__name__}).") from erreur
        return fenetres.Referentiels(**lire)

    def charger(self, run_id: str, lot: Iterable[fenetres.Fenetre]) -> int:
        import psycopg

        try:
            with self._connexion.transaction(), self._connexion.cursor() as curseur:
                avant = self._compter(curseur, run_id)
                paquet = []
                for fenetre in lot:
                    paquet.append(self._parametres(run_id, fenetre))
                    if len(paquet) == LOT:
                        curseur.executemany(SQL_ECRITURE, paquet)
                        paquet = []
                if paquet:
                    curseur.executemany(SQL_ECRITURE, paquet)
                return self._compter(curseur, run_id) - avant
        except psycopg.Error as erreur:
            raise ErreurSortie(f"PostgreSQL a refusé l'écriture dans dwh.fact_traffic_window ({type(erreur).__name__} : {erreur}).") from erreur

    @staticmethod
    def _parametres(run_id: str, f: fenetres.Fenetre) -> tuple:
        return (f.window_start, f.window_size_s, run_id, f.source_type, f.vehicle_count, f.flow_veh_per_min, f.average_speed_kmh,
                f.occupancy_rate, f.max_queue_length_m, f.speed_ratio, f.sample_count, f.expected_sample_count,
                f.congestion_state, f.classifier_version, f.road_segment_id)

    @staticmethod
    def _compter(curseur, run_id: str) -> int:
        curseur.execute("SELECT count(*) FROM dwh.fact_traffic_window WHERE run_id = %s", (run_id,))
        return int(curseur.fetchone()[0])

    def totaux(self, run_id: str) -> Totaux:
        import psycopg

        try:
            with self._connexion.cursor() as curseur:
                curseur.execute(SQL_TOTAUX, (run_id,))
                lignes, vehicules, debit, empreinte = curseur.fetchone()
        except psycopg.Error as erreur:
            raise ErreurSortie(f"Lecture des totaux impossible ({type(erreur).__name__}).") from erreur
        return Totaux(int(lignes), int(vehicules), str(debit), str(empreinte))

    def fermer(self) -> None:
        self._connexion.close()


def sha256_du_fichier(chemin: Path) -> str:
    resume = hashlib.sha256()
    with chemin.open("rb") as fichier:
        for bloc in iter(lambda: fichier.read(1 << 20), b""):
            resume.update(bloc)
    return resume.hexdigest()


def lire_lignes(chemin: Path) -> tuple[list[str], list[tuple[int, dict]]]:
    """En-tête et lignes numérotées à partir de 1 (le BOM éventuel est ignoré). Une ligne trop longue garde le surplus sous `_extra`."""
    try:
        with chemin.open(encoding="utf-8-sig", newline="") as fichier:
            lecteur = csv.DictReader(fichier, restkey="_extra")
            return list(lecteur.fieldnames or []), list(enumerate(lecteur, start=1))
    except (UnicodeDecodeError, csv.Error) as erreur:
        raise ErreurChargement(f"{chemin.name} n'est pas un CSV UTF-8 lisible ({type(erreur).__name__}).") from erreur


def ligne_rejet(rejet: Rejet, nom: str) -> dict:
    return {"source_ref": f"{nom}#{rejet.ligne}", "rule": rejet.regle, "reason": rejet.motif, "payload": dict(rejet.brut)}


def charger_fichier(fichier: Path, run_id: str, *, entrepot: Entrepot, rejets_pg: SortieRejets | None = None) -> Resultat:
    """Contrôle puis charge un fichier de fenêtres. Rien n'est écrit dans `fact_traffic_window` si une écriture échoue."""
    if not RUN_ID.fullmatch(run_id):
        raise ErreurChargement(f"run_id « {run_id} » refusé : 1 à 80 caractères parmi lettres, chiffres, . _ : -.")
    if not fichier.is_file():
        raise ErreurChargement(f"Fichier de fenêtres introuvable : {fichier}.")
    entete, lignes = lire_lignes(fichier)
    try:
        fenetres.verifier_entete(entete)
    except fenetres.ErreurFenetre as erreur:
        raise ErreurChargement(str(erreur)) from erreur

    controleur = fenetres.Controleur(entrepot.referentiels())
    resultat = Resultat(fichier, sha256_du_fichier(fichier), run_id)
    retenues: list[fenetres.Fenetre] = []
    refusees: list[dict] = []
    for rang, ligne in lignes:
        resultat.lues += 1
        sortie = controleur.traiter(rang, ligne)
        if isinstance(sortie, Rejet):
            resultat.rejetees += 1
            resultat.par_regle[sortie.regle] += 1
            refusees.append(ligne_rejet(sortie, fichier.name))
        else:
            retenues.append(sortie)
    resultat.chargees = len(retenues)

    if rejets_pg is not None:
        ecrits = rejets_pg.remplacer(DATASET, fichier.name, refusees)
        if ecrits != len(refusees):  # réconciliation de l'ADR-013 : lues = chargées + rejetées, et chaque rejet est tracé
            raise ErreurChargement(f"{ecrits} rejets écrits pour {len(refusees)} lignes refusées : rien n'est chargé.")
    resultat.inserees = entrepot.charger(run_id, retenues)
    resultat.totaux = entrepot.totaux(run_id)
    return resultat


def afficher(resultat: Resultat) -> None:
    print(f"Fichier   : {resultat.fichier} (sha256 {resultat.sha256[:12]})")
    print(f"Run       : {resultat.run_id}")
    print(f"Lignes    : {resultat.lues} lues = {resultat.chargees} chargées + {resultat.rejetees} rejetées")
    for regle, nombre in sorted(resultat.par_regle.items()):
        print(f"  {regle:<22}: {nombre}")
    print(f"Écriture  : {resultat.inserees} créées, {resultat.deja_presentes} déjà présentes (identiques ou mises à jour)")
    totaux = resultat.totaux
    print(f"Totaux    : {totaux.lignes} lignes, {totaux.vehicules} véhicules, débit {totaux.debit}, empreinte {totaux.empreinte}")


def construire_parseur() -> argparse.ArgumentParser:
    parseur = argparse.ArgumentParser(description="Charge un fichier de fenêtres de trafic dans dwh.fact_traffic_window (rejouable).")
    parseur.add_argument("--file", required=True, help="fichier CSV de fenêtres, dans data/datasets/fenetres/ (son nom suffit)")
    parseur.add_argument("--run-id", required=True, help="identifiant de l'exécution d'origine (partie de la clé d'idempotence)")
    parseur.add_argument("--postgres-url", default=os.environ.get("POSTGRES_URL"), help="adresse PostgreSQL (sinon variable POSTGRES_URL)")
    return parseur


def principal(argv: Sequence[str] | None = None, *, entrepot: Entrepot | None = None, rejets_pg: SortieRejets | None = None,
              dossier: Path = FENETRES) -> int:
    """`dossier` n'est pas une option de la ligne de commande : seuls les tests le changent."""
    arguments = construire_parseur().parse_args(argv)
    try:
        fichier = fichier_fenetres(dossier, arguments.file)
        if entrepot is None:
            if not arguments.postgres_url:
                raise ErreurChargement("Adresse PostgreSQL absente : variable POSTGRES_URL ou option --postgres-url "
                                       "(python scripts/dev/dev.py etl-charger la construit depuis .env).")
            entrepot = EntrepotPostgres.depuis_url(arguments.postgres_url)
            rejets_pg = RejetsPostgres(entrepot.connexion)
        resultat = charger_fichier(fichier, arguments.run_id, entrepot=entrepot, rejets_pg=rejets_pg)
    except (ErreurChargement, ErreurSortie) as erreur:
        print(f"ERREUR : {erreur}", file=sys.stderr)
        return 1
    finally:
        if hasattr(entrepot, "fermer"):
            entrepot.fermer()
    afficher(resultat)
    return 0


if __name__ == "__main__":
    sys.exit(principal())
