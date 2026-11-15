"""Port `ObjectStore` et son adaptateur local (ADR-025, `STORAGE_BACKEND=local`) : des octets rangés sous des clés.

Le port a quatre opérations, celles d'un compartiment S3 dont le projet a besoin : écrire (`put`), lire (`get`),
tester (`exists`) et lister par préfixe (`list`). Le code métier n'importe aucun SDK de cloud : le jour où AWS sera
autorisé, un adaptateur de plus derrière ce port suffira (et le test `tests/test_absence_sdk_aws.py` devra alors
nommer sa seule exception).

Les clés sont des chemins relatifs stricts (`<run_id>/modele.json`) : segments en minuscules, chiffres, point, tiret,
souligné, sans `..`, sans chemin absolu. Les majuscules ne sont permises que sur demande (`majuscules=True`, pour les
fichiers d'un jeu de données comme `PROVENANCE.md`) : sur un système de fichiers qui ignore la casse, `A/b` et `a/b`
seraient le même objet. Une clé écrite **n'est jamais réécrite** (un objet versionné est immuable) ;
seul le pointeur « en service » se remplace, par un échange atomique.
"""

import hashlib
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

CLE = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}(/[a-z0-9][a-z0-9._-]{0,99}){0,3}")
CLE_AVEC_MAJUSCULES = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}(/[A-Za-z0-9][A-Za-z0-9._-]{0,99}){0,3}")
PREFIXE = re.compile(r"[A-Za-z0-9._/-]{0,400}")
PROFONDEUR_MAX = 4  # segments d'une clé : au-delà, `list` ne descend pas
TAILLE_MAX = 16 * 1024 * 1024  # un modèle de ce dépôt tient en quelques ko ; au-delà, c'est une erreur ou une attaque
TAILLE_MAX_JEU = 256 * 1024 * 1024  # un fichier Parquet du jeu v1 pèse une dizaine de Mo
LISTE_MAX = 10_000  # nombre de clés rendu par `list` ; au-delà, le préfixe est trop large
BACKEND_LOCAL = "local"


class StockageErreur(RuntimeError):
    pass


class ObjetAbsent(StockageErreur):
    pass


class ObjetDejaEcrit(StockageErreur):
    pass


class StockageNonConfigure(StockageErreur):
    """`STORAGE_BACKEND` nomme un adaptateur qui n'existe pas (S3 est documenté, non exécuté)."""


class ObjectStore(Protocol):
    def put(self, cle: str, octets: bytes, *, remplacer: bool = False) -> str: ...
    def get(self, cle: str) -> bytes: ...
    def exists(self, cle: str) -> bool: ...
    def list(self, prefixe: str = "") -> list[str]: ...


def sha256(octets: bytes) -> str:
    return hashlib.sha256(octets).hexdigest()


def verifier_la_cle(cle: str, *, majuscules: bool = False) -> str:
    modele = CLE_AVEC_MAJUSCULES if majuscules else CLE
    if not isinstance(cle, str) or not modele.fullmatch(cle):  # chaque segment commence par une lettre ou un chiffre : jamais « .. »
        raise StockageErreur(f"clé de stockage invalide : {cle!r}")
    return cle


class StockageLocal:
    """Un dossier : jamais de chemin hors de lui, écriture atomique, fichiers en lecture seule."""

    def __init__(self, racine: Path, *, taille_max: int = TAILLE_MAX, majuscules: bool = False) -> None:
        self.racine = Path(racine)
        self.taille_max = taille_max
        self.majuscules = majuscules

    def _chemin(self, cle: str) -> Path:
        racine = self.racine.resolve()
        chemin = (racine / verifier_la_cle(cle, majuscules=self.majuscules)).resolve()
        if not chemin.is_relative_to(racine):
            raise StockageErreur(f"clé de stockage hors du magasin : {cle!r}")
        return chemin

    def put(self, cle: str, octets: bytes, *, remplacer: bool = False) -> str:
        """Écrit les octets ; rend leur SHA-256. Refuse de réécrire une clé, sauf `remplacer` (le pointeur seulement)."""
        if len(octets) > self.taille_max:
            raise StockageErreur(f"objet trop gros : {len(octets)} octets (maximum {self.taille_max})")
        chemin = self._chemin(cle)
        if chemin.exists() and not remplacer:
            raise ObjetDejaEcrit(f"{cle} existe déjà : un objet versionné ne se réécrit pas")
        chemin.parent.mkdir(parents=True, exist_ok=True)
        descripteur, temporaire = tempfile.mkstemp(dir=chemin.parent, prefix=".ecriture-")
        try:
            with os.fdopen(descripteur, "wb") as fichier:
                fichier.write(octets)
                fichier.flush()
                os.fsync(fichier.fileno())
            os.chmod(temporaire, 0o644 if remplacer else 0o444)  # le pointeur se remplace ; un objet versionné ne se réécrit pas
            if remplacer:
                os.replace(temporaire, chemin)
            else:
                os.link(temporaire, chemin)  # échoue si le fichier est apparu entre-temps : jamais d'écrasement
                os.unlink(temporaire)
        except FileExistsError as erreur:
            raise ObjetDejaEcrit(f"{cle} existe déjà : un objet versionné ne se réécrit pas") from erreur
        finally:
            if os.path.exists(temporaire):
                os.unlink(temporaire)
        return sha256(octets)

    def get(self, cle: str) -> bytes:
        chemin = self._chemin(cle)
        if not chemin.is_file():
            raise ObjetAbsent(f"{cle} est absent du magasin")
        if chemin.stat().st_size > self.taille_max:
            raise StockageErreur(f"{cle} dépasse la taille maximale")
        return chemin.read_bytes()

    def exists(self, cle: str) -> bool:
        return self._chemin(cle).is_file()

    def list(self, prefixe: str = "") -> list[str]:
        """Les clés qui commencent par `prefixe`, triées (comme `ListObjectsV2` de S3). Les liens symboliques et les
        fichiers d'écriture en cours sont ignorés : ce que `list` rend, `get` le lit."""
        if not isinstance(prefixe, str) or not PREFIXE.fullmatch(prefixe) or ".." in prefixe or prefixe.startswith("/") or "//" in prefixe:
            raise StockageErreur(f"préfixe de stockage invalide : {prefixe!r}")
        racine = self.racine.resolve()
        if not racine.is_dir():
            return []
        modele = CLE_AVEC_MAJUSCULES if self.majuscules else CLE
        cles: list[str] = []
        for dossier, sous_dossiers, fichiers in os.walk(racine):  # ne suit pas les liens symboliques de dossier
            parties = Path(dossier).relative_to(racine).parts
            if len(parties) >= PROFONDEUR_MAX - 1:
                sous_dossiers.clear()
            for nom in fichiers:
                cle = "/".join((*parties, nom))
                if cle.startswith(prefixe) and modele.fullmatch(cle) and not os.path.islink(os.path.join(dossier, nom)):
                    cles.append(cle)
                    if len(cles) > LISTE_MAX:
                        raise StockageErreur(f"plus de {LISTE_MAX} objets pour le préfixe {prefixe!r} : le préciser")
        return sorted(cles)


def ouvrir_magasin(
    racine: Path, environ: Mapping[str, str] | None = None, *, taille_max: int = TAILLE_MAX, majuscules: bool = False
) -> ObjectStore:
    """Le magasin choisi par `STORAGE_BACKEND` (« local » par défaut). Un autre nom est une erreur de configuration."""
    environnement = os.environ if environ is None else environ
    if environnement.get("STORAGE_BACKEND", BACKEND_LOCAL) != BACKEND_LOCAL:
        raise StockageNonConfigure("STORAGE_BACKEND : seul « local » existe ; S3 est documenté, non exécuté (ADR-025)")
    return StockageLocal(racine, taille_max=taille_max, majuscules=majuscules)


def ouvrir_magasin_de_jeu(dossier: Path, environ: Mapping[str, str] | None = None) -> ObjectStore:
    """Le magasin d'un jeu de données (un dossier) : fichiers Parquet de plusieurs Mo, `manifest.json`, `PROVENANCE.md`."""
    return ouvrir_magasin(dossier, environ, taille_max=TAILLE_MAX_JEU, majuscules=True)


def ranger_a_l_identique(magasin: ObjectStore, cle: str, octets: bytes) -> str:
    """Écrit un objet versionné ; si la clé existe déjà avec **les mêmes octets**, rien ne change (reconstruire un jeu
    déterministe est sans effet). Des octets différents sont refusés : une version ne se réécrit pas, on en crée une autre."""
    if magasin.exists(cle):
        if magasin.get(cle) != octets:
            raise ObjetDejaEcrit(f"{cle} existe déjà avec un autre contenu : supprimer le dossier ou créer une nouvelle version")
        return sha256(octets)
    return magasin.put(cle, octets)
