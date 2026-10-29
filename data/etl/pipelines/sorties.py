"""Sorties du nettoyage (DAT-04) : lignes refusées dans PostgreSQL `dwh.etl_reject`, bilan dans MongoDB `processing_stats`.

Les pilotes (psycopg, pymongo) ne sont importés qu'à l'écriture : les tests sans base n'ont pas besoin de les installer.
Les deux écritures se rejouent sans doublon : les rejets d'un fichier sont remplacés dans une transaction, le bilan d'un
fichier (même empreinte) est mis à jour sur place.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Protocol

LOT = 5000
KIND_BILAN = "rejects"  # valeur de `kind` dans processing_stats : taux et motifs de rejet d'un chargement


class ErreurSortie(Exception):
    """Une sortie (PostgreSQL ou MongoDB) n'a pas pu être écrite."""


class SortieRejets(Protocol):
    def remplacer(self, dataset: str, fichier: str, rejets: Iterable[Mapping]) -> int: ...


class SortieBilan(Protocol):
    def enregistrer(self, valeurs: Mapping, *, fenetre_debut: datetime, sha256: str) -> None: ...


class RejetsPostgres:
    """Écrit dans `dwh.etl_reject` avec le compte `svc_traitement` (dictionnaire, section 8.1)."""

    def __init__(self, connexion) -> None:
        self._connexion = connexion

    @classmethod
    def depuis_url(cls, url: str) -> RejetsPostgres:
        import psycopg

        try:
            return cls(psycopg.connect(url, connect_timeout=5))
        except psycopg.Error as erreur:
            raise ErreurSortie(f"PostgreSQL injoignable ou refusé ({type(erreur).__name__}) : lancer db-up.") from erreur

    def remplacer(self, dataset: str, fichier: str, rejets: Iterable[Mapping]) -> int:
        """Remplace tous les rejets de ce fichier par ceux-ci, en une transaction : rejouer ne duplique rien."""
        import psycopg
        from psycopg.types.json import Jsonb

        prefixe = f"{fichier}#"
        total = 0
        try:
            with self._connexion.transaction(), self._connexion.cursor() as curseur:
                curseur.execute("DELETE FROM dwh.etl_reject WHERE dataset = %s AND starts_with(source_ref, %s)", (dataset, prefixe))
                lot = []
                for rejet in rejets:
                    lot.append((dataset, rejet["source_ref"], rejet["rule"], rejet["reason"], Jsonb(rejet["payload"])))
                    if len(lot) == LOT:
                        total += self._inserer(curseur, lot)
                        lot = []
                total += self._inserer(curseur, lot)
        except psycopg.Error as erreur:
            raise ErreurSortie(f"PostgreSQL a refusé l'écriture dans dwh.etl_reject ({type(erreur).__name__} : {erreur}).") from erreur
        return total

    @staticmethod
    def _inserer(curseur, lot: list) -> int:
        if lot:
            curseur.executemany("INSERT INTO dwh.etl_reject (dataset, source_ref, rule, reason, payload) VALUES (%s, %s, %s, %s, %s)", lot)
        return len(lot)

    def fermer(self) -> None:
        self._connexion.close()


class BilanMongo:
    """Écrit le taux de rejet d'un fichier dans `processing_stats` (kind = rejects) avec le compte `svc_traitement`."""

    def __init__(self, collection) -> None:
        self._collection = collection

    @classmethod
    def depuis_url(cls, url: str) -> BilanMongo:
        from pymongo import MongoClient

        try:
            base = MongoClient(url, serverSelectionTimeoutMS=5000).get_default_database()
        except Exception as erreur:  # adresse sans nom de base, ou mal formée
            raise ErreurSortie(f"Adresse MongoDB inutilisable : {type(erreur).__name__}.") from erreur
        return cls(base["processing_stats"])

    def enregistrer(self, valeurs: Mapping, *, fenetre_debut: datetime, sha256: str) -> None:
        """Un document par fichier brut (clé : kind, fenêtre, empreinte) ; une nouvelle exécution le met à jour."""
        from pymongo.errors import OperationFailure, PyMongoError

        filtre = {"kind": KIND_BILAN, "window_start": fenetre_debut, "values.source_sha256": sha256}
        champs = {f"values.{cle}": valeur for cle, valeur in valeurs.items() if cle != "source_sha256"}
        try:
            self._collection.update_one(filtre, {"$set": champs}, upsert=True)
        except OperationFailure as erreur:
            raise ErreurSortie(f"MongoDB a refusé l'écriture dans processing_stats (code {erreur.code}).") from erreur
        except PyMongoError as erreur:
            raise ErreurSortie(f"MongoDB injoignable ({type(erreur).__name__}) : lancer db-up.") from erreur


def lire_rejets(chemin: Path) -> Iterable[dict]:
    """Relit le fichier JSON Lines des rejets, une ligne à la fois."""
    with chemin.open(encoding="utf-8") as fichier:
        for ligne in fichier:
            yield json.loads(ligne)
