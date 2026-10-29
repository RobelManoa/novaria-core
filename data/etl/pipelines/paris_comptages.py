"""Source « comptage routier de la Ville de Paris » (capteurs permanents) : adresse d'export, téléchargement, contrôle de forme.

Bibliothèque standard uniquement. Les octets reçus sont conservés tels quels : rien n'est converti ni corrigé ici
(le nettoyage relève de DAT-04). Jeu retenu, licence et schéma : data/datasets/README.md (DAT-01).
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

DATASET_ID = "paris-comptages-routiers"
SOURCE_TYPE = "REAL_HISTORICAL"
LICENCE = "ODbL"
HOTE = "opendata.paris.fr"
ADRESSE_JEU = f"https://{HOTE}/api/explore/v2.1/catalog/datasets/comptages-routiers-permanents"
AGENT = "novaria-core-etl/0.1 (projet de master, DAT-03)"

# En-tête du fichier d'export, dans l'ordre du portail. Un autre en-tête signifie que la source a changé : on s'arrête.
COLONNES = (
    "iu_ac", "libelle", "t_1h", "q", "k", "etat_trafic", "iu_nd_amont", "libelle_nd_amont", "iu_nd_aval",
    "libelle_nd_aval", "etat_barre", "date_debut", "date_fin", "geo_point_2d", "geo_shape",
)

# Une fenêtre = environ 71 000 lignes et 24 Mo par jour. Au-delà de 7 jours, relancer fenêtre par fenêtre.
FENETRE_MAX = timedelta(days=7)
TAILLE_MAX = 512 * 1024 * 1024
BLOC = 1024 * 1024
DELAI_S = 120

Ouvrir = Callable[[urllib.request.Request, int], BinaryIO]


class ErreurSource(Exception):
    """La source répond autrement que prévu (adresse, forme, taille, réseau)."""


def ouvrir_par_defaut(requete: urllib.request.Request, delai: int) -> BinaryIO:
    # L'adresse a été vérifiée (https, hôte du portail) avant d'arriver ici.
    return urllib.request.urlopen(requete, timeout=delai)  # noqa: S310


def fenetre_du_jour(jour: date) -> tuple[datetime, datetime]:
    """Le jour entier en UTC : de 00:00 inclus au lendemain 00:00 exclu."""
    debut = datetime(jour.year, jour.month, jour.day, tzinfo=UTC)
    return debut, debut + timedelta(days=1)


def verifier_fenetre(debut: datetime, fin: datetime) -> tuple[datetime, datetime]:
    """Contrôle les bornes (avec fuseau, début avant fin, au plus FENETRE_MAX) et les ramène en UTC."""
    if debut.tzinfo is None or fin.tzinfo is None:
        raise ValueError("Les bornes de la fenêtre doivent porter un fuseau (exemple : 2026-10-18T00:00:00Z).")
    debut, fin = debut.astimezone(UTC), fin.astimezone(UTC)
    if fin <= debut:
        raise ValueError("La fin de la fenêtre doit suivre son début.")
    if fin - debut > FENETRE_MAX:
        raise ValueError(f"Fenêtre trop longue ({fin - debut}) : {FENETRE_MAX.days} jours au plus, par fenêtres successives.")
    return debut, fin


def instant(valeur: datetime) -> str:
    return valeur.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def adresse_export(debut: datetime, fin: datetime) -> str:
    """Adresse de l'export CSV des lignes dont `t_1h` est dans [début, fin[.

    Le tri (heure, tronçon) rend l'export identique d'un appel à l'autre tant que le portail ne change pas ses
    données : c'est ce qui permet de reconnaître un fichier déjà reçu par son empreinte.
    """
    parametres = {
        "where": f"t_1h >= date'{instant(debut)}' AND t_1h < date'{instant(fin)}'",
        "order_by": "t_1h, iu_ac",
        "delimiter": ";",
        "limit": "-1",
    }
    return f"{ADRESSE_JEU}/exports/csv?{urllib.parse.urlencode(parametres, quote_via=urllib.parse.quote)}"


@dataclass(frozen=True)
class Telechargement:
    chemin: Path
    sha256: str
    octets: int


def _verifier_adresse(adresse: str) -> None:
    morceaux = urllib.parse.urlsplit(adresse)
    if morceaux.scheme != "https" or morceaux.hostname != HOTE:
        raise ErreurSource(f"Adresse refusée (https vers {HOTE} seulement) : {morceaux.scheme}://{morceaux.hostname}")


def telecharger(adresse: str, dossier: Path, *, ouvrir: Ouvrir = ouvrir_par_defaut, taille_max: int = TAILLE_MAX) -> Telechargement:
    """Reçoit le fichier par blocs dans un fichier provisoire de `dossier`, en calculant son SHA-256 au passage.

    Les octets sont écrits tels que reçus. En cas d'échec, le fichier provisoire est supprimé.
    """
    _verifier_adresse(adresse)
    requete = urllib.request.Request(adresse, headers={"User-Agent": AGENT, "Accept-Encoding": "identity"})  # noqa: S310
    dossier.mkdir(parents=True, exist_ok=True)
    descripteur, nom = tempfile.mkstemp(prefix="telechargement-", suffix=".part", dir=dossier)
    chemin = Path(nom)
    empreinte = hashlib.sha256()
    octets = 0
    try:
        with os.fdopen(descripteur, "wb") as sortie, ouvrir(requete, DELAI_S) as flux:
            while bloc := flux.read(BLOC):
                octets += len(bloc)
                if octets > taille_max:
                    raise ErreurSource(f"Fichier plus gros que {taille_max} octets : téléchargement interrompu.")
                empreinte.update(bloc)
                sortie.write(bloc)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as erreur:
        chemin.unlink(missing_ok=True)
        raise ErreurSource(f"Téléchargement impossible ({erreur}).") from erreur
    except BaseException:
        chemin.unlink(missing_ok=True)
        raise
    return Telechargement(chemin, empreinte.hexdigest(), octets)


def analyser(chemin: Path) -> int:
    """Contrôle la forme du fichier et rend son nombre de lignes de données (hors en-tête).

    Refus : en-tête différent de COLONNES, ligne au nombre de colonnes différent, texte illisible, aucune ligne.
    Aucune valeur n'est interprétée : q et k vides, états en texte, etc. sont des cas du nettoyage (DAT-04).
    """
    try:
        with chemin.open(encoding="utf-8-sig", newline="") as fichier:
            lecteur = csv.reader(fichier, delimiter=";")
            entete = next(lecteur, None)
            if entete is None or tuple(entete) != COLONNES:
                raise ErreurSource(f"En-tête inattendu : la source a changé de format ({entete}).")
            lignes = 0
            for numero, ligne in enumerate(lecteur, start=1):
                if len(ligne) != len(COLONNES):
                    raise ErreurSource(f"Ligne de données {numero} : {len(ligne)} colonnes au lieu de {len(COLONNES)}.")
                lignes += 1
    except (UnicodeDecodeError, csv.Error) as erreur:
        raise ErreurSource(f"Fichier illisible comme CSV UTF-8 ({erreur}).") from erreur
    if lignes == 0:
        raise ErreurSource("Aucune ligne de données pour cette fenêtre : rien n'est conservé.")
    return lignes


def sha256_du_fichier(chemin: Path) -> str:
    empreinte = hashlib.sha256()
    with chemin.open("rb") as fichier:
        while bloc := fichier.read(BLOC):
            empreinte.update(bloc)
    return empreinte.hexdigest()


def date_de_modification_source(*, ouvrir: Ouvrir = ouvrir_par_defaut) -> datetime | None:
    """Date de dernière mise à jour des données annoncée par le portail ; None si elle est indisponible.

    Information facultative : elle explique pourquoi une même fenêtre peut changer d'empreinte d'un jour à l'autre.
    """
    requete = urllib.request.Request(ADRESSE_JEU, headers={"User-Agent": AGENT, "Accept-Encoding": "identity"})  # noqa: S310
    try:
        with ouvrir(requete, DELAI_S) as flux:
            octets = flux.read(8 * BLOC)
        if octets[:2] == b"\x1f\x8b":  # le portail compresse ses métadonnées même quand on ne le demande pas
            octets = gzip.decompress(octets)
        modifiee = datetime.fromisoformat(json.loads(octets)["metas"]["default"]["data_processed"])
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, EOFError, ValueError, KeyError, TypeError):
        return None
    return modifiee.astimezone(UTC) if modifiee.tzinfo else None
