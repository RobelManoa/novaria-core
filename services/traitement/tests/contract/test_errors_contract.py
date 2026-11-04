"""Chaque erreur documentée dans le contrat est testée (BE-06).

Critère d'acceptation : chaque erreur documentée dans le contrat est testée.

Les contrats `api-metier` et `traitement` (`contracts/openapi/`) disent, pour chaque opération, les
erreurs qu'elle peut renvoyer. Ces tests partent d'eux, pas d'une liste écrite à la main :
- pour chaque opération que le service implémente et chaque erreur que le contrat lui attribue, un
  appel provoque cette erreur, et la réponse a le bon code HTTP, le bon `code` stable, le type de
  contenu `application/problem+json` et un corps conforme au schéma `Problem` ;
- une erreur documentée sans test fait échouer la suite, sauf un cas écrit ici avec sa raison
  (`403` d'une route ouverte au rôle le plus bas). Le `429` de la connexion est testé depuis
  BE-08 : la limite est dépassée pour de bon, `Retry-After` est lu ;
- les erreurs que le service déclare dans `/openapi.json` sont exactement celles du contrat ;
- les erreurs imprévues (`5XX`) sont provoquées sur toutes les opérations : le client ne voit
  aucun détail technique et la réponse porte l'identifiant de corrélation.
"""

import uuid

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.config import get_settings
from app.core.errors import (
    CONFLICT,
    FORBIDDEN,
    INTERNAL_ERROR,
    INVALID_CREDENTIALS,
    NOT_FOUND,
    RATE_LIMITED,
    UNAUTHENTICATED,
    UPSTREAM_UNAVAILABLE,
    VALIDATION_ERROR,
)
from app.db.session import get_indicator_repository, get_user_repository
from app.main import app
from app.models import Role
from app.schemas.errors import Problem
from app.services.auth import ROLE_LEVEL
from tests.contract.conftest import CONTRACTS
from tests.fakes import PASSWORD, bearer
from tests.openapi_checks import API, PROBLEM, TRAITEMENT, check, load
from tests.scene import UNKNOWN_ID, Scene

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
LOGIN = "/api/v1/auth/login"
USERS = "/api/v1/users"
INDICATORS = "/api/v1/indicators"
PROBLEM_KEYS = {"type", "title", "status", "code", "detail", "correlation_id", "errors"}
LOWEST_ROLE = min(Role, key=lambda role: ROLE_LEVEL[role])


# --- Ce que disent les contrats ---------------------------------------------------------------


def contract_operations() -> dict[tuple[str, str], dict]:
    operations: dict[tuple[str, str], dict] = {}
    for contract in (API, TRAITEMENT):
        for path, item in contract["paths"].items():
            for method, operation in item.items():
                if method in HTTP_METHODS:
                    operations[(method, path)] = operation
    return operations


def implemented_operations() -> list[tuple[str, str]]:
    served = {(method, path) for path, item in app.openapi()["paths"].items() for method in item}
    return sorted(served)


CONTRACT = contract_operations()
IMPLEMENTED = implemented_operations()


def documented_errors(method: str, path: str) -> list[str]:
    """Codes d'erreur (`"401"`, `"5XX"`…) que le contrat attribue à l'opération."""
    return sorted(code for code in CONTRACT[(method, path)]["responses"] if code[0] in "45")


# Codes `code` admis pour chaque réponse d'erreur du contrat (`common.yaml`, section responses).
ALLOWED_CODES = {
    "401": {UNAUTHENTICATED.code, INVALID_CREDENTIALS.code},
    "403": {FORBIDDEN.code},
    "404": {NOT_FOUND.code},
    "409": {CONFLICT.code},
    "422": {VALIDATION_ERROR.code},
    "429": {RATE_LIMITED.code},
    "500": {INTERNAL_ERROR.code},
    "503": {UPSTREAM_UNAVAILABLE.code},
}
# Une réponse du contrat peut couvrir plusieurs codes HTTP : `ServerError` est écrit `5XX`.
COVERS = {"5XX": ["500", "503"]}


def required_role(method: str, path: str) -> Role | None:
    value = app.openapi()["paths"][path][method].get("x-required-role")
    return Role(value) if value else None


def exemption(method: str, path: str, status: str) -> str | None:
    """Raison pour laquelle une erreur documentée ne peut pas être provoquée."""
    if status == "403" and required_role(method, path) == LOWEST_ROLE:
        return f"le rôle `{LOWEST_ROLE.value}` est le plus bas : personne n'a moins de droits"
    return None


# --- Mise en scène ----------------------------------------------------------------------------


# Un appel par erreur documentée. La clé est le code HTTP du contrat ; les erreurs `5XX` sont
# provoquées plus bas, pour toutes les opérations.
PROVOKERS = {
    ("post", LOGIN): {
        "401": lambda s: s.request(
            "post", LOGIN, json={"username": "inconnu", "password": PASSWORD}
        ),
        "422": lambda s: s.request("post", LOGIN, json={}),
        "429": lambda s: exceed_the_login_limit(s),
    },
    ("get", "/api/v1/auth/me"): {
        "401": lambda s: s.request("get", "/api/v1/auth/me"),
    },
    ("get", USERS): {
        "401": lambda s: s.request("get", USERS),
        "403": lambda s: s.request("get", USERS, role=Role.VIEWER),
        "422": lambda s: s.request("get", USERS, role=Role.ADMIN, params={"limit": 0}),
    },
    ("post", USERS): {
        "401": lambda s: s.request("post", USERS, json={}),
        "403": lambda s: s.request("post", USERS, role=Role.OPERATOR, json={}),
        "409": lambda s: duplicate_user(s),
        "422": lambda s: s.request("post", USERS, role=Role.ADMIN, json={"username": "x"}),
    },
    ("get", f"{USERS}/{{user_id}}"): {
        "401": lambda s: s.request("get", f"{USERS}/{{user_id}}"),
        "403": lambda s: s.request("get", f"{USERS}/{{user_id}}", role=Role.VIEWER),
        "404": lambda s: s.request("get", f"{USERS}/{{user_id}}", role=Role.ADMIN),
        "422": lambda s: s.client.get(f"{USERS}/pas-un-uuid", headers=s.token(Role.ADMIN)),
    },
    ("get", INDICATORS): {
        "401": lambda s: s.request("get", INDICATORS),
        "422": lambda s: s.request("get", INDICATORS, role=Role.VIEWER, params={"limit": 0}),
    },
    ("get", f"{INDICATORS}/latest"): {
        "401": lambda s: s.request("get", f"{INDICATORS}/latest"),
        "422": lambda s: s.request(
            "get", f"{INDICATORS}/latest", role=Role.VIEWER, params={"intersection_id": "ici"}
        ),
    },
    ("get", f"{INDICATORS}/{{indicator_id}}"): {
        "401": lambda s: s.request("get", f"{INDICATORS}/{{indicator_id}}"),
        "404": lambda s: s.request("get", f"{INDICATORS}/{{indicator_id}}", role=Role.VIEWER),
    },
}


def exceed_the_login_limit(scene: Scene):
    """Autant d'échecs que la configuration en tolère sur un identifiant, puis un de trop."""
    attempt = {"username": "inconnu", "password": PASSWORD}
    for _ in range(get_settings().login_max_failures):
        assert scene.request("post", LOGIN, json=attempt).status_code == 401
    return scene.request("post", LOGIN, json=attempt)


def duplicate_user(scene: Scene):
    admin = scene.token(Role.ADMIN)
    body = {"username": "double", "password": "un-mot-de-passe-long", "role": "viewer"}
    assert scene.client.post(USERS, headers=admin, json=body).status_code == 201
    return scene.client.post(USERS, headers=admin, json=body)


def assert_problem(response, status: int, codes: set[str]) -> dict:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    check(body, PROBLEM)
    assert set(body) <= PROBLEM_KEYS, set(body) - PROBLEM_KEYS
    assert body["status"] == status
    assert body["code"] in codes
    assert body["correlation_id"] == response.headers["X-Correlation-ID"]
    return body


# --- Chaque erreur documentée a un test -------------------------------------------------------


def test_the_service_implements_the_operations_we_provoke_errors_on():
    assert set(PROVOKERS) <= set(IMPLEMENTED)
    assert set(IMPLEMENTED) <= set(CONTRACT), "une route du service n'est pas dans les contrats"


def test_every_documented_error_has_a_test_or_a_written_reason_why_not():
    """Une erreur ajoutée au contrat, ou une opération ajoutée au service, fait échouer ce test."""
    missing = []
    for method, path in IMPLEMENTED:
        for status in documented_errors(method, path):
            if status in COVERS or exemption(method, path, status):
                continue
            if status not in PROVOKERS.get((method, path), {}):
                missing.append(f"{method.upper()} {path} {status}")
    assert missing == [], f"erreurs documentées sans test : {missing}"


def test_no_test_is_kept_for_an_error_the_contract_no_longer_documents():
    stale = [
        f"{method.upper()} {path} {status}"
        for (method, path), by_status in PROVOKERS.items()
        for status in by_status
        if status not in CONTRACT[(method, path)]["responses"]
    ]
    assert stale == []


def test_the_only_errors_without_a_test_are_the_written_exemptions():
    exempt = {
        (method, path, status)
        for method, path in IMPLEMENTED
        for status in documented_errors(method, path)
        if exemption(method, path, status)
    }
    assert exempt == {
        ("get", INDICATORS, "403"),
        ("get", f"{INDICATORS}/latest", "403"),
        ("get", f"{INDICATORS}/{{indicator_id}}", "403"),
    }
    assert LOWEST_ROLE == Role.VIEWER, "un rôle plus bas rend ces 403 testables"


CASES = [
    (method, path, status)
    for (method, path), by_status in PROVOKERS.items()
    for status in sorted(by_status)
]
CASE_IDS = [f"{method.upper()} {path} {status}" for method, path, status in CASES]


@pytest.mark.parametrize(("method", "path", "status"), CASES, ids=CASE_IDS)
def test_a_documented_error_is_produced_with_the_documented_status_code_and_body(
    scene, method, path, status
):
    response = PROVOKERS[(method, path)][status](scene)
    body = assert_problem(response, int(status), ALLOWED_CODES[status])
    if status == "401":
        wanted = INVALID_CREDENTIALS if path == LOGIN else UNAUTHENTICATED
        assert body["code"] == wanted.code
        if path != LOGIN:
            assert response.headers["WWW-Authenticate"] == "Bearer"
    if status == "429":
        assert int(response.headers["Retry-After"]) >= 1, "le client sait combien attendre"
    if status == "422":
        assert body["errors"], "chaque champ fautif est listé"
        for item in body["errors"]:
            assert item["field"].split(".")[0] in {"body", "query", "path"}
            assert item["message"]


# --- Le service déclare les erreurs du contrat -----------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"), IMPLEMENTED, ids=[f"{m.upper()} {p}" for m, p in IMPLEMENTED]
)
def test_the_responses_the_service_declares_are_those_of_the_contract(method, path):
    declared = set(app.openapi()["paths"][path][method]["responses"])
    expected = set(CONTRACT[(method, path)]["responses"])
    assert declared == expected, (
        f"déclarées seulement par le service : {sorted(declared - expected)} ; "
        f"seulement par le contrat : {sorted(expected - declared)}"
    )


@pytest.mark.parametrize(
    ("method", "path"), IMPLEMENTED, ids=[f"{m.upper()} {p}" for m, p in IMPLEMENTED]
)
def test_every_declared_error_is_described_as_a_problem(method, path):
    responses = app.openapi()["paths"][path][method]["responses"]
    for status, response in responses.items():
        if status[0] in "45":
            assert list(response["content"]) == ["application/problem+json"], status
            reference = response["content"]["application/problem+json"]["schema"]["$ref"]
            assert reference == "#/components/schemas/Problem"


def test_the_problem_model_has_the_codes_of_the_contract():
    common = load(CONTRACTS / "openapi" / "common.yaml")["components"]["schemas"]["Problem"]
    codes = list(Problem.model_json_schema()["properties"]["code"]["enum"])
    assert codes == common["properties"]["code"]["enum"]
    assert set(Problem.model_json_schema()["properties"]) == set(common["properties"])
    assert set(Problem.model_json_schema()["required"]) == set(common["required"])


def test_fastapi_default_validation_schemas_are_not_published():
    schemas = app.openapi()["components"]["schemas"]
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas
    assert "Problem" in schemas


# --- Erreurs imprévues (5XX) sur toutes les opérations ---------------------------------------


def broken(error: Exception):
    def dependency():
        raise error

    return dependency


def serve_with_failing_database(scene, method: str, path: str, error: Exception):
    """Un appel authentifié, valide, dont la base de données échoue."""
    headers = scene.token(Role.ADMIN)
    app.dependency_overrides[get_user_repository] = broken(error)
    url = path.replace("{user_id}", UNKNOWN_ID).replace("{indicator_id}", "inconnu")
    body = {"username": "u", "password": PASSWORD} if path == LOGIN else None
    if (method, path) == ("post", USERS):
        body = {"username": "nouveau", "password": "un-mot-de-passe-long", "role": "viewer"}
    return scene.client.request(method.upper(), url, headers=headers, json=body)


def unreachable() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("connection refused : postgresql://u:pw@h"))


DATABASE_OPERATIONS = [(m, p) for m, p in IMPLEMENTED if p != "/api/v1/health"]
DATABASE_IDS = [f"{m.upper()} {p}" for m, p in DATABASE_OPERATIONS]


@pytest.mark.parametrize(("method", "path"), DATABASE_OPERATIONS, ids=DATABASE_IDS)
def test_an_unexpected_failure_gives_a_500_without_any_technical_detail(
    scene, method, path, caplog
):
    secret = f"mongodb://svc:{uuid.uuid4()}@interne"
    response = serve_with_failing_database(scene, method, path, RuntimeError(secret))
    body = assert_problem(response, 500, {INTERNAL_ERROR.code})
    assert secret not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text
    assert body["title"] == INTERNAL_ERROR.title
    records = [r for r in caplog.records if r.getMessage() == "erreur interne non gérée"]
    assert [r.fields["error"] for r in records] == ["RuntimeError"], "la cause est dans le journal"
    assert secret not in str(records[0].fields)


def saturated() -> PoolTimeoutError:
    return PoolTimeoutError("QueuePool limit of size 5 overflow 10 reached : postgresql://u:pw@h")


@pytest.mark.parametrize(("method", "path"), DATABASE_OPERATIONS, ids=DATABASE_IDS)
@pytest.mark.parametrize("error", [unreachable, saturated], ids=["injoignable", "saturée"])
def test_an_unreachable_or_saturated_database_gives_a_503_without_the_address(
    scene, method, path, error
):
    response = serve_with_failing_database(scene, method, path, error())
    body = assert_problem(response, 503, {UPSTREAM_UNAVAILABLE.code})
    assert "postgresql" not in response.text
    assert "pw" not in body["detail"]
    assert "QueuePool" not in response.text


@pytest.mark.parametrize(
    ("method", "path"),
    [(m, p) for m, p in IMPLEMENTED if p.startswith(INDICATORS)],
    ids=[f"{m.upper()} {p}" for m, p in IMPLEMENTED if p.startswith(INDICATORS)],
)
@pytest.mark.parametrize(
    ("error", "status"), [(RuntimeError("x"), 500), (unreachable(), 503)], ids=["500", "503"]
)
def test_a_failing_warehouse_is_reported_like_a_failing_accounts_database(
    scene, method, path, error, status
):
    headers = scene.token(Role.VIEWER)
    app.dependency_overrides[get_indicator_repository] = broken(error)
    url = path.replace("{indicator_id}", "inconnu")
    response = scene.client.request(method.upper(), url, headers=headers)
    assert_problem(response, status, ALLOWED_CODES[str(status)])


@pytest.mark.parametrize(
    ("error", "status"), [(RuntimeError("x"), 500), (unreachable(), 503)], ids=["500", "503"]
)
def test_an_authenticated_call_that_ends_in_a_server_error_is_audited_with_that_status(
    scene, journal, error, status
):
    """L'audit (BE-05) est à l'extérieur de l'intergiciel des erreurs imprévues : il voit le 500."""
    headers = scene.token(Role.VIEWER)
    app.dependency_overrides[get_indicator_repository] = broken(error)
    assert scene.client.get(INDICATORS, headers=headers).status_code == status
    (entry,) = journal.entries
    assert entry["action"] == f"GET {INDICATORS}"
    assert (entry["outcome"], entry["details"]["status"]) == ("error", status)


def test_the_health_probe_failure_is_a_500_too(scene, monkeypatch):
    def failing():
        raise RuntimeError("configuration illisible")

    monkeypatch.setattr("app.api.v1.health.get_settings", failing)
    assert_problem(scene.client.get("/api/v1/health"), 500, {INTERNAL_ERROR.code})


def test_a_response_that_does_not_match_its_model_is_a_500_not_a_leak(scene, repo, monkeypatch):
    """Si le code renvoie un objet incomplet, rien de l'objet ne sort : la réponse est refusée."""
    from app.api.v1 import users

    broken_user = repo.make("cassé", Role.ADMIN)
    broken_user.password_hash = "$argon2id$empreinte-qui-ne-doit-jamais-sortir"
    broken_user.role = "rôle-inconnu"
    monkeypatch.setattr(users.UserService, "get", lambda self, user_id: broken_user)
    response = scene.client.get(
        f"{USERS}/{UNKNOWN_ID}", headers=bearer(repo.make("lui", Role.ADMIN))
    )
    assert_problem(response, 500, {INTERNAL_ERROR.code})
    assert "empreinte" not in response.text
