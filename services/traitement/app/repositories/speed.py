"""Lecture des réseaux de vitesse dans l'entrepôt (IA-16) : `dwh.speed_network`, `dwh.speed_sensor`,
`dwh.fact_speed_window`.

Lecture seule, comme `indicators.py` : la session est ouverte en lecture seule. Un réseau de vitesse
n'a aucun comptage : seules les vitesses
mesurées ont une ligne, une vitesse absente n'en a pas.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class SpeedNetwork:
    network_id: str
    label: str
    description: str
    source_type: str
    step_s: int
    speed_unit: str


@dataclass(frozen=True)
class Coverage:
    first: datetime | None
    last: datetime | None
    steps: int
    sensors: int


@dataclass(frozen=True)
class SpeedReading:
    observed_at: datetime
    sensor_id: str
    speed: float  # dans l'unité du réseau


class SpeedRepository(Protocol):
    def list_networks(self) -> list[SpeedNetwork]: ...

    def get_network(self, network_id: str) -> SpeedNetwork | None: ...

    def sensors(self, network_id: str) -> list[str]:
        """Les identifiants des capteurs, dans l'ordre de leur rang."""
        ...

    def coverage(self, network_id: str) -> Coverage: ...

    def last_before(self, network_id: str, at: datetime | None) -> datetime | None:
        """Le dernier instant mesuré à `at` près (inclus) ; le dernier instant du réseau si `at` est
        vide."""
        ...

    def readings(self, network_id: str, start: datetime, end: datetime) -> list[SpeedReading]:
        """Les vitesses mesurées de `start` à `end` inclus."""
        ...


class SqlSpeedRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_networks(self) -> list[SpeedNetwork]:
        rows = self._session.execute(
            text(
                "SELECT network_id, label, description, source_type, step_s, speed_unit "
                'FROM dwh.speed_network ORDER BY network_id COLLATE "C"'
            )
        )
        return [SpeedNetwork(*row) for row in rows]

    def get_network(self, network_id: str) -> SpeedNetwork | None:
        row = self._session.execute(
            text(
                "SELECT network_id, label, description, source_type, step_s, speed_unit "
                "FROM dwh.speed_network WHERE network_id = :n"
            ),
            {"n": network_id},
        ).first()
        return SpeedNetwork(*row) if row else None

    def sensors(self, network_id: str) -> list[str]:
        rows = self._session.execute(
            text(
                "SELECT sensor_id FROM dwh.speed_sensor WHERE network_id = :n ORDER BY sensor_key"
            ),
            {"n": network_id},
        )
        return [row[0] for row in rows]

    def coverage(self, network_id: str) -> Coverage:
        row = self._session.execute(
            text(
                "SELECT min(observed_at), max(observed_at), count(DISTINCT observed_at) "
                "FROM dwh.fact_speed_window WHERE network_id = :n"
            ),
            {"n": network_id},
        ).one()
        sensors = self._session.execute(
            text("SELECT count(*) FROM dwh.speed_sensor WHERE network_id = :n"), {"n": network_id}
        ).scalar_one()
        return Coverage(row[0], row[1], int(row[2] or 0), int(sensors or 0))

    def last_before(self, network_id: str, at: datetime | None) -> datetime | None:
        query = "SELECT max(observed_at) FROM dwh.fact_speed_window WHERE network_id = :n"
        parameters: dict = {"n": network_id}
        if at is not None:
            query += " AND observed_at <= :at"
            parameters["at"] = at
        return self._session.execute(text(query), parameters).scalar_one()

    def readings(self, network_id: str, start: datetime, end: datetime) -> list[SpeedReading]:
        rows = self._session.execute(
            text(
                "SELECT f.observed_at, s.sensor_id, f.speed FROM dwh.fact_speed_window f "
                "JOIN dwh.speed_sensor s USING (network_id, sensor_key) "
                "WHERE f.network_id = :n AND f.observed_at BETWEEN :a AND :b "
                "ORDER BY f.observed_at, s.sensor_key"
            ),
            {"n": network_id, "a": start, "b": end},
        )
        return [SpeedReading(row[0], row[1], float(row[2])) for row in rows]


__all__ = ["Coverage", "SpeedNetwork", "SpeedReading", "SpeedRepository", "SqlSpeedRepository"]
