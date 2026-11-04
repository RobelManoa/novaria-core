"""Anomalies injectables : valeur aberrante, capteur muet, doublon, message en retard.

Une anomalie vise UN capteur sur une suite d'intervalles et ne touche rien d'autre : les autres messages du run restent
identiques octet pour octet (les valeurs viennent de `rng`, sans état). Elle s'écrit en ligne de commande ou en JSON :

    aberrante:sensor=SENSOR_003,at=2026-10-20T08:05:00Z,variant=vitesse
    muet:sensor=SENSOR_007,at=+600,duration=5m
    doublon:sensor=SENSOR_001,at=+120,copies=2,lag=3
    retard:sensor=SENSOR_010,at=+300,delay=45

`at` est l'instant de FIN du premier intervalle touché (le `time` du message) : date UTC, ou « +N » secondes depuis le début
du run. Absent, il vaut « au prochain intervalle » (injection à la demande pendant une exécution).
"""

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from .network import INTERVAL_S, SEGMENT_BY_SENSOR

KINDS = ("aberrante", "muet", "doublon", "retard")
OUTLIER_VARIANTS = ("vitesse", "debit", "vitesse-nulle")
DEFAULT_DURATION_S = {"muet": 300}  # un capteur muet l'est plus de 60 s (règle DQ-08)
DEFAULT_DELAY_S = 45  # au-delà du retard autorisé de 30 s (règle DQ-04) : la collecte rejette ce message
TRUTH_NAMES = {"aberrante": "OUTLIER", "muet": "SILENT", "doublon": "DUPLICATE", "retard": "LATE"}

_DURATION = re.compile(r"^(\d+)([smh]?)$")


class AnomalyError(ValueError):
    """Anomalie mal écrite : le message dit quoi corriger."""


def parse_utc(text: str) -> datetime:
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise AnomalyError(f"date illisible : {text!r} (attendu : 2026-10-20T08:05:00Z)") from error
    if moment.tzinfo is None:
        raise AnomalyError(f"date sans fuseau : {text!r} (ajouter Z)")
    return moment.astimezone(UTC)


def parse_duration(text: str) -> int:
    match = _DURATION.match(str(text).strip())
    if not match:
        raise AnomalyError(f"durée illisible : {text!r} (exemples : 90, 90s, 5m, 1h)")
    return int(match[1]) * {"": 1, "s": 1, "m": 60, "h": 3600}[match[2]]


@dataclass(frozen=True)
class Anomaly:
    kind: str
    sensor_id: str
    start: datetime | None  # None : à la demande, résolu au prochain intervalle par Run.add_anomaly
    intervals: int = 1  # nombre d'intervalles consécutifs touchés
    variant: str = ""  # aberrante : vitesse, debit ou vitesse-nulle
    delay_s: int = 0  # retard : secondes de retard à la livraison
    copies: int = 1  # doublon : nombre de copies en plus de l'original
    lag_s: int = 0  # doublon : secondes entre l'original et ses copies

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise AnomalyError(f"type d'anomalie inconnu : {self.kind!r} (attendus : {', '.join(KINDS)})")
        if self.sensor_id not in SEGMENT_BY_SENSOR:
            raise AnomalyError(f"capteur inconnu : {self.sensor_id!r} (SENSOR_001 à SENSOR_024)")
        if self.intervals < 1:
            raise AnomalyError("la durée doit couvrir au moins un intervalle")
        if self.start is not None and (self.start.tzinfo is None or int(self.start.timestamp()) % INTERVAL_S):
            raise AnomalyError(f"`at` doit tomber sur un multiple de {INTERVAL_S} s (fin d'un intervalle) : {self.start}")
        if self.kind == "aberrante" and self.variant not in OUTLIER_VARIANTS:
            raise AnomalyError(f"variante inconnue : {self.variant!r} (attendues : {', '.join(OUTLIER_VARIANTS)})")
        if self.kind == "retard" and self.delay_s < 1:
            raise AnomalyError("un retard doit durer au moins 1 s")
        if self.kind == "doublon" and (self.copies < 1 or self.copies > 10 or self.lag_s < 0):
            raise AnomalyError("un doublon a de 1 à 10 copies, et un décalage de 0 s ou plus")

    @property
    def anomaly_id(self) -> str:
        start = "demande" if self.start is None else str(int(self.start.timestamp() * 1000))
        return f"{self.kind}:{self.sensor_id}:{start}"

    @property
    def last(self) -> datetime | None:
        return None if self.start is None else self.start + timedelta(seconds=INTERVAL_S * (self.intervals - 1))

    def covers(self, instant: datetime) -> bool:
        return self.start is not None and self.start <= instant <= self.last  # type: ignore[operator]

    def resolved(self, start: datetime) -> "Anomaly":
        return replace(self, start=start)

    def to_json(self) -> dict:
        """Forme écrite dans le manifeste ; `from_json` la relit (rejeu d'un run avec ses anomalies)."""
        data = {"kind": self.kind, "sensor_id": self.sensor_id, "intervals": self.intervals}
        data["start"] = None if self.start is None else self.start.strftime("%Y-%m-%dT%H:%M:%SZ")
        if self.kind == "aberrante":
            data["variant"] = self.variant
        elif self.kind == "retard":
            data["delay_s"] = self.delay_s
        elif self.kind == "doublon":
            data.update(copies=self.copies, lag_s=self.lag_s)
        return dict(sorted(data.items()))

    @classmethod
    def from_json(cls, data: dict, run_start: datetime | None = None) -> "Anomaly":
        known = {"kind", "sensor_id", "start", "at", "intervals", "duration", "variant", "delay_s", "delay", "copies", "lag_s", "lag", "sensor"}
        unknown = set(data) - known
        if unknown:
            raise AnomalyError(f"champ inconnu : {', '.join(sorted(unknown))}")
        kind = data.get("kind", "")
        raw_at = data.get("start", data.get("at"))
        if raw_at is None:
            start = None
        elif isinstance(raw_at, str) and raw_at.startswith("+"):
            if run_start is None:
                raise AnomalyError("« +N secondes » demande un début de run")
            start = run_start + timedelta(seconds=parse_duration(raw_at[1:]))
        else:
            start = parse_utc(str(raw_at))
        duration = data.get("duration")
        if "intervals" in data:
            intervals = int(data["intervals"])
        else:
            seconds = parse_duration(duration) if duration is not None else DEFAULT_DURATION_S.get(kind, INTERVAL_S)
            intervals = max(1, -(-seconds // INTERVAL_S))
        try:
            return cls(
                kind=kind,
                sensor_id=data.get("sensor_id", data.get("sensor", "")),
                start=start,
                intervals=intervals,
                variant=data.get("variant", "vitesse" if kind == "aberrante" else ""),
                delay_s=int(data.get("delay_s", data.get("delay", DEFAULT_DELAY_S if kind == "retard" else 0))),
                copies=int(data.get("copies", 1)),
                lag_s=int(data.get("lag_s", data.get("lag", 0))),
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, AnomalyError):
                raise
            raise AnomalyError(f"valeur illisible dans l'anomalie : {error}") from error


def parse_spec(spec: str, run_start: datetime | None = None) -> Anomaly:
    """« muet:sensor=SENSOR_007,at=+600,duration=5m » devient une `Anomaly`."""
    kind, _, rest = spec.partition(":")
    fields: dict[str, str] = {"kind": kind.strip()}
    for part in filter(None, (piece.strip() for piece in rest.split(","))):
        key, separator, value = part.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise AnomalyError(f"champ mal écrit : {part!r} (attendu : cle=valeur)")
        fields[key.strip()] = value.strip()
    if "sensor" not in fields:
        raise AnomalyError("`sensor=SENSOR_nnn` est obligatoire")
    return Anomaly.from_json(fields, run_start)
