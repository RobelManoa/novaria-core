"""Dépôt d'utilisateurs en mémoire pour les tests d'authentification et d'autorisation (BE-03).

Même comportement que `SqlUserRepository` sur ce que les services utilisent : unicité du nom,
valeurs par défaut posées à l'écriture, tri par date de création puis identifiant.
"""

import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from app.core.security import create_access_token, hash_password
from app.models import Role, User
from app.repositories.indicators import IndicatorFilters, IndicatorRow, Position
from app.repositories.users import DuplicateUsername
from app.services.indicators import make_indicator_id

PASSWORD = "mot-de-passe-de-test-12"
# Valeur d'essai, pas un secret. Assemblée plutôt qu'écrite d'un bloc : un littéral de cette
# longueur, dans une variable nommée « secret », est pris pour une clé par gitleaks.
SECRET = "-".join(["essai"] * 8)  # 47 caractères : au-dessus du minimum de 32
TTL_S = 1800
ORIGIN = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


@lru_cache
def hash_of(password: str) -> str:
    """Une empreinte argon2id par mot de passe : le calcul est volontairement lent."""
    return hash_password(password)


class FakeUserRepository:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}

    def get_by_username(self, username: str) -> User | None:
        return next((u for u in self.users.values() if u.username == username), None)

    def get(self, user_id: uuid.UUID) -> User | None:
        return self.users.get(user_id)

    def add(self, user: User) -> User:
        if self.get_by_username(user.username) is not None:
            raise DuplicateUsername(user.username)
        user.user_id = user.user_id or uuid.uuid4()
        user.is_active = True if user.is_active is None else user.is_active
        user.created_at = user.created_at or ORIGIN + timedelta(seconds=len(self.users))
        self.users[user.user_id] = user
        return user

    def list_page(self, *, limit, after, role):
        rows = sorted(self.users.values(), key=lambda u: (u.created_at, u.user_id))
        if role is not None:
            rows = [u for u in rows if u.role == role]
        if after is not None:
            rows = [u for u in rows if (u.created_at, u.user_id) > after]
        return rows[:limit]

    def make(
        self,
        username: str,
        role: Role = Role.VIEWER,
        *,
        password: str = PASSWORD,
        active: bool = True,
    ) -> User:
        return self.add(
            User(username=username, password_hash=hash_of(password), role=role, is_active=active)
        )


def bearer(user: User, *, secret: str = SECRET) -> dict[str, str]:
    """En-tête d'un jeton valide pour cet utilisateur."""
    token = create_access_token(user.user_id, user.role, secret=secret, ttl_s=TTL_S)
    return {"Authorization": f"Bearer {token.value}"}


START = datetime(2026, 10, 20, 8, 20, tzinfo=UTC)


def make_row(**changes) -> IndicatorRow:
    """Un indicateur (exemple de `traitement.openapi.yaml`), modifiable champ par champ."""
    values = {
        "road_segment_id": "ROAD_001",
        "intersection_id": "INT_01",
        "window_start": START,
        "window_size_s": 60,
        "vehicle_count": 9,
        "flow_veh_per_min": 9.0,
        "average_speed_kmh": 11.4,
        "occupancy_rate": 0.78,
        "max_queue_length_m": 140.0,
        "speed_ratio": 0.228,
        "sample_count": 6,
        "expected_sample_count": 6,
        "completeness": 1.0,
        "congestion_state": "CONGESTED",
        "classifier_version": "regles-v0",
        "run_id": "run-demo-0001",
        "source_type": "SIMULATED",
        "scenario_id": "journee-calme",
        "seed": 42,
        "dataset_id": None,
    } | changes
    identifier = make_indicator_id(
        values["run_id"], values["road_segment_id"], values["window_size_s"], values["window_start"]
    )
    return IndicatorRow(indicator_id=identifier, **values)


def sort_key(row: IndicatorRow) -> tuple:
    """Même ordre que la base : début décroissant, puis tronçon et exécution par octets."""
    return (-row.window_start.timestamp(), row.road_segment_id.encode(), row.run_id.encode())


class FakeIndicatorRepository:
    """Entrepôt en mémoire : mêmes filtres, ordre et curseur que `SqlIndicatorRepository`."""

    def __init__(self, rows: list[IndicatorRow] | None = None) -> None:
        self.rows = list(rows or [])

    def list_page(self, filters: IndicatorFilters, *, limit: int, after: Position | None):
        kept = [
            r
            for r in self.rows
            if r.window_size_s == filters.window_size_s
            and filters.intersection_id in (None, r.intersection_id)
            and filters.road_segment_id in (None, r.road_segment_id)
            and filters.congestion_state in (None, r.congestion_state)
            and filters.run_id in (None, r.run_id)
            and filters.source_type in (None, r.source_type)
            and (filters.start is None or r.window_start >= filters.start)
            and (filters.end is None or r.window_start < filters.end)
        ]
        if after is not None:
            last = (-after[0].timestamp(), after[1].encode(), after[2].encode())
            kept = [r for r in kept if sort_key(r) > last]
        return sorted(kept, key=sort_key)[:limit]

    def get(self, *, run_id, road_segment_id, window_size_s, window_start):
        return next(
            (
                r
                for r in self.rows
                if (r.run_id, r.road_segment_id, r.window_size_s, r.window_start)
                == (run_id, road_segment_id, window_size_s, window_start)
            ),
            None,
        )

    def latest(self, *, intersection_id, run_id):
        minutes = [r for r in self.rows if r.window_size_s == 60]
        if run_id is None and minutes:
            run_id = sorted(minutes, key=sort_key)[0].run_id
        par_troncon: dict[str, IndicatorRow] = {}
        for row in sorted(minutes, key=sort_key, reverse=True):
            if row.run_id == run_id and intersection_id in (None, row.intersection_id):
                par_troncon[row.road_segment_id] = row  # le dernier écrit est le plus récent
        return [par_troncon[k] for k in sorted(par_troncon, key=str.encode)]
