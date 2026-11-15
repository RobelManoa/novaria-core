"""Lecture des rapports déposés par le robot (FE-06, ADR-019, ADR-025).

Le robot dépose dans un dossier deux fichiers par rapport : `<report_id>.pdf`, puis, en dernier,
`<report_id>.json` (les métadonnées). Un rapport n'existe pour l'API que lorsque ses métadonnées
sont valides **et** que son PDF est là : le robot écrit le PDF d'abord, de sorte qu'un rapport
listé est toujours téléchargeable. Ce service ne fait que lire : il n'écrit, ne supprime et ne
déplace rien.

Équivalent local d'un seau S3 derrière le port `ReportStore` ([ADR-025], [ADR-029]) ; le jour où le
stockage change, seul l'adaptateur change.
"""

import base64
import binascii
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from app.schemas.reports import ReportMetadata

logger = logging.getLogger("app.reports")
DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class InvalidCursor(ValueError):
    """Le curseur n'a pas été produit par ce service."""


class ReportCorrupted(Exception):
    """Le PDF ne correspond pas à la taille ou à l'empreinte de ses métadonnées."""


@dataclass(frozen=True)
class ReportFile:
    metadata: ReportMetadata
    path: Path


@dataclass(frozen=True)
class ReportPage:
    items: list[ReportMetadata]
    next_cursor: str | None


class ReportStore(Protocol):
    def list_all(self) -> list[ReportMetadata]:
        """Tous les rapports lisibles, du plus récent au plus ancien."""

    def open(self, report_id: uuid.UUID) -> ReportFile | None:
        """Le rapport et le chemin de son PDF, vérifiés ; `None` s'il n'existe pas."""


def order_key(item: ReportMetadata) -> tuple[float, str]:
    """`generated_at` décroissant, puis `report_id` croissant (comme le dit le contrat)."""
    return (-item.generated_at.timestamp(), str(item.report_id))


class FileReportStore:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def _metadata(self, path: Path) -> ReportMetadata | None:
        try:
            metadata = ReportMetadata.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError):
            logger.warning(
                "métadonnées de rapport illisibles", extra={"fields": {"file": path.name}}
            )
            return None
        if path.name != f"{metadata.report_id}.json":
            logger.warning(
                "métadonnées au nom d'un autre rapport", extra={"fields": {"file": path.name}}
            )
            return None
        return metadata

    def list_all(self) -> list[ReportMetadata]:
        if not self._directory.is_dir():
            return []
        found = []
        for path in self._directory.glob("*.json"):
            metadata = self._metadata(path)
            if metadata is not None and (self._directory / f"{metadata.report_id}.pdf").is_file():
                found.append(metadata)
        return sorted(found, key=order_key)

    def open(self, report_id: uuid.UUID) -> ReportFile | None:
        # Le chemin vient d'un UUID analysé : ni texte du client, ni nom lu dans un fichier.
        base = self._directory / str(report_id)
        metadata_path, pdf_path = base.with_suffix(".json"), base.with_suffix(".pdf")
        if not (metadata_path.is_file() and pdf_path.is_file()):
            return None
        metadata = self._metadata(metadata_path)
        if metadata is None:
            return None
        content = pdf_path.read_bytes()
        if (
            len(content) != metadata.size_bytes
            or hashlib.sha256(content).hexdigest() != metadata.sha256
        ):
            logger.error("rapport corrompu", extra={"fields": {"report_id": str(report_id)}})
            raise ReportCorrupted(str(report_id))
        return ReportFile(metadata, pdf_path)


def encode_cursor(item: ReportMetadata) -> str:
    raw = json.dumps([item.generated_at.isoformat(), str(item.report_id)])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[float, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        moment, identifier = json.loads(raw)
        stamp = datetime.fromisoformat(moment)
        if stamp.tzinfo is None or not isinstance(identifier, str):
            raise ValueError("forme")
        return (-stamp.timestamp(), str(uuid.UUID(identifier)))
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError) as error:
        raise InvalidCursor(cursor) from error


class ReportService:
    def __init__(self, store: ReportStore) -> None:
        self._store = store

    def list_page(self, *, limit: int = DEFAULT_LIMIT, cursor: str | None = None) -> ReportPage:
        items = self._store.list_all()
        if cursor:
            after = decode_cursor(cursor)
            items = [item for item in items if order_key(item) > after]
        page = items[:limit]
        more = len(items) > limit
        return ReportPage(page, encode_cursor(page[-1]) if more else None)

    def open(self, report_id: uuid.UUID) -> ReportFile | None:
        return self._store.open(report_id)
