"""PostgreSQL, schéma `alertes` : alertes, historique, règles, boîte d'envoi.

Compte `svc_alerte`, droits minimaux (ADR-024).

Le SQL est écrit à la main : chaque changement d'état est une seule transaction (RG-17), avec des
verrous de ligne (`FOR UPDATE`) là où deux acteurs peuvent agir sur la même alerte (le travailleur
et un opérateur). L'index unique partiel `alert_one_open_per_segment_idx` arbitre la création : un
`INSERT ... ON CONFLICT DO NOTHING` qui n'écrit rien dit « une alerte non résolue existe déjà ».

Toute erreur de la base ou du gestionnaire de connexions devient `StoreFailed` ; les exceptions du
cœur (`NotFound`, `InvalidTransition`) traversent et annulent la transaction.
"""

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

from app.domain.model import Alert, HistoryEntry, Kind, Provenance, Rule, Severity, State
from app.services.ports import AlertFilter, NotFound, OutboxRow, PublishFailed, StoreFailed, Tx

logger = logging.getLogger("app.postgres")

ALERT_COLUMNS = (
    "alert_id::text AS alert_id, rule_id, kind, road_segment_id, intersection_id, episode_id::text "
    "AS episode_id, run_id, source_type, scenario_id, seed, dataset_id, severity, cause, state, "
    "opened_at, notified_at, acknowledged_at, acknowledged_by, resolved_at, resolution, "
    "correlation_id, updated_at"
)
RULE_COLUMNS = "rule_id, kind, enabled, params, min_gap_s, updated_at"


def alert_of(row: dict[str, Any]) -> Alert:
    return Alert(
        alert_id=row["alert_id"],
        rule_id=row["rule_id"],
        kind=Kind(row["kind"]),
        road_segment_id=row["road_segment_id"],
        intersection_id=row["intersection_id"],
        provenance=Provenance(
            row["source_type"], row["run_id"], row["scenario_id"], row["seed"], row["dataset_id"]
        ),
        severity=Severity(row["severity"]),
        state=State(row["state"]),
        opened_at=row["opened_at"],
        cause=row["cause"],
        episode_id=row["episode_id"],
        notified_at=row["notified_at"],
        acknowledged_at=row["acknowledged_at"],
        acknowledged_by=row["acknowledged_by"],
        resolved_at=row["resolved_at"],
        resolution=row["resolution"],
        correlation_id=row["correlation_id"],
        updated_at=row["updated_at"],
    )


def rule_of(row: dict[str, Any]) -> Rule:
    return Rule(
        rule_id=row["rule_id"],
        kind=Kind(row["kind"]),
        enabled=row["enabled"],
        params=row["params"] or {},
        min_gap_s=row["min_gap_s"],
        updated_at=row["updated_at"],
    )


class _PgTx:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._c = connection

    def _one(self, sql: str, params: tuple) -> Alert | None:
        row = self._c.execute(sql, params).fetchone()
        return alert_of(row) if row else None

    def last_alert(self, kind: Kind, segment: str, run_id: str) -> Alert | None:
        return self._one(
            f"SELECT {ALERT_COLUMNS} FROM alertes.alert "
            "WHERE kind = %s AND road_segment_id = %s AND run_id = %s "
            "ORDER BY opened_at DESC LIMIT 1",
            (kind.value, segment, run_id),
        )

    def open_alert(self, kind: Kind, segment: str, run_id: str, *, lock: bool) -> Alert | None:
        return self._one(
            f"SELECT {ALERT_COLUMNS} FROM alertes.alert "
            "WHERE kind = %s AND road_segment_id = %s AND run_id = %s AND state <> 'RESOLVED'"
            + (" FOR UPDATE" if lock else ""),
            (kind.value, segment, run_id),
        )

    def get(self, alert_id: str, *, lock: bool) -> Alert | None:
        return self._one(
            f"SELECT {ALERT_COLUMNS} FROM alertes.alert WHERE alert_id = %s::uuid"
            + (" FOR UPDATE" if lock else ""),
            (alert_id,),
        )

    def insert(self, alert: Alert) -> bool:
        p = alert.provenance
        cursor = self._c.execute(
            "INSERT INTO alertes.alert (alert_id, rule_id, kind, road_segment_id, intersection_id, "
            "episode_id, run_id, source_type, scenario_id, seed, dataset_id, severity, cause, "
            "state, opened_at, correlation_id, updated_at) "
            "VALUES (%s::uuid, %s, %s, %s, %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s) "
            "ON CONFLICT DO NOTHING",
            (alert.alert_id, alert.rule_id, alert.kind.value, alert.road_segment_id,
             alert.intersection_id, alert.episode_id, p.run_id, p.source_type, p.scenario_id,
             p.seed, p.dataset_id, alert.severity.value, alert.cause, alert.state.value,
             alert.opened_at, alert.correlation_id, alert.updated_at),
        )  # fmt: skip
        return cursor.rowcount == 1

    def update(self, alert: Alert) -> None:
        self._c.execute(
            "UPDATE alertes.alert SET state = %s, notified_at = %s, acknowledged_at = %s, "
            "acknowledged_by = %s, resolved_at = %s, resolution = %s, updated_at = %s "
            "WHERE alert_id = %s::uuid",
            (alert.state.value, alert.notified_at, alert.acknowledged_at, alert.acknowledged_by,
             alert.resolved_at, alert.resolution, alert.updated_at, alert.alert_id),
        )  # fmt: skip

    def add_history(self, alert_id: str, entry: HistoryEntry) -> None:
        self._c.execute(
            "INSERT INTO alertes.alert_history (alert_id, from_state, to_state, changed_at, actor, "
            "details) VALUES (%s::uuid, %s, %s, %s, %s, %s)",
            (alert_id, entry.from_state.value if entry.from_state else None,
             entry.to_state.value, entry.changed_at, entry.actor,
             Jsonb(entry.details) if entry.details is not None else None),
        )  # fmt: skip

    def add_outbox(self, topic: str, key: str, event_id: str, payload: dict[str, Any]) -> None:
        self._c.execute(
            "INSERT INTO alertes.outbox_event (topic, event_key, event_id, payload) "
            "VALUES (%s, %s, %s, %s)",
            (topic, key, event_id, Jsonb(payload)),
        )


class PostgresAlertStore:
    def __init__(self, dsn: str, *, max_size: int = 5, timeout_s: float = 5.0) -> None:
        # `open=False` : le pool ne se connecte qu'au premier usage, un service sans base démarre.
        self._pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=max_size,
            timeout=timeout_s,
            kwargs={"row_factory": dict_row, "application_name": "novaria-alerte"},
            open=False,
        )
        self._opened = False

    def _ready(self) -> ConnectionPool:
        if not self._opened:
            try:
                self._pool.open(wait=False)
            except Exception as error:  # noqa: BLE001 - un échec d'ouverture est une panne
                raise StoreFailed(type(error).__name__) from error
            self._opened = True
        return self._pool

    def close(self) -> None:
        if self._opened:
            self._pool.close()
            self._opened = False

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection]:
        try:
            with self._ready().connection() as connection:
                yield connection
        except (psycopg.Error, PoolTimeout) as error:
            raise StoreFailed(type(error).__name__) from error

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        with self._connection() as connection:  # valide en sortie, annule sur exception
            yield _PgTx(connection)

    # ----------------------------------------------------------------------------- lectures
    def rules(self) -> list[Rule]:
        with self._connection() as c:
            rows = c.execute(f"SELECT {RULE_COLUMNS} FROM alertes.alert_rule ORDER BY rule_id")
            return [rule_of(r) for r in rows.fetchall()]

    def update_rule(
        self, rule_id: str, *, enabled: bool | None, params: dict[str, Any] | None,
        min_gap_s: int | None,
    ) -> Rule:  # fmt: skip
        with self._connection() as c:
            row = c.execute(
                "UPDATE alertes.alert_rule SET enabled = COALESCE(%s, enabled), "
                "params = CASE WHEN %s::jsonb IS NULL THEN params ELSE params || %s::jsonb END, "
                "min_gap_s = COALESCE(%s, min_gap_s), updated_at = now() WHERE rule_id = %s "
                f"RETURNING {RULE_COLUMNS}",
                (enabled, _json(params), _json(params), min_gap_s, rule_id),
            ).fetchone()
        if row is None:
            raise NotFound(rule_id)
        return rule_of(row)

    def pending_notification(self, limit: int) -> list[Alert]:
        with self._connection() as c:
            rows = c.execute(
                f"SELECT {ALERT_COLUMNS} FROM alertes.alert WHERE state = 'CREATED' "
                "ORDER BY opened_at, alertes.alert.alert_id LIMIT %s",
                (limit,),
            ).fetchall()
        return [alert_of(r) for r in rows]

    def list_alerts(
        self, filters: AlertFilter, *, after: tuple[datetime, str] | None, limit: int
    ) -> list[Alert]:  # fmt: skip
        clauses, params = [], []
        for column, value in (
            ("state", filters.state.value if filters.state else None),
            ("kind", filters.kind.value if filters.kind else None),
            ("severity", filters.severity),
            ("intersection_id", filters.intersection_id),
            ("road_segment_id", filters.road_segment_id),
        ):
            if value is not None:
                clauses.append(f"{column} = %s")
                params.append(value)
        if filters.opened_from is not None:
            clauses.append("opened_at >= %s")
            params.append(filters.opened_from)
        if filters.opened_to is not None:
            clauses.append("opened_at <= %s")
            params.append(filters.opened_to)
        if after is not None:
            clauses.append("(opened_at, alert_id) < (%s, %s::uuid)")
            params.extend(after)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connection() as c:
            rows = c.execute(
                f"SELECT {ALERT_COLUMNS} FROM alertes.alert {where} "
                "ORDER BY opened_at DESC, alertes.alert.alert_id DESC LIMIT %s",
                (*params, limit),
            ).fetchall()
        return [alert_of(r) for r in rows]

    def get_alert(self, alert_id: str) -> tuple[Alert, list[HistoryEntry]] | None:
        with self._connection() as c:
            row = c.execute(
                f"SELECT {ALERT_COLUMNS} FROM alertes.alert WHERE alert_id = %s::uuid", (alert_id,)
            ).fetchone()
            if row is None:
                return None
            history = c.execute(
                "SELECT from_state, to_state, changed_at, actor, details "
                "FROM alertes.alert_history WHERE alert_id = %s::uuid ORDER BY history_id",
                (alert_id,),
            ).fetchall()
        entries = [
            HistoryEntry(
                State(h["from_state"]) if h["from_state"] else None,
                State(h["to_state"]),
                h["changed_at"],
                h["actor"],
                h["details"],
            )
            for h in history
        ]
        return alert_of(row), entries

    # ------------------------------------------------------------------------ boîte d'envoi
    def relay_outbox(self, publish: Callable[[OutboxRow], None], *, limit: int) -> int:
        """Publie dans l'ordre les lignes non publiées. Une ligne est marquée **après** l'accusé du
        bus ; à la première erreur de publication, ce qui est déjà accusé est validé, puis l'erreur
        remonte (les lignes restantes seront reprises : livraison au moins une fois)."""
        failure: PublishFailed | None = None
        done = 0
        with self._connection() as c:
            rows = c.execute(
                "SELECT outbox_id, topic, event_key, event_id, payload FROM alertes.outbox_event "
                "WHERE published_at IS NULL ORDER BY outbox_id LIMIT %s FOR UPDATE SKIP LOCKED",
                (limit,),
            ).fetchall()
            for row in rows:
                try:
                    publish(
                        OutboxRow(
                            row["outbox_id"], row["topic"], row["event_key"], row["event_id"],
                            row["payload"],
                        )
                    )  # fmt: skip
                except PublishFailed as error:
                    failure = error
                    break
                c.execute(
                    "UPDATE alertes.outbox_event SET published_at = now() WHERE outbox_id = %s",
                    (row["outbox_id"],),
                )
                done += 1
        if failure is not None:
            raise failure
        return done


def _json(value: dict[str, Any] | None) -> str | None:
    return json.dumps(value) if value is not None else None
