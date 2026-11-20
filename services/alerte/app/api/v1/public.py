"""Routes publiques de l'application citoyenne (CIT-03, ADR-030) : sans jeton, en lecture seule.

Contrat : `alerte.openapi.yaml`, `GET /api/v1/public/alerts` (`security: []`).

Ce service ne sert que sa part : les alertes de congestion en cours. L'état par tronçon est servi
par `traitement`. Aucune dépendance d'authentification : la passerelle a déjà fixé le débit, le
cache et retiré tout jeton (`gateway/citoyen.conf`). Le journal et `/metrics` ne portent jamais de
valeur de requête (`app/core/logs.py`, `app/core/metrics.py`) : l'étiquette est le modèle de route.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_store
from app.api.mapping import public_alert_out
from app.schemas.api import Problem, PublicAlertListOut
from app.services.ports import AlertStore

router = APIRouter(tags=["Public"])

# Borne de la liste (le contrat dit 100) : une route publique ne rend jamais une liste sans limite.
PUBLIC_LIMIT = 100


@router.get(
    "/public/alerts",
    response_model=PublicAlertListOut,
    operation_id="getPublicAlerts",
    summary="Alertes de congestion en cours (public)",
    responses={429: {"model": Problem, "description": "Limite de débit ; `RATE_LIMITED`."}},
)
def public_alerts(store: Annotated[AlertStore, Depends(get_store)]) -> dict:
    """Les alertes de congestion non résolues, de la plus récente à la plus ancienne."""
    return {"items": [public_alert_out(a) for a in store.list_open_congestion(PUBLIC_LIMIT)]}
