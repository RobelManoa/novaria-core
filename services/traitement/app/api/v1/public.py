"""Routes publiques de l'application citoyenne (CIT-03, ADR-030) : sans jeton, en lecture seule.

Contrat : `traitement.openapi.yaml`, `GET /api/v1/public/congestion` (`security: []`).

Ce service ne sert que sa part : l'état de chaque tronçon, lu dans l'entrepôt **existant**
(`dwh.v_indicator` et le référentiel des tronçons, par le compte en lecture seule), sans nouvelle
source. Les alertes en cours sont servies par `alerte`. Aucune dépendance d'authentification : la
passerelle a fixé le débit et le cache et retiré tout jeton (`gateway/citoyen.conf`). Le journal,
l'audit et `/metrics` ne portent jamais de valeur de requête : un appel sans jeton n'est que compté,
sous le modèle de route (`app/services/audit.py`).
"""

from fastapi import APIRouter, Depends

from app.api.responses import errors
from app.api.v1.indicators import get_indicator_service
from app.schemas.public import PublicCongestionList, PublicSegmentState
from app.services.indicators import IndicatorService

router = APIRouter(prefix="/public", tags=["public"])


@router.get(
    "/congestion",
    response_model=PublicCongestionList,
    operation_id="getPublicCongestion",
    summary="État de congestion de chaque tronçon (public)",
    responses=errors(429, "5XX"),
)
def public_congestion(
    service: IndicatorService = Depends(get_indicator_service),
) -> PublicCongestionList:
    """Un élément par tronçon, dans l'ordre de `road_segment_id`, pour le run le plus récent."""
    return PublicCongestionList(
        items=[PublicSegmentState.from_row(row) for row in service.latest_public()]
    )
