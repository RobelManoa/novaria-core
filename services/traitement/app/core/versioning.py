"""Politique de version de l'API (BE-06) : une seule version majeure publiée, `/api/v1`.

- L'URL porte la version **majeure** (`/api/v1/...`). Un changement compatible (champ ajouté,
  paramètre facultatif, route nouvelle) garde `v1` ; une rupture crée `/api/v2`, qui vit à côté de
  `v1` pendant la transition (règles : `contracts/openapi/README.md`).
- Une version inconnue (`/api/v2/...` avant sa publication) répond 404 `NOT_FOUND` en disant quelles
  versions existent, au lieu d'un 404 muet.
- Le retrait d'une route annoncé à l'avance passe par `deprecated(...)` : en-têtes `Deprecation`
  (RFC 9745) et `Sunset` (RFC 8594) sur ses réponses.
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import format_datetime

from fastapi import Response

API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"
SUPPORTED_VERSIONS = (API_VERSION,)

_VERSION_IN_PATH = re.compile(r"^/api/(v[0-9]{1,6})(?:/|$)")


def unsupported_version(path: str) -> str | None:
    """La version demandée par le chemin si elle n'est pas publiée, sinon `None`."""
    found = _VERSION_IN_PATH.match(path)
    if found and found.group(1) not in SUPPORTED_VERSIONS:
        return found.group(1)
    return None


def deprecated(since: datetime, sunset: datetime | None = None) -> Callable[[Response], None]:
    """Dépendance d'une route dont le retrait est annoncé.

    `Deprecation: @<secondes>` dit depuis quand la route est dépréciée ; `Sunset` donne la date
    de retrait. Les deux dates sont en UTC, sinon elles sont refusées.
    """
    for moment in (since, sunset):
        if moment is not None and moment.utcoffset() is None:
            raise ValueError("les dates de dépréciation doivent avoir un fuseau horaire")
    if sunset is not None and sunset < since:
        raise ValueError("le retrait ne peut pas précéder l'annonce")

    def add_headers(response: Response) -> None:
        response.headers["Deprecation"] = f"@{int(since.astimezone(UTC).timestamp())}"
        if sunset is not None:
            response.headers["Sunset"] = format_datetime(sunset.astimezone(UTC), usegmt=True)

    return add_headers
