"""Rapports automatiques (FE-06, IA-07) : `Report` et `ReportPage` de `traitement.openapi.yaml`.

`ReportMetadata` est aussi le format du fichier de métadonnées que le robot dépose à côté du PDF
(`<report_id>.json`) : une seule définition, validée à l'écriture par le robot et à la lecture ici.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

# Le nom devient l'en-tête `Content-Disposition` : ni guillemet, ni barre, ni caractère de contrôle.
FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,199}")
SHA256 = re.compile(r"[0-9a-f]{64}")


class ReportMetadata(BaseModel):
    """Métadonnées d'un rapport, telles que le contrat les décrit."""

    model_config = ConfigDict(extra="forbid")

    report_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    period_start: datetime
    period_end: datetime
    generated_at: datetime
    file_name: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(ge=0)
    content_type: Literal["application/pdf"]
    sha256: str

    @field_validator("period_start", "period_end", "generated_at")
    @classmethod
    def has_a_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("la date doit porter un fuseau horaire (UTC)")
        return value

    @field_validator("file_name")
    @classmethod
    def file_name_is_safe(cls, value: str) -> str:
        if not FILE_NAME.fullmatch(value):
            raise ValueError("nom de fichier non conforme")
        return value

    @field_validator("sha256")
    @classmethod
    def sha256_is_hex(cls, value: str) -> str:
        if not SHA256.fullmatch(value):
            raise ValueError("empreinte SHA-256 attendue en hexadécimal minuscule")
        return value


class ReportResponse(ReportMetadata):
    @field_serializer("period_start", "period_end", "generated_at")
    def in_utc(self, value: datetime) -> datetime:
        """Le contrat veut une date UTC (`...Z`), quel que soit le fuseau du fichier déposé."""
        return value.astimezone(UTC)


class ReportPageResponse(BaseModel):
    items: list[ReportResponse]
    next_cursor: str | None = Field(
        description="Curseur de la page suivante ; null sur la dernière."
    )
