"""Dépôt du rapport : le PDF, puis ses métadonnées en dernier, et une notification simulée.

L'API (`services/traitement`) ne liste un rapport que si ses métadonnées sont valides et si son PDF est
là : écrire le PDF d'abord garantit qu'un rapport listé est téléchargeable. Un même rapport (même
période) garde le même identifiant : relancer le robot le remplace, il ne le duplique pas (ADR-019).
"""

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rapport.periode import Periode

ESPACE_NOMS = uuid.UUID("6f3c1c0e-6d3a-4a43-9a54-3a4a5a7c0b11")  # espace d'identifiants des rapports Novaria
NOM_NOTIFICATIONS = "notifications.log"


@dataclass(frozen=True)
class Depot:
    identifiant: uuid.UUID
    chemin_pdf: Path
    chemin_metadonnees: Path
    metadonnees: dict
    remplace: bool


def identifiant(periode: Periode) -> uuid.UUID:
    return uuid.uuid5(ESPACE_NOMS, f"rapport-hebdomadaire:{periode.api(periode.debut)}:{periode.api(periode.fin)}")


def nom_de_fichier(periode: Periode) -> str:
    nom = f"rapport-hebdomadaire-{periode.etiquette}.pdf"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,199}", nom):
        raise ValueError(f"nom de fichier refusé : {nom}")
    return nom


def _ecrire(chemin: Path, contenu: bytes) -> None:
    """Écriture atomique : fichier temporaire du même dossier, puis renommage."""
    descripteur, temporaire = tempfile.mkstemp(dir=chemin.parent, prefix=".depot-")
    try:
        with os.fdopen(descripteur, "wb") as fichier:
            fichier.write(contenu)
        os.chmod(temporaire, 0o644)  # `mkstemp` crée en 0600 : le service de lecture, un autre compte, doit lire
        os.replace(temporaire, chemin)
    except BaseException:
        Path(temporaire).unlink(missing_ok=True)
        raise


def deposer(dossier: Path, periode: Periode, titre: str, pdf: bytes, genere_le: datetime) -> Depot:
    dossier.mkdir(parents=True, exist_ok=True)
    rapport = identifiant(periode)
    chemin_pdf, chemin_json = dossier / f"{rapport}.pdf", dossier / f"{rapport}.json"
    remplace = chemin_json.exists()
    metadonnees = {
        "report_id": str(rapport),
        "title": titre[:200],
        "period_start": periode.api(periode.debut),
        "period_end": periode.api(periode.fin),
        "generated_at": genere_le.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file_name": nom_de_fichier(periode),
        "size_bytes": len(pdf),
        "content_type": "application/pdf",
        "sha256": hashlib.sha256(pdf).hexdigest(),
    }
    # Remplacement : l'ancien rapport disparaît de la liste le temps d'écrire le nouveau PDF, au lieu
    # d'afficher pendant un instant des métadonnées qui ne correspondent plus au fichier.
    chemin_json.unlink(missing_ok=True)
    _ecrire(chemin_pdf, pdf)
    _ecrire(chemin_json, json.dumps(metadonnees, ensure_ascii=False, indent=2).encode("utf-8"))
    return Depot(rapport, chemin_pdf, chemin_json, metadonnees, remplace)


def notifier(dossier: Path, niveau: str, message: str, quand: datetime) -> None:
    """Notification simulée : une ligne JSON ajoutée à `notifications.log` (équivalent local d'un courriel)."""
    dossier.mkdir(parents=True, exist_ok=True)
    ligne = {"ts": quand.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "niveau": niveau, "message": message}
    with (dossier / NOM_NOTIFICATIONS).open("a", encoding="utf-8") as fichier:
        fichier.write(json.dumps(ligne, ensure_ascii=False) + "\n")
