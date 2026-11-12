"""Port `ObjectStore` et son adaptateur local (ADR-025, `STORAGE_BACKEND=local`) : des octets rangés sous des clés.

Les clés sont des chemins relatifs stricts (`<run_id>/modele.json`) : segments en minuscules, chiffres, point, tiret,
souligné, sans `..`, sans chemin absolu. Une clé écrite **n'est jamais réécrite** (un modèle versionné est immuable) ;
seul le pointeur « en service » se remplace, par un échange atomique.
"""

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

CLE = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}(/[a-z0-9][a-z0-9._-]{0,99}){0,3}")
TAILLE_MAX = 16 * 1024 * 1024  # un modèle de ce dépôt tient en quelques ko ; au-delà, c'est une erreur ou une attaque


class StockageErreur(RuntimeError):
    pass


class ObjetAbsent(StockageErreur):
    pass


class ObjetDejaEcrit(StockageErreur):
    pass


class ObjectStore(Protocol):
    def put(self, cle: str, octets: bytes, *, remplacer: bool = False) -> str: ...
    def get(self, cle: str) -> bytes: ...
    def exists(self, cle: str) -> bool: ...


def sha256(octets: bytes) -> str:
    return hashlib.sha256(octets).hexdigest()


def verifier_la_cle(cle: str) -> str:
    if not isinstance(cle, str) or not CLE.fullmatch(cle):  # chaque segment commence par une lettre ou un chiffre : jamais « .. »
        raise StockageErreur(f"clé de stockage invalide : {cle!r}")
    return cle


class StockageLocal:
    """Un dossier (`var/models/`) : jamais de chemin hors de lui, écriture atomique, fichiers en lecture seule."""

    def __init__(self, racine: Path) -> None:
        self.racine = Path(racine)

    def _chemin(self, cle: str) -> Path:
        racine = self.racine.resolve()
        chemin = (racine / verifier_la_cle(cle)).resolve()
        if not chemin.is_relative_to(racine):
            raise StockageErreur(f"clé de stockage hors du magasin : {cle!r}")
        return chemin

    def put(self, cle: str, octets: bytes, *, remplacer: bool = False) -> str:
        """Écrit les octets ; rend leur SHA-256. Refuse de réécrire une clé, sauf `remplacer` (le pointeur seulement)."""
        if len(octets) > TAILLE_MAX:
            raise StockageErreur(f"objet trop gros : {len(octets)} octets (maximum {TAILLE_MAX})")
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
            os.chmod(temporaire, 0o644 if remplacer else 0o444)  # le pointeur se remplace ; un modèle ne se réécrit pas
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
        if chemin.stat().st_size > TAILLE_MAX:
            raise StockageErreur(f"{cle} dépasse la taille maximale")
        return chemin.read_bytes()

    def exists(self, cle: str) -> bool:
        return self._chemin(cle).is_file()
