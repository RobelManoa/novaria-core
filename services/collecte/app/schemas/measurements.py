"""Corps des réponses de `POST /api/v1/measurements` : `MeasurementReceipt` et `Problem`."""

from typing import Literal

from pydantic import BaseModel, Field


class MeasurementReceipt(BaseModel):
    """Accusé de réception : `ACCEPTED` (publiée) ou `DUPLICATE` (même `id` déjà reçu, ignorée)."""

    event_id: str = Field(min_length=1, description="`id` de l'événement reçu (clé d'idempotence).")
    status: Literal["ACCEPTED", "DUPLICATE"]


class ProblemItem(BaseModel):
    field: str
    message: str


class Problem(BaseModel):
    """Erreur au format RFC 9457 (`common.yaml`, schéma `Problem`)."""

    type: str
    title: str
    status: int
    code: str
    detail: str
    correlation_id: str
    errors: list[ProblemItem] | None = None
