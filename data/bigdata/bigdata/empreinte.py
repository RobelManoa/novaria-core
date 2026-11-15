"""Empreinte des résultats : de quoi dire que deux moteurs ont rendu la même chose, sans comparer des millions de lignes une à une.

Pour les lignes propres : leur nombre, la somme des CRC-32 d'une ligne canonique (nom du fichier, colonnes propres,
séparées par « | »), et les sommes entières du débit (en millièmes) et de l'occupation (en cent-millièmes). Pour les
rejets : leur nombre par règle et la somme des CRC-32 de « fichier#ligne|règle ». Une somme de CRC-32 ne dépend pas de
l'ordre des lignes : Python et Spark peuvent les écrire dans n'importe quel ordre. Les montants sont convertis en entiers
par la **même** opération sur les deux moteurs (`floor(x × 1000 + 0,5)`), pour éviter que l'ordre d'addition de flottants
ne fasse deux sommes.

Une égalité d'empreintes ne **prouve** pas l'égalité des lignes (deux jeux différents peuvent avoir la même somme) : elle
la rend invraisemblable ; le test de parité compare en plus des échantillons ligne à ligne.
"""

import csv
import json
import math
import zlib
from collections.abc import Iterable
from pathlib import Path

ECHELLE_DEBIT = 1000
ECHELLE_OCCUPATION = 100_000
COLONNES_PROPRES = (
    "road_segment_id", "label", "hour_utc", "vehicle_count", "occupancy_pct", "traffic_state", "barrier_state",
    "upstream_node_id", "downstream_node_id", "quality_flags", "source_line",
)  # data/etl/pipelines/nettoyer_paris.py


def entier(texte: str, echelle: int) -> str:
    """`floor(x × échelle + 0,5)` en texte ; vide si la valeur est absente."""
    return "" if texte == "" else str(math.floor(float(texte) * echelle + 0.5))


def ligne_canonique(fichier: str, valeurs: Iterable[str]) -> str:
    """La ligne propre (onze colonnes de `nettoyer_paris`, en texte) sous sa forme canonique."""
    (segment, libelle, heure, debit, occupation, etat, barre, amont, aval, drapeaux, numero) = valeurs
    return "|".join((
        fichier, segment, libelle, heure, entier(debit, ECHELLE_DEBIT), entier(occupation, ECHELLE_OCCUPATION), etat, barre,
        amont, aval, drapeaux, numero,
    ))


def crc(texte: str) -> int:
    return zlib.crc32(texte.encode("utf-8"))


def vide() -> dict:
    return {
        "propres": {"lignes": 0, "somme_crc": 0, "debit_milliemes": 0, "occupation_cent_milliemes": 0, "occupations": 0},
        "rejets": {"lignes": 0, "somme_crc": 0, "par_regle": {}},
    }


def depuis_les_sorties_python(dossier: Path, noms: Iterable[str]) -> dict:
    """L'empreinte des sorties de `nettoyer_fichier` (`propre/*.csv`, `rejets/*.jsonl`) pour les fichiers bruts `noms`."""
    resultat = vide()
    propres, rejets = resultat["propres"], resultat["rejets"]
    for nom in sorted(noms):
        stem = nom.removesuffix(".csv")
        with (dossier / "propre" / f"{stem}.csv").open(encoding="utf-8", newline="") as fichier:
            lecteur = csv.reader(fichier, delimiter=";")
            next(lecteur)  # en-tête
            for valeurs in lecteur:
                propres["lignes"] += 1
                propres["somme_crc"] += crc(ligne_canonique(nom, valeurs))
                propres["debit_milliemes"] += math.floor(float(valeurs[3]) * ECHELLE_DEBIT + 0.5)
                if valeurs[4] != "":
                    propres["occupations"] += 1
                    propres["occupation_cent_milliemes"] += math.floor(float(valeurs[4]) * ECHELLE_OCCUPATION + 0.5)
        with (dossier / "rejets" / f"{stem}.jsonl").open(encoding="utf-8") as fichier:
            for texte in fichier:
                rejet = json.loads(texte)
                rejets["lignes"] += 1
                rejets["somme_crc"] += crc(f"{rejet['source_ref']}|{rejet['rule']}")
                rejets["par_regle"][rejet["rule"]] = rejets["par_regle"].get(rejet["rule"], 0) + 1
    rejets["par_regle"] = dict(sorted(rejets["par_regle"].items()))
    return resultat


def depuis_la_sortie_spark(spark, sortie: Path, noms: Iterable[str]) -> dict:
    """L'empreinte de la sortie Parquet de `nettoyage_spark.nettoyer`, calculée par Spark, pour les fichiers bruts `noms`."""
    from pyspark.sql import functions as F

    relu = spark.read.parquet(str(sortie)).where(F.col("fichier").isin(list(noms)))

    def texte(colonne: str):
        return F.coalesce(F.col(colonne).cast("string"), F.lit(""))

    debit = F.floor(F.col("vehicle_count") * ECHELLE_DEBIT + 0.5)
    occupation = F.floor(F.col("occupancy_pct") * ECHELLE_OCCUPATION + 0.5)
    canonique = F.concat_ws(
        "|", F.col("fichier"), texte("road_segment_id"), texte("label"), texte("hour_utc"), debit.cast("string"),
        F.coalesce(occupation.cast("string"), F.lit("")), texte("traffic_state"), texte("barrier_state"),
        texte("upstream_node_id"), texte("downstream_node_id"), texte("quality_flags"), texte("source_line"),
    )
    propre = relu.where(F.col("statut") == "propre").agg(
        F.count(F.lit(1)).alias("lignes"), F.sum(F.crc32(canonique)).alias("somme_crc"), F.sum(debit).alias("debit"),
        F.sum(occupation).alias("occupation"), F.count(F.col("occupancy_pct")).alias("occupations"),
    ).collect()[0]
    rejets_df = relu.where(F.col("statut") == "rejet")
    cle = F.concat(F.col("fichier"), F.lit("#"), F.col("source_line").cast("string"), F.lit("|"), F.col("regle"))
    rejet = rejets_df.agg(F.count(F.lit(1)).alias("lignes"), F.sum(F.crc32(cle)).alias("somme_crc")).collect()[0]
    par_regle = {r["regle"]: r["n"] for r in rejets_df.groupBy("regle").agg(F.count(F.lit(1)).alias("n")).collect()}
    return {
        "propres": {
            "lignes": propre["lignes"], "somme_crc": propre["somme_crc"] or 0, "debit_milliemes": propre["debit"] or 0,
            "occupation_cent_milliemes": propre["occupation"] or 0, "occupations": propre["occupations"],
        },
        "rejets": {"lignes": rejet["lignes"], "somme_crc": rejet["somme_crc"] or 0, "par_regle": dict(sorted(par_regle.items()))},
    }
