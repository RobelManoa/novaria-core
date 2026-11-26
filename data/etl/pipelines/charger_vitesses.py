"""Charge un réseau de mesures de vitesse dans `dwh.speed_*` : un manifeste et un fichier de mesures, rien d'autre (IA-16, ADR-032).

    cd data/etl
    python -m pipelines.charger_vitesses --reseau metr-la

Le dossier `data/datasets/vitesses/<réseau>/` contient :

- `manifeste.json` : `network_id`, `label`, `description`, `source_type`, `step_s` (60 ou 300), `speed_unit` (`mph` ou `kmh`) et
  `sensors`, la liste ordonnée des identifiants de capteurs (leur rang dans la liste est leur rang pour toujours) ;
- `mesures.csv` : `observed_at,sensor_id,speed` (instant UTC `...Z`, aligné sur le pas du réseau, vitesse dans l'unité du manifeste).

**Ajouter des capteurs ne demande aucun code** : on les ajoute en fin de liste dans le manifeste et leurs lignes dans le fichier de
mesures, puis on relance la commande. Un capteur déjà connu ne change jamais de rang (un modèle appris s'appuie sur cet ordre) : un
manifeste qui le déplace est refusé. Rejouer le même dossier ne crée aucune ligne et ne change aucune valeur.

Seules les vitesses mesurées ont une ligne : une vitesse absente du fichier reste absente, jamais remplie. Une ligne refusée (capteur
inconnu, instant mal formé ou non aligné, vitesse hors bornes) est comptée par motif ; le chargement continue.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

RACINE = Path(__file__).resolve().parents[3]
DOSSIER = RACINE / "data" / "datasets" / "vitesses"
NOM_RESEAU = re.compile(r"[a-z0-9][a-z0-9-]{0,39}", re.ASCII)
IDENTIFIANT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}", re.ASCII)
INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", re.ASCII)
CHAMPS = {"network_id", "label", "description", "source_type", "step_s", "speed_unit", "sensors"}
SOURCES = {"REAL_HISTORICAL", "SIMULATED", "REAL_STREAM"}
LOT = 50_000
VITESSE_MAX = 300.0


class ErreurChargement(Exception):
    """Le chargement n'a pas eu lieu (manifeste, fichier ou base)."""


@dataclass(frozen=True)
class Manifeste:
    network_id: str
    label: str
    description: str
    source_type: str
    step_s: int
    speed_unit: str
    sensors: tuple[str, ...]


def lire_manifeste(chemin: Path) -> Manifeste:
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erreur:
        raise ErreurChargement(f"Manifeste illisible ({chemin.name}) : {erreur}") from erreur
    if not isinstance(brut, dict) or set(brut) != CHAMPS:
        raise ErreurChargement(f"Manifeste : champs attendus exactement {sorted(CHAMPS)}.")
    if not (isinstance(brut["network_id"], str) and NOM_RESEAU.fullmatch(brut["network_id"])):
        raise ErreurChargement("Manifeste : network_id de 1 à 40 caractères (minuscules, chiffres, tiret).")
    for champ in ("label", "description"):
        if not isinstance(brut[champ], str) or (champ == "label" and not 1 <= len(brut[champ]) <= 120):
            raise ErreurChargement(f"Manifeste : {champ} texte attendu (label de 1 à 120 caractères).")
    if brut["source_type"] not in SOURCES:
        raise ErreurChargement(f"Manifeste : source_type parmi {sorted(SOURCES)}.")
    if brut["step_s"] not in (60, 300) or isinstance(brut["step_s"], bool):
        raise ErreurChargement("Manifeste : step_s vaut 60 ou 300.")
    if brut["speed_unit"] not in ("mph", "kmh"):
        raise ErreurChargement("Manifeste : speed_unit vaut mph ou kmh.")
    capteurs = brut["sensors"]
    if not isinstance(capteurs, list) or not capteurs or not all(isinstance(c, str) and IDENTIFIANT.fullmatch(c) for c in capteurs):
        raise ErreurChargement("Manifeste : sensors est une liste non vide d'identifiants (lettres, chiffres, . _ -).")
    if len(set(capteurs)) != len(capteurs):
        raise ErreurChargement("Manifeste : identifiants de capteurs en double.")
    return Manifeste(brut["network_id"], brut["label"], brut["description"], brut["source_type"], brut["step_s"], brut["speed_unit"], tuple(capteurs))


@dataclass
class Resultat:
    reseau: str
    capteurs: int = 0
    lues: int = 0
    chargees: int = 0
    rejetees: int = 0
    par_motif: Counter = field(default_factory=Counter)


Mesure = tuple[datetime, int, float]  # instant, rang du capteur, vitesse


def lire_mesures(chemin: Path, manifeste: Manifeste, resultat: Resultat) -> Iterator[Mesure]:
    """Les mesures valides du fichier, une à une ; les autres sont comptées par motif dans `resultat`."""
    rang = {capteur: i for i, capteur in enumerate(manifeste.sensors)}
    try:
        with chemin.open(encoding="utf-8", newline="") as source:
            lecteur = csv.reader(source)
            if next(lecteur, None) != ["observed_at", "sensor_id", "speed"]:
                raise ErreurChargement("mesures.csv : en-tête attendu « observed_at,sensor_id,speed ».")
            for ligne in lecteur:
                resultat.lues += 1
                motif = None
                if len(ligne) != 3:
                    motif = "colonnes"
                elif ligne[1] not in rang:
                    motif = "capteur inconnu"
                elif not INSTANT.fullmatch(ligne[0]):
                    motif = "instant mal formé"
                else:
                    try:
                        instant = datetime.strptime(ligne[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
                    except ValueError:
                        instant = None
                    if instant is None:
                        motif = "instant mal formé"
                    elif instant.timestamp() % manifeste.step_s:
                        motif = "instant non aligné sur le pas"
                    else:
                        try:
                            vitesse = float(ligne[2])
                        except ValueError:
                            vitesse = float("nan")
                        if not 0 < vitesse < VITESSE_MAX:
                            motif = "vitesse hors bornes"
                if motif:
                    resultat.rejetees += 1
                    resultat.par_motif[motif] += 1
                    continue
                yield instant, rang[ligne[1]], vitesse
    except OSError as erreur:
        raise ErreurChargement(f"mesures.csv illisible : {erreur}") from erreur
    except UnicodeDecodeError as erreur:
        raise ErreurChargement("mesures.csv : UTF-8 attendu.") from erreur


class Entrepot(Protocol):
    def enregistrer(self, manifeste: Manifeste) -> None: ...

    def charger(self, network_id: str, lot: list[Mesure]) -> int: ...


def charger_reseau(dossier: Path, *, entrepot: Entrepot) -> Resultat:
    manifeste = lire_manifeste(dossier / "manifeste.json")
    resultat = Resultat(manifeste.network_id, capteurs=len(manifeste.sensors))
    entrepot.enregistrer(manifeste)
    lot: list[Mesure] = []
    for mesure in lire_mesures(dossier / "mesures.csv", manifeste, resultat):
        lot.append(mesure)
        if len(lot) >= LOT:
            resultat.chargees += entrepot.charger(manifeste.network_id, lot)
            lot = []
    if lot:
        resultat.chargees += entrepot.charger(manifeste.network_id, lot)
    return resultat


class EntrepotPostgres:
    def __init__(self, connexion) -> None:
        self._connexion = connexion

    @classmethod
    def depuis_url(cls, url: str) -> EntrepotPostgres:
        import psycopg

        try:
            return cls(psycopg.connect(url, connect_timeout=5, autocommit=True))
        except psycopg.Error as erreur:
            raise ErreurChargement(f"PostgreSQL injoignable ou refusé ({type(erreur).__name__}) : lancer db-up.") from erreur

    def fermer(self) -> None:
        self._connexion.close()

    def enregistrer(self, manifeste: Manifeste) -> None:
        import psycopg

        try:
            with self._connexion.transaction(), self._connexion.cursor() as curseur:
                curseur.execute(
                    "INSERT INTO dwh.speed_network (network_id, label, description, source_type, step_s, speed_unit) "
                    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (network_id) DO UPDATE SET label = EXCLUDED.label, "
                    "description = EXCLUDED.description, source_type = EXCLUDED.source_type, step_s = EXCLUDED.step_s, "
                    "speed_unit = EXCLUDED.speed_unit",
                    (manifeste.network_id, manifeste.label, manifeste.description, manifeste.source_type, manifeste.step_s, manifeste.speed_unit),
                )
                curseur.execute("SELECT sensor_key, sensor_id FROM dwh.speed_sensor WHERE network_id = %s", (manifeste.network_id,))
                connus = {cle: capteur for cle, capteur in curseur.fetchall()}
                for cle, capteur in connus.items():
                    if cle >= len(manifeste.sensors) or manifeste.sensors[cle] != capteur:
                        raise ErreurChargement(
                            f"Le capteur {capteur!r} a le rang {cle} dans l'entrepôt : le manifeste ne doit ni le déplacer ni le retirer "
                            "(un modèle appris s'appuie sur cet ordre). Ajouter les nouveaux capteurs en fin de liste."
                        )
                for cle, capteur in enumerate(manifeste.sensors):
                    if cle not in connus:
                        curseur.execute(
                            "INSERT INTO dwh.speed_sensor (network_id, sensor_key, sensor_id) VALUES (%s, %s, %s)",
                            (manifeste.network_id, cle, capteur),
                        )
        except psycopg.Error as erreur:
            raise ErreurChargement(f"Écriture refusée par PostgreSQL ({type(erreur).__name__}).") from erreur

    def charger(self, network_id: str, lot: list[Mesure]) -> int:
        """Écrit un lot par « insérer ou mettre à jour ». Pas de table temporaire : le compte du traitement n'a pas ce droit."""
        import psycopg

        try:
            with self._connexion.transaction(), self._connexion.cursor() as curseur:
                curseur.execute(
                    "INSERT INTO dwh.fact_speed_window (network_id, observed_at, sensor_key, speed) "
                    "SELECT %s, u.observed_at, u.sensor_key, u.speed "
                    "FROM unnest(%s::timestamptz[], %s::integer[], %s::numeric[]) AS u(observed_at, sensor_key, speed) "
                    "ON CONFLICT (network_id, observed_at, sensor_key) DO UPDATE SET speed = EXCLUDED.speed",
                    (network_id, [m[0] for m in lot], [m[1] for m in lot], [m[2] for m in lot]),
                )
                return len(lot)
        except psycopg.Error as erreur:
            raise ErreurChargement(f"Écriture refusée par PostgreSQL ({type(erreur).__name__}).") from erreur


def dossier_du_reseau(base: Path, nom: str) -> Path:
    if NOM_RESEAU.fullmatch(nom) is None:
        raise ErreurChargement(f"Nom de réseau refusé : {nom!r} (minuscules, chiffres et tiret, 40 caractères au plus).")
    dossier = base / nom
    if not (dossier / "manifeste.json").is_file() or not (dossier / "mesures.csv").is_file():
        raise ErreurChargement(f"{dossier} doit contenir manifeste.json et mesures.csv.")
    return dossier


def afficher(resultat: Resultat) -> None:
    print(f"Réseau {resultat.reseau} : {resultat.capteurs} capteurs ; {resultat.lues} lignes lues, {resultat.chargees} chargées, "
          f"{resultat.rejetees} refusées.")
    for motif, nombre in sorted(resultat.par_motif.items()):
        print(f"  refusées : {motif} : {nombre}")


def principal(argv: Sequence[str] | None = None, *, entrepot: Entrepot | None = None, base: Path = DOSSIER) -> int:
    parseur = argparse.ArgumentParser(description="Charge un réseau de vitesses (manifeste et mesures) dans dwh.speed_* (rejouable).")
    parseur.add_argument("--reseau", required=True, help="nom du dossier dans data/datasets/vitesses/")
    parseur.add_argument("--postgres-url", default=os.environ.get("POSTGRES_URL"), help="adresse PostgreSQL (sinon variable POSTGRES_URL)")
    arguments = parseur.parse_args(argv)
    try:
        dossier = dossier_du_reseau(base, arguments.reseau)
        if entrepot is None:
            if not arguments.postgres_url:
                raise ErreurChargement("Adresse PostgreSQL absente : variable POSTGRES_URL ou option --postgres-url "
                                       "(python scripts/dev/dev.py etl-vitesses la construit depuis .env).")
            entrepot = EntrepotPostgres.depuis_url(arguments.postgres_url)
        resultat = charger_reseau(dossier, entrepot=entrepot)
    except ErreurChargement as erreur:
        print(f"ERREUR : {erreur}", file=sys.stderr)
        return 1
    finally:
        if hasattr(entrepot, "fermer"):
            entrepot.fermer()
    afficher(resultat)
    return 0


__all__ = ["ErreurChargement", "Manifeste", "charger_reseau", "principal"]

if __name__ == "__main__":
    sys.exit(principal())
