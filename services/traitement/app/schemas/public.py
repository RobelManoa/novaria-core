"""Réponses des routes publiques de l'application citoyenne (CIT-03, ADR-030).

Mêmes champs que `PublicSegmentState` et `PublicCongestionList` de
`contracts/openapi/traitement.openapi.yaml`. **Liste blanche** : six champs et aucun autre.
`extra="forbid"` refuse un champ de plus, et le mappeur copie chaque champ à la main : ajouter une
colonne au modèle interne n'ajoute rien à ce que le public voit.
"""

from datetime import UTC, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.repositories.indicators import PublicSegmentRow
from app.schemas.indicators import CongestionState

WINDOW_S = (
    60  # la route lit la dernière fenêtre d'une minute : sa mise à jour est la fin de cette fenêtre
)


class PublicSegmentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    road_segment_id: str
    intersection_id: str
    approach: Literal["N", "E", "S", "W"]
    state: CongestionState
    updated_at: str
    simulated: bool

    @classmethod
    def from_row(cls, row: PublicSegmentRow) -> "PublicSegmentState":
        end = (row.window_start + timedelta(seconds=WINDOW_S)).astimezone(UTC)
        return cls(
            road_segment_id=row.road_segment_id,
            intersection_id=row.intersection_id,
            approach=row.approach,
            state=CongestionState(row.congestion_state),
            updated_at=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            simulated=row.source_type == "SIMULATED",
        )


class PublicCongestionList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PublicSegmentState]
