"""Recommandations de plan de feux : règle de Webster d'abord, score d'un modèle ensuite (IA-06).

Pour un carrefour et une fenêtre d'une minute, quand **toutes** ses approches ont leur indicateur :

| Situation | Suite |
|---|---|
| aucune approche `SLOW` ni `CONGESTED` | rien (le plan fixe suffit) |
| une approche `UNKNOWN` | rien : on ne recommande pas sur des données insuffisantes |
| un seul axe (nord-sud ou est-ouest) dans le réseau | rien : une phase ne fait pas un plan |
| sinon | recommandation `WEBSTER_REFERENCE`, valable 5 minutes |

Tant que la dégradation dure, une recommandation par minute ; quand elle cesse, plus rien : passé
`valid_until`, la réponse extérieure revient au plan fixe (EXG-REP-03). L'identifiant dérive du run,
du carrefour et de la fenêtre : rejouer la même fenêtre redonne la même recommandation.

Le champ `model` reste `null` : le contrat sait porter le score d'un modèle entraîné, mais ce
modèle (IA-06) n'existe pas encore. Quand il existera, son score sera une **entrée** (jamais la
décision) ; les durées de phase viennent toujours de `webster_plan`.
"""

import uuid
from collections import Counter
from decimal import Decimal
from fractions import Fraction

from pydantic import ValidationError

from app.flux.rejections import SERVICE
from app.schemas.events import RecommendationEvent

from .facts import IndicatorFact
from .reference import PlanReference
from .webster import VERSION, ApproachLoad, WebsterParams, webster_plan

_NAMESPACE = uuid.UUID(
    "0c2d3e4f-5a6b-5c7d-8e9f-1a2b3c4d5e6f"
)  # constante du projet, fixée une fois
VALIDITY_S = 300
DEGRADED = ("SLOW", "CONGESTED")


def _stamp(ms: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Recommender:
    def __init__(
        self,
        reference: PlanReference,
        params: WebsterParams | None = None,
        validity_s: int = VALIDITY_S,
    ) -> None:
        self._reference = reference
        self._params = params or WebsterParams()
        self._validity_s = validity_s
        self._groups: dict[tuple[str, str, int], dict[str, IndicatorFact]] = {}
        self._done: dict[tuple[str, str], int] = {}  # (run, carrefour) -> dernière fenêtre jugée
        self.stats: Counter[str] = Counter()

    def feed(self, facts: list[IndicatorFact]) -> list[dict]:
        """Range des indicateurs ; rend les recommandations des groupes devenus complets."""
        events: list[dict] = []
        for fact in facts:
            if fact.window_size_s != 60:
                continue
            if fact.road_segment_id not in self._reference.segments:
                self.stats["unknown_segment"] += 1
                continue
            scope = (fact.run_id, fact.intersection_id)
            if fact.window_start_ms <= self._done.get(scope, -1):
                self.stats["late_correction"] += (
                    1  # une correction ne change pas une décision prise
                )
                continue
            key = (*scope, fact.window_start_ms)
            group = self._groups.setdefault(key, {})
            group[fact.road_segment_id] = fact
            expected = {
                s.road_segment_id for s in self._reference.segments_of(fact.intersection_id)
            }
            if expected <= set(group):
                event = self._decide(group)
                if event is not None:
                    events.append(event)
                self._close(key)
        return events

    def _close(self, key: tuple[str, str, int]) -> None:
        run_id, intersection_id, start = key
        del self._groups[key]
        self._done[(run_id, intersection_id)] = start
        for older in [k for k in self._groups if k[:2] == key[:2] and k[2] < start]:
            del self._groups[older]  # une fenêtre plus ancienne restée incomplète est abandonnée
            self.stats["incomplete_group"] += 1

    def retained_offsets(self) -> dict[int, int]:
        """Plus petit offset, par partition, des indicateurs qui attendent encore leurs voisins."""
        lowest: dict[int, int] = {}
        for group in self._groups.values():
            for fact in group.values():
                if fact.partition is not None and fact.offset is not None:
                    lowest[fact.partition] = min(
                        fact.offset, lowest.get(fact.partition, fact.offset)
                    )
        return lowest

    def _decide(self, group: dict[str, IndicatorFact]) -> dict | None:
        facts = [group[segment] for segment in sorted(group)]
        states = {f.congestion_state for f in facts}
        if not states & set(DEGRADED):
            self.stats["no_need"] += 1
            return None
        if "UNKNOWN" in states:
            self.stats["unknown_approach"] += 1
            return None
        loads = [
            ApproachLoad(
                self._reference.segments[f.road_segment_id].approach,
                Fraction(Decimal(repr(f.flow_veh_per_min))),
                self._reference.segments[f.road_segment_id].lanes,
            )
            for f in facts
        ]
        plan = webster_plan(loads, self._params)
        if plan is None:
            self.stats["single_axis"] += 1
            return None
        event = self._event(facts, plan, "CONGESTED" if "CONGESTED" in states else "SLOW")
        try:
            RecommendationEvent.model_validate(event)
        except ValidationError:
            self.stats["invalid"] += 1
            return None
        self.stats["recommended"] += 1
        return event

    def _event(self, facts: list[IndicatorFact], plan, worst: str) -> dict:
        first = facts[0]
        identifier = str(
            uuid.uuid5(
                _NAMESPACE,
                f"recommendation:{first.run_id}:{first.intersection_id}:{first.window_start_ms}",
            )
        )
        end = first.window_end_ms
        return {
            "id": identifier,
            "source": SERVICE,
            "type": "novaria.traffic.recommendation.v1",
            "time": _stamp(end),
            "subject": first.intersection_id,
            "schema_version": "1.0",
            "correlation_id": f"corr-{first.window_start_ms}",
            "domain": "traffic",
            "data": {
                "recommendation_id": identifier,
                "intersection_id": first.intersection_id,
                "valid_until": _stamp(end + self._validity_s * 1000),
                "cycle_s": plan.cycle_s,
                "phases": [
                    {
                        "phase_id": p.phase_id,
                        "green_approaches": list(p.green_approaches),
                        "duration_s": p.duration_s,
                    }
                    for p in plan.phases
                ],
                "method": {"kind": "WEBSTER_REFERENCE", "version": VERSION},
                "model": None,
                "inputs": {
                    "indicator_ids": sorted(f.event_id for f in facts),
                    "window_start": _stamp(first.window_start_ms),
                    "window_size_s": 60,
                    "congestion_state": worst,
                },
                "provenance": first.provenance,
            },
        }
