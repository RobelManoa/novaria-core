"""`GET /metrics` : indicateurs au format Prometheus (ADR-025, IA-06).

Hors de `/api/v1` et hors du contrat OpenAPI : c'est un point d'exploitation, pas une route métier.
Sans jeton, comme le veut un collecteur de métriques ; il ne sort que des nombres et les
identifiants de deux exécutions. Le port du service n'est publié que sur 127.0.0.1 et la
passerelle ne route pas `/metrics` (`gateway/nginx.conf`). Pour l'instant : la dérive des entrées
du modèle de prévision.
"""

from fastapi import Depends, Response

from app.db.session import get_indicator_repository
from app.drift import metrics
from app.drift.runtime import get_drift_monitor
from app.drift.service import DriftMonitor
from app.repositories.indicators import IndicatorRepository


def read_metrics(
    indicators: IndicatorRepository = Depends(get_indicator_repository),
    monitor: DriftMonitor = Depends(get_drift_monitor),
) -> Response:
    return Response(metrics.render(monitor.report(indicators)), media_type=metrics.CONTENT_TYPE)
