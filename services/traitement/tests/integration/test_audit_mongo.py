"""Journal d'audit et compteurs d'usage contre un vrai MongoDB (BE-05).

Preuve de la tâche « Capture MongoDB » : les entrées écrites par l'application sont lues dans la
base, avec les validateurs et les index créés par `db/mongo/init`.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import OperationFailure, WriteError

from app.core.config import get_settings
from app.db.observer import get_observer
from app.db.session import get_indicator_repository, get_user_repository
from app.main import app
from app.models import Role
from app.repositories.audit import open_collections
from app.services.audit import RecordingObserver, RequestEvent, bucket_start, build_audit_entry
from tests.fakes import bearer
from tests.integration.mongo import URL, database, erase, needs_mongo, unique_marker

pytestmark = needs_mongo

DEBUT = datetime(2026, 10, 20, 8, 20, 31, 123000, tzinfo=UTC)
UNAUTHORIZED = 13
SCHEMA_REFUSED = 121
DUPLICATE_KEY = 11000


@pytest.fixture
def base():
    return database(URL)


@pytest.fixture
def traces():
    """Ce qu'un test a écrit, effacé ensuite si un compte administrateur est fourni."""
    actors: list[str] = []
    endpoints: list[str] = []
    yield actors, endpoints
    erase(actors, endpoints)


def counted(base) -> dict[str, int]:
    """Total des compteurs par point d'accès, toutes tranches confondues."""
    totaux: dict[str, int] = {}
    for ligne in base.usage_stats.find({"endpoint": {"$not": {"$regex": "^GET /essai/"}}}):
        totaux[ligne["endpoint"]] = totaux.get(ligne["endpoint"], 0) + ligne["count"]
    return totaux


def event(actor: str, template: str = "/api/v1/users", **changes) -> RequestEvent:
    values = {
        "method": "GET",
        "template": template,
        "status": 200,
        "started_at": DEBUT,
        "duration_ms": 4.2,
        "correlation_id": str(uuid.uuid4()),
        "actor": actor,
        "role": "admin",
    }
    return RequestEvent(**(values | changes))


# --- Dépôt ----------------------------------------------------------------------------------


def test_an_entry_is_stored_with_its_types_and_read_back(base, traces):
    acteur = str(uuid.uuid4())
    traces[0].append(acteur)
    audit, _ = open_collections(URL)
    ev = event(acteur, path_params={"user_id": str(uuid.UUID(int=5))})
    audit.insert(build_audit_entry(ev, "traitement"))

    stocke = base.audit_logs.find_one({"actor": acteur})
    assert stocke["ts"].replace(tzinfo=UTC) == DEBUT
    assert stocke["service"] == "traitement"
    assert stocke["action"] == "GET /api/v1/users"
    assert stocke["outcome"] == "ok"
    assert stocke["correlation_id"] == ev.correlation_id
    assert stocke["details"] == {
        "status": 200,
        "duration_ms": 4.2,
        "role": "admin",
        "path_params": {"user_id": str(uuid.UUID(int=5))},
    }


def test_the_validator_of_the_collection_accepts_every_outcome_we_write(base, traces):
    acteur = str(uuid.uuid4())
    traces[0].append(acteur)
    audit, _ = open_collections(URL)
    for status in (200, 401, 403, 404, 422, 500):
        audit.insert(build_audit_entry(event(acteur, status=status), "traitement"))
    lignes = base.audit_logs.find({"actor": acteur}).sort("details.status")
    assert [r["outcome"] for r in lignes] == ["ok", "denied", "denied", "error", "error", "error"]


def test_the_validator_refuses_what_the_application_would_never_write(base):
    """Contre-épreuve : le validateur est bien actif, la preuve ci-dessus n'est pas vide."""
    entree = {"ts": DEBUT, "service": "traitement", "actor": "x", "action": "GET /"}
    with pytest.raises(WriteError) as erreur:
        base.audit_logs.insert_one(entree | {"outcome": "peut-etre"})
    assert erreur.value.code == SCHEMA_REFUSED


def test_the_backend_account_cannot_rewrite_or_erase_the_journal(base):
    """Le journal ne se réécrit pas : le compte n'a que `find` et `insert` sur audit_logs."""
    for operation in (
        lambda: base.audit_logs.update_one({}, {"$set": {"actor": "x"}}),
        lambda: base.audit_logs.delete_many({"actor": "inexistant"}),
        lambda: base.audit_logs.drop(),
    ):
        with pytest.raises(OperationFailure) as erreur:
            operation()
        assert erreur.value.code == UNAUTHORIZED


def test_the_counter_starts_at_one_and_grows_by_one(base, traces):
    point = f"GET /essai/{unique_marker()}"
    traces[1].append(point)
    _, usage = open_collections(URL)
    tranche = bucket_start(DEBUT)
    for _ in range(3):
        usage.increment(point, tranche)
    lignes = list(base.usage_stats.find({"endpoint": point}))
    assert [(r["count"], r["bucket_start"].replace(tzinfo=UTC)) for r in lignes] == [(3, tranche)]


def test_each_hour_has_its_own_row(base, traces):
    point = f"GET /essai/{unique_marker()}"
    traces[1].append(point)
    _, usage = open_collections(URL)
    usage.increment(point, datetime(2026, 10, 20, 8, tzinfo=UTC))
    usage.increment(point, datetime(2026, 10, 20, 9, tzinfo=UTC))
    usage.increment(point, datetime(2026, 10, 20, 9, tzinfo=UTC))
    comptes = [r["count"] for r in base.usage_stats.find({"endpoint": point}).sort("bucket_start")]
    assert comptes == [1, 2]


def test_concurrent_first_calls_lose_no_count(base, traces):
    """Cinquante appels simultanés sur une ligne qui n'existe pas encore : aucun n'est perdu."""
    point = f"GET /essai/{unique_marker()}"
    traces[1].append(point)
    _, usage = open_collections(URL)
    tranche = bucket_start(DEBUT)
    with ThreadPoolExecutor(max_workers=25) as pool:
        list(pool.map(lambda _: usage.increment(point, tranche), range(50)))
    assert base.usage_stats.count_documents({"endpoint": point}) == 1, "une seule ligne"
    assert base.usage_stats.find_one({"endpoint": point})["count"] == 50


def test_the_index_refuses_a_second_row_for_the_same_endpoint_and_hour(base, traces):
    point = f"GET /essai/{unique_marker()}"
    traces[1].append(point)
    base.usage_stats.insert_one({"endpoint": point, "bucket_start": DEBUT, "count": 1})
    with pytest.raises(WriteError) as erreur:
        base.usage_stats.insert_one({"endpoint": point, "bucket_start": DEBUT, "count": 1})
    assert erreur.value.code == DUPLICATE_KEY


# --- Observateur ----------------------------------------------------------------------------


def test_the_observer_writes_both_the_entry_and_the_count(base, traces):
    acteur = str(uuid.uuid4())
    chemin = f"/essai/{unique_marker()}"
    traces[0].append(acteur)
    traces[1].append(f"GET {chemin}")
    audit, usage = open_collections(URL)
    observateur = RecordingObserver(audit, usage, service="traitement", log=lambda *_: None)
    observateur.observe(event(acteur, chemin))
    assert base.audit_logs.count_documents({"actor": acteur}) == 1
    assert base.usage_stats.find_one({"endpoint": f"GET {chemin}"})["count"] == 1


def test_a_mongodb_that_cannot_be_reached_never_breaks_the_response(client, repo):
    """Adresse sans serveur : la réponse du client est inchangée, la perte est comptée."""
    pertes: list[tuple] = []
    audit, usage = open_collections(
        "mongodb://svc_backend:x@127.0.0.1:1/novaria?authSource=novaria"
    )
    observateur = RecordingObserver(
        audit, usage, service="traitement", log=lambda message, fields: pertes.append(fields)
    )
    app.state.observer = observateur
    appelant = repo.make("appelant", Role.ADMIN)
    reponse = client.get("/api/v1/auth/me", headers=bearer(appelant))
    assert reponse.status_code == 200
    assert observateur.dropped == 1
    assert pertes[0]["error"] == "ServerSelectionTimeoutError"
    assert "127.0.0.1" not in str(pertes)
    assert "svc_backend" not in str(pertes)


# --- Application complète -------------------------------------------------------------------


def test_the_application_writes_one_entry_per_authenticated_call_in_mongodb(
    base, traces, secret, repo, indicators
):
    """Le critère d'acceptation, de bout en bout : application → MongoDB → lecture."""
    audit, usage = open_collections(URL)
    app.dependency_overrides[get_user_repository] = lambda: repo
    app.dependency_overrides[get_indicator_repository] = lambda: indicators
    app.state.observer = RecordingObserver(audit, usage, service="traitement", log=lambda *_: None)
    client = TestClient(app)
    avant = counted(base)
    try:
        admin = repo.make("administrateur", Role.ADMIN)
        viewer = repo.make("lecteur", Role.VIEWER)
        traces[0].extend([str(admin.user_id), str(viewer.user_id)])
        appels = [
            (bearer(admin), "/api/v1/auth/me", 200),
            (bearer(admin), "/api/v1/users", 200),
            (bearer(viewer), "/api/v1/users", 403),
            (bearer(admin), f"/api/v1/users/{viewer.user_id}", 200),
        ]
        correlations = []
        for en_tete, chemin, attendu in appels:
            reponse = client.get(chemin, headers=en_tete)
            assert reponse.status_code == attendu
            correlations.append(reponse.headers["X-Correlation-ID"])
        assert client.get("/api/v1/users").status_code == 401, "sans jeton : compté, pas journalisé"
    finally:
        app.dependency_overrides.clear()
        app.state.observer = None

    # Les compteurs sont partagés avec les autres écritures de la base : on compare des écarts.
    apres = counted(base)
    assert {k: apres[k] - avant.get(k, 0) for k in apres if apres[k] != avant.get(k, 0)} == {
        "GET /api/v1/auth/me": 1,
        "GET /api/v1/users": 3,
        "GET /api/v1/users/{user_id}": 1,
    }

    acteurs = [str(admin.user_id), str(viewer.user_id)]
    lignes = list(base.audit_logs.find({"actor": {"$in": acteurs}}).sort("ts"))
    assert [(r["action"], r["details"]["status"], r["outcome"]) for r in lignes] == [
        ("GET /api/v1/auth/me", 200, "ok"),
        ("GET /api/v1/users", 200, "ok"),
        ("GET /api/v1/users", 403, "denied"),
        ("GET /api/v1/users/{user_id}", 200, "ok"),
    ]
    assert [r["correlation_id"] for r in lignes] == correlations
    assert lignes[3]["details"]["path_params"] == {"user_id": str(viewer.user_id)}
    texte = str(lignes)
    for interdit in ("Bearer", "eyJ", "administrateur", "lecteur", "password", "testclient"):
        assert interdit not in texte, interdit


def test_the_observer_of_the_configuration_uses_the_address_of_the_environment(monkeypatch):
    monkeypatch.setenv("AUDIT_MONGO_URL", URL)
    get_settings.cache_clear()
    get_observer.cache_clear()
    try:
        assert isinstance(get_observer(), RecordingObserver)
    finally:
        get_settings.cache_clear()
        get_observer.cache_clear()
