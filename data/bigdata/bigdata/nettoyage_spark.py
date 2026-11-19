"""Le nettoyage du comptage de Paris (DAT-04) en PySpark : les sept règles de `transforms.paris_qualite`, en colonnes.

Même entrée (les fichiers CSV bruts), mêmes règles, même ordre (la **première** règle violée l'emporte), même
déduplication (par fichier, le premier de chaque (iu_ac, t_1h) est gardé). La sortie est du Parquet, partitionné par
statut (`statut=propre`, `statut=rejet`), écrit en un seul passage sur les données.

Ce que ce port **reproduit** : les décisions (quelle ligne est propre, quelle règle refuse les autres) et les valeurs des
lignes propres. Ce qu'il **ne reproduit pas** : le texte du motif de refus, la ligne brute complète des rejets (un extrait
suffit à les retrouver), la normalisation Unicode NFC, les espaces autres que ceux de l'ASCII, et les formes d'horodatage
que Python accepte en plus du format du portail (`AAAA-MM-JJThh:mm:ss` suivi de `Z` ou d'un décalage `±hh:mm`).

Le numéro de ligne vient de la position dans le fichier : chaque fichier est lu en **une** partition (`ouvrir_session`
l'impose), le numéro est donc l'indice de la ligne dans sa partition.
"""

import re
import time
from datetime import UTC, datetime
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

ETATS = ("Inconnu", "Fluide", "Pré-saturé", "Saturé", "Bloqué")
BARRES = ("Inconnu", "Ouvert", "Barré", "Invalide")
BANDES = ETATS[1:]
SEUILS = (15.0, 30.0, 50.0)
DEBIT_MAX = 15_000.0
OCCUPATION_MAX = 100.0
CALENDRIER_DEBUT = datetime(2012, 1, 1, tzinfo=UTC)
CALENDRIER_FIN = datetime(2031, 1, 1, tzinfo=UTC)
TOLERANCE_FUTUR_S = 5
NOMBRE = r"^[+-]?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$"
ENTIER = r"^[0-9]{1,9}$"
INSTANT = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(Z|[+-][0-9]{2}:[0-9]{2})$"
DATE = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
FORMAT_INSTANT = "yyyy-MM-dd'T'HH:mm:ssXXX"
COLONNES_BRUTES = (
    "iu_ac", "libelle", "t_1h", "q", "k", "etat_trafic", "iu_nd_amont", "libelle_nd_amont", "iu_nd_aval",
    "libelle_nd_aval", "etat_barre", "date_debut", "date_fin", "geo_point_2d", "geo_shape",
)
OCTETS_MAX_PAR_FICHIER = "4g"


def ouvrir_session(coeurs: int, memoire: str = "3g", dossier_temporaire: str | None = None) -> SparkSession:
    """Spark en mode local sur `coeurs` cœurs (maître `local[N]`, l'équivalent d'un cluster d'un seul nœud).

    Un fichier = une partition : sans cela, Spark regroupe plusieurs petits fichiers dans une même partition et le numéro
    de ligne ne se déduirait plus de la position. L'interface web, inutile ici, est coupée ; le fuseau est UTC ; le mode
    ANSI est coupé pour qu'une valeur illisible donne `null` (comme `None` en Python) au lieu d'arrêter le travail.
    """
    constructeur = (
        SparkSession.builder.master(f"local[{coeurs}]").appName("novaria-bigdata")
        .config("spark.driver.memory", memoire)
        .config("spark.ui.enabled", "false")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.ansi.enabled", "false")
        .config("spark.sql.shuffle.partitions", str(max(2, coeurs * 2)))
        .config("spark.sql.files.maxPartitionBytes", OCTETS_MAX_PAR_FICHIER)
        .config("spark.sql.files.openCostInBytes", OCTETS_MAX_PAR_FICHIER)
        .config("spark.sql.parquet.compression.codec", "snappy")
    )
    if dossier_temporaire:
        constructeur = constructeur.config("spark.local.dir", dossier_temporaire)
    return constructeur.getOrCreate()


def _texte(colonne: str):
    """`_texte` de `paris_qualite` : valeur absente = vide, espaces de tête et de queue retirés."""
    return F.regexp_replace(F.coalesce(F.col(colonne), F.lit("")), r"^\s+|\s+$", "")


def _nombre(texte):
    """`_nombre` : nombre fini ou `null` (la forme est contrôlée avant la conversion)."""
    valeur = F.when(texte.rlike(NOMBRE), texte.cast("double"))
    return F.when(valeur.isNotNull() & ~F.isnan(valeur) & (F.abs(valeur) != F.lit(float("inf"))), valeur)


def _instant(texte):
    """`_instant` : horodatage avec fuseau, ramené en UTC (`null` si la forme n'est pas celle du portail)."""
    return F.when(texte.rlike(INSTANT), F.try_to_timestamp(texte, F.lit(FORMAT_INSTANT)))


def _date_valide(texte):
    return texte.rlike(DATE) & F.try_to_timestamp(texte, F.lit("yyyy-MM-dd")).isNotNull()


def _etat(texte, liste: tuple[str, ...]):
    """`_etat` : le nom de l'état, ou son rang entier (0 = Inconnu) ; `null` si ni l'un ni l'autre."""
    rang = F.when(texte.rlike(r"^[0-9]+$"), texte.cast("long"))
    valeurs = F.array(*[F.lit(v) for v in liste])
    return (
        F.when(texte.isin(*liste), texte)
        .when(rang.isNotNull() & (rang < len(liste)), F.element_at(valeurs, (rang + 1).cast("int")))
    )


def colonnes_derivees(texte: dict) -> dict:
    """Les valeurs typées tirées des colonnes de texte, calculées une fois et réutilisées par les règles et la sortie."""
    return {
        "instant": _instant(texte["t_1h"]), "debit": _nombre(texte["q"]), "occupation": _nombre(texte["k"]),
        "etat": _etat(texte["etat_trafic"], ETATS), "barre": _etat(texte["etat_barre"], BARRES),
    }


def regle_violee(c: dict, texte: dict, maintenant: datetime):
    """La première règle violée (`MISSING_REQUIRED`, `TYPE_INVALID`, `OUT_OF_RANGE`, `NOT_ON_THE_HOUR`, `FUTURE_TIMESTAMP`,
    `STATE_MISMATCH`) ou `null`, dans l'ordre de `paris_qualite.REGLES`. `texte` : les colonnes brutes déjà nettoyées."""
    manquant = (texte["iu_ac"] == "") | (texte["t_1h"] == "") | (texte["q"] == "")
    type_invalide = (
        ((texte["iu_ac"] != "") & ~texte["iu_ac"].rlike(ENTIER))
        | ((texte["t_1h"] != "") & c["instant"].isNull())
        | ((texte["q"] != "") & c["debit"].isNull())
        | ((texte["k"] != "") & c["occupation"].isNull())
        | ((texte["date_debut"] != "") & ~_date_valide(texte["date_debut"]))
        | ((texte["date_fin"] != "") & ~_date_valide(texte["date_fin"]))
        | ((texte["etat_trafic"] != "") & c["etat"].isNull())
        | ((texte["etat_barre"] != "") & c["barre"].isNull())
    )
    debut = F.lit(CALENDRIER_DEBUT.timestamp()).cast("timestamp")
    fin = F.lit(CALENDRIER_FIN.timestamp()).cast("timestamp")
    hors_bornes = (
        (c["debit"].isNotNull() & ~((c["debit"] >= 0) & (c["debit"] <= DEBIT_MAX)))
        | (c["occupation"].isNotNull() & ~((c["occupation"] >= 0) & (c["occupation"] <= OCCUPATION_MAX)))
        | (c["instant"].isNotNull() & ~((c["instant"] >= debut) & (c["instant"] < fin)))
    )
    pas_pleine = c["instant"].isNotNull() & ((F.minute(c["instant"]) != 0) | (F.second(c["instant"]) != 0))
    futur = c["instant"].isNotNull() & (F.unix_timestamp(c["instant"]) > F.lit(int(maintenant.timestamp()) + TOLERANCE_FUTUR_S))

    k = c["occupation"]
    rang = (k >= SEUILS[0]).cast("int") + (k >= SEUILS[1]).cast("int") + (k >= SEUILS[2]).cast("int")
    bandes = F.array(*[F.lit(b) for b in BANDES])
    attendu = F.element_at(bandes, rang + 1)
    voisin = F.element_at(bandes, F.greatest(rang, F.lit(1)))  # la bande d'en dessous ; sans effet hors d'un seuil exact
    sur_un_seuil = k.isin(*SEUILS)
    etat_connu = (texte["etat_trafic"] != "") & c["etat"].isNotNull()
    incoherent = etat_connu & F.when(
        k.isNull(), (texte["k"] == "") & (c["etat"] != "Inconnu")
    ).otherwise((c["etat"] == "Inconnu") | ~((c["etat"] == attendu) | (sur_un_seuil & (c["etat"] == voisin))))
    return (
        F.when(manquant, "MISSING_REQUIRED").when(type_invalide, "TYPE_INVALID").when(hors_bornes, "OUT_OF_RANGE")
        .when(pas_pleine, "NOT_ON_THE_HOUR").when(futur, "FUTURE_TIMESTAMP").when(incoherent, "STATE_MISMATCH")
    )


def classer(brut: DataFrame, maintenant: datetime) -> DataFrame:
    """Une ligne par ligne brute : `statut` (propre ou rejet), `regle`, et les colonnes propres (ou l'extrait des rejets).

    Les colonnes de texte nettoyées, puis les colonnes typées, sont **matérialisées** par des projections successives, et
    les règles ne les référencent que par leur nom. Écrites en une seule expression imbriquée, les mêmes règles
    recopient les mêmes sous-expressions des dizaines de fois : le code généré dépasse la limite de la machine virtuelle
    et Spark retombe sur une évaluation interprétée, bien plus lente (constaté pendant la mise au point).
    """
    lu = brut.select(
        F.col("_metadata.file_name").alias("fichier"),
        (F.monotonically_increasing_id() - F.shiftleft(F.spark_partition_id().cast("long"), 33) + 1).alias("ligne"),
        *[F.col(nom) for nom in COLONNES_BRUTES],
    )
    nettoye = lu.select("fichier", "ligne", *[_texte(nom).alias(nom) for nom in COLONNES_BRUTES])
    texte = {nom: F.col(nom) for nom in COLONNES_BRUTES}
    derivees = colonnes_derivees(texte)
    typees = nettoye.select("*", *[expression.alias(f"_{nom}") for nom, expression in derivees.items()])
    c = {nom: F.col(f"_{nom}") for nom in derivees}
    base = typees.select(
        "fichier", "ligne",
        regle_violee(c, texte, maintenant).alias("regle_ligne"),
        texte["iu_ac"].cast("long").cast("string").alias("road_segment_id"),
        texte["libelle"].alias("label"),
        c["instant"].alias("heure"),
        c["debit"].alias("vehicle_count"),
        c["occupation"].alias("occupancy_pct"),
        F.when(texte["etat_trafic"] != "", c["etat"]).alias("traffic_state"),
        F.when(texte["etat_barre"] != "", c["barre"]).alias("barrier_state"),
        texte["iu_nd_amont"].alias("upstream_node_id"),
        texte["iu_nd_aval"].alias("downstream_node_id"),
        F.concat_ws(";", texte["iu_ac"], texte["t_1h"], texte["q"], texte["k"]).alias("extrait"),
    )
    # Doublon : parmi les lignes sans autre défaut, le premier (iu_ac, t_1h) d'un fichier est gardé. Une ligne déjà refusée
    # a sa propre clé : elle ne compte pas comme « première » et ne fait pas d'un partage de clé un nœud surchargé.
    cle = F.when(
        F.col("regle_ligne").isNull(),
        F.concat_ws("|", F.col("fichier"), F.col("road_segment_id"), F.unix_timestamp(F.col("heure")).cast("string")),
    ).otherwise(F.concat_ws("#", F.col("fichier"), F.col("ligne").cast("string")))
    rang_dans_la_cle = F.row_number().over(Window.partitionBy(cle).orderBy("ligne"))
    avec_rang = base.withColumn("rang", rang_dans_la_cle)
    regle = F.coalesce(F.col("regle_ligne"), F.when(F.col("rang") > 1, F.lit("DUPLICATE_KEY")))
    propre = regle.isNull()
    return avec_rang.select(
        F.when(propre, "propre").otherwise("rejet").alias("statut"),
        "fichier",
        F.col("ligne").alias("source_line"),
        regle.alias("regle"),
        F.when(propre, F.col("road_segment_id")).alias("road_segment_id"),
        F.when(propre, F.col("label")).alias("label"),
        F.when(propre, F.date_format("heure", "yyyy-MM-dd'T'HH:mm:ss'Z'")).alias("hour_utc"),
        F.when(propre, F.col("vehicle_count")).alias("vehicle_count"),
        F.when(propre, F.col("occupancy_pct")).alias("occupancy_pct"),
        F.when(propre, F.col("traffic_state")).alias("traffic_state"),
        F.when(propre, F.col("barrier_state")).alias("barrier_state"),
        F.when(propre, F.col("upstream_node_id")).alias("upstream_node_id"),
        F.when(propre, F.col("downstream_node_id")).alias("downstream_node_id"),
        F.when(propre, F.when(F.col("occupancy_pct").isNull(), F.lit("MISSING_OCCUPANCY")).otherwise(F.lit(""))).alias("quality_flags"),
        F.when(~propre, F.col("extrait")).alias("extrait"),
    )


def lire(spark: SparkSession, motif: str) -> DataFrame:
    """Les fichiers bruts (un motif de chemins) en colonnes de texte ; la BOM du premier nom de colonne est retirée."""
    brut = (
        spark.read.option("header", True).option("sep", ";").option("quote", '"').option("escape", '"')
        .option("encoding", "UTF-8").option("multiLine", False).option("inferSchema", False).csv(motif)
    )
    return brut.toDF(*[nom.lstrip("﻿") for nom in brut.columns])


def nettoyer(spark: SparkSession, motif: str, sortie: Path, maintenant: datetime) -> dict:
    """Nettoie tous les fichiers du motif et écrit le résultat dans `sortie` ; rend le bilan (forme de `Bilan.en_dict`)."""
    debut = time.perf_counter()
    classe = classer(lire(spark, motif), maintenant)
    classe.write.mode("overwrite").partitionBy("statut").parquet(str(sortie))
    ecriture = time.perf_counter() - debut
    resultat = bilan(spark, sortie)
    resultat["seconds_job"] = round(ecriture, 3)
    return resultat


def bilan(spark: SparkSession, sortie: Path) -> dict:
    """Le bilan relu dans ce qui a été écrit : lues = propres + rejetées, et chaque rejet porte une règle."""
    relu = spark.read.parquet(str(sortie))
    lignes = {(r["statut"], r["regle"]): r["n"] for r in relu.groupBy("statut", "regle").agg(F.count(F.lit(1)).alias("n")).collect()}
    propres = sum(n for (statut, _), n in lignes.items() if statut == "propre")
    par_regle = {regle: n for (statut, regle), n in lignes.items() if statut == "rejet"}
    drapeaux = relu.where(F.col("quality_flags") == "MISSING_OCCUPANCY").count()
    return {
        "rows_read": propres + sum(par_regle.values()), "rows_clean": propres, "rows_rejected": sum(par_regle.values()),
        "by_rule": dict(sorted(par_regle.items())), "flags": {"MISSING_OCCUPANCY": drapeaux} if drapeaux else {},
    }
