"""Source de METR-LA : où le prendre, quelle taille et quelle empreinte attendre, et comment contrôler le fichier.

Le jeu n'est pas dans le dépôt (`.gitignore`, `data/datasets/*`) : on le télécharge et on contrôle son **empreinte**. Un
fichier dont la taille ou l'empreinte diffère n'est jamais utilisé ; on ne « corrige » pas l'empreinte attendue sans
relire la fiche de provenance. Bibliothèque standard seulement.

Origine : fichier `metr-la.h5` diffusé par le dépôt DCRNN (https://github.com/liyaguang/DCRNN) dans un dossier Google Drive.
**Licence des données : non établie** (voir la fiche) : usage de recherche et d'évaluation, jamais redistribué.
"""

import hashlib
import shutil
import urllib.request
from pathlib import Path

from jeu_entrainement.simulation import RACINE

FICHIER = "metr-la.h5"
DOSSIER = RACINE / "data" / "datasets" / "metr-la"
IDENTIFIANT_DRIVE = "1pAGRfzMx6K9WWsfDcD1NMbIif0T0saFC"
URL = f"https://drive.usercontent.google.com/download?id={IDENTIFIANT_DRIVE}&export=download&confirm=t"
TAILLE_OCTETS = 57_038_056
SHA256 = "64784b76d6fb8ec9bff4b6decafb354da2bb37840468fdccee5044e511277c05"
DELAI_S = 60
BLOC = 1 << 20


class FichierRefuse(Exception):
    """Le fichier n'est pas celui que la fiche de provenance décrit."""


def empreinte(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        while bloc := f.read(BLOC):
            h.update(bloc)
    return h.hexdigest()


def verifier(chemin: Path | None = None) -> Path:
    """Rend le chemin si taille et empreinte sont celles de la fiche ; sinon `FichierRefuse` (message clair, rien n'est lu)."""
    chemin = chemin or DOSSIER / FICHIER
    if not chemin.is_file():
        raise FichierRefuse(f"{chemin} est absent : python3 scripts/dev/dev.py ml-prevision telecharger (Windows : py -3 ...)")
    if chemin.stat().st_size != TAILLE_OCTETS:
        raise FichierRefuse(f"{chemin} : {chemin.stat().st_size} octets, {TAILLE_OCTETS} attendus (téléchargement incomplet ou fichier changé)")
    lu = empreinte(chemin)
    if lu != SHA256:
        raise FichierRefuse(f"{chemin} : SHA-256 {lu} au lieu de {SHA256} (fichier changé : relire la fiche avant de continuer)")
    return chemin


def telecharger(dossier: Path | None = None, *, url: str = URL, ouvrir=urllib.request.urlopen) -> Path:
    """Télécharge `metr-la.h5` dans `dossier`, le contrôle, et rend son chemin. Un fichier déjà conforme n'est pas retéléchargé.

    Le fichier est écrit sous un nom temporaire puis renommé : un téléchargement interrompu ou refusé ne laisse jamais un
    fichier qui ressemble au jeu.
    """
    dossier = dossier or DOSSIER
    cible = dossier / FICHIER
    if cible.is_file():
        try:
            return verifier(cible)
        except FichierRefuse:
            pass  # fichier inattendu : on le retélécharge sous un nom temporaire, l'ancien reste jusqu'au contrôle
    dossier.mkdir(parents=True, exist_ok=True)
    temporaire = cible.with_suffix(".h5.partiel")
    try:
        with ouvrir(url, timeout=DELAI_S) as reponse, temporaire.open("wb") as sortie:
            shutil.copyfileobj(reponse, sortie, BLOC)
        verifier(temporaire)
    except BaseException:
        temporaire.unlink(missing_ok=True)
        raise
    temporaire.replace(cible)
    return cible
