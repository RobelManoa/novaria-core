"""Journal d'audit et compteurs d'usage contre les routes du service (BE-05).

Critère d'acceptation : chaque appel authentifié produit une entrée d'audit.

Les tests partent des routes que le service publie (`app.openapi()`), pas d'une liste écrite à la
main : une route ajoutée plus tard est auditée ou fait échouer ces tests. Pour chaque route et
chaque rôle :
- avec un jeton valide, quelle que soit l'issue (200, 403, 404, 422), exactement une entrée, du bon
  auteur, de la bonne action et de la bonne issue ;
- sans jeton ou avec un jeton illisible, aucune entrée, mais l'appel est compté ;
- aucune entrée ne contient le jeton, le mot de passe, le nom d'utilisateur ni l'adresse.
"""

import json
import uuid

import pytest

from app.main import app
from app.models import Role
from app.services.audit import UNMATCHED, outcome_of
from tests.fakes import PASSWORD, bearer

HEALTH = ("/api/v1/health", "get")
LOGIN = ("/api/v1/auth/login", "post")
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
NEW_USER = {"username": "nouveau", "password": "un-mot-de-passe-long", "role": "viewer"}


def routes() -> list[tuple[str, str]]:
    return sorted(
        (path, method)
        for path, item in app.openapi()["paths"].items()
        if path.startswith("/api/v1")
        for method in item
    )


PROTECTED = [route for route in routes() if route not in (HEALTH, LOGIN)]
IDS = [f"{method.upper()} {path}" for path, method in PROTECTED]
CASES = [(path, method, role) for path, method in PROTECTED for role in Role]
CASE_IDS = [f"{method.upper()} {path} avec {role.value}" for path, method, role in CASES]


def call(client, path: str, method: str, headers: dict | None = None):
    url = path.replace("{user_id}", UNKNOWN_ID).replace("{indicator_id}", UNKNOWN_ID)
    body = NEW_USER if (path, method) == ("/api/v1/users", "post") else None
    return client.request(method.upper(), url, headers=headers or {}, json=body)


def test_the_probe_and_the_login_are_the_only_routes_without_a_token():
    assert len(PROTECTED) + 2 == len(routes())
    assert {HEALTH, LOGIN} <= set(routes())


# --- Avec un jeton valide : une entrée ------------------------------------------------------


@pytest.mark.parametrize(("path", "method", "role"), CASES, ids=CASE_IDS)
def test_every_authenticated_call_produces_exactly_one_audit_entry(
    client, repo, journal, path, method, role
):
    appelant = repo.make("appelant", role)
    reponse = call(client, path, method, bearer(appelant))

    (entry,) = journal.entries
    assert entry["actor"] == str(appelant.user_id)
    assert entry["action"] == f"{method.upper()} {path}"
    assert entry["outcome"] == outcome_of(reponse.status_code)
    assert entry["service"] == "traitement"
    assert entry["details"]["status"] == reponse.status_code
    assert entry["details"]["role"] == role.value
    assert entry["correlation_id"] == reponse.headers["X-Correlation-ID"]
    assert journal.usage.total(entry["action"]) == 1


RESERVED = [
    (path, method)
    for path, method in PROTECTED
    if app.openapi()["paths"][path][method]["x-required-role"] != Role.VIEWER.value
]


def test_some_routes_are_reserved_to_a_higher_role():
    assert RESERVED, "sans route réservée, le test des refus ne vérifierait rien"


@pytest.mark.parametrize(
    ("path", "method"), RESERVED, ids=[f"{m.upper()} {p}" for p, m in RESERVED]
)
def test_a_denied_call_is_audited_as_denied(client, repo, journal, path, method):
    appelant = repo.make("lecteur", Role.VIEWER)
    assert call(client, path, method, bearer(appelant)).status_code == 403
    (entry,) = journal.entries
    assert entry["outcome"] == "denied"
    assert entry["actor"] == str(appelant.user_id)


def test_several_calls_make_several_entries_in_order(client, repo, journal):
    appelant = repo.make("appelant", Role.ADMIN)
    for _ in range(3):
        client.get("/api/v1/auth/me", headers=bearer(appelant))
    client.get("/api/v1/users", headers=bearer(appelant))
    assert [e["action"] for e in journal.entries] == ["GET /api/v1/auth/me"] * 3 + [
        "GET /api/v1/users"
    ]
    assert [e["ts"] for e in journal.entries] == sorted(e["ts"] for e in journal.entries)
    assert sum(journal.usage.counts.values()) == 4
    assert journal.usage.total("GET /api/v1/auth/me") == 3


def test_a_uuid_in_the_path_is_recorded_but_the_counter_key_stays_the_template(
    client, repo, journal
):
    admin = repo.make("administrateur", Role.ADMIN)
    cible = repo.make("cible", Role.VIEWER)
    reponse = client.get(f"/api/v1/users/{cible.user_id}", headers=bearer(admin))
    assert reponse.status_code == 200
    (entry,) = journal.entries
    assert entry["action"] == "GET /api/v1/users/{user_id}"
    assert entry["details"]["path_params"] == {"user_id": str(cible.user_id)}
    assert set(key[0] for key in journal.usage.counts) == {"GET /api/v1/users/{user_id}"}


def test_a_malformed_identifier_in_the_path_is_not_recorded(client, repo, journal):
    admin = repo.make("administrateur", Role.ADMIN)
    reponse = client.get("/api/v1/users/pas-un-uuid", headers=bearer(admin))
    assert reponse.status_code == 422
    (entry,) = journal.entries
    assert "path_params" not in entry["details"]
    assert "pas-un-uuid" not in json.dumps(entry, default=str)


def test_a_call_that_fails_with_a_validation_error_is_audited_as_an_error(client, repo, journal):
    admin = repo.make("administrateur", Role.ADMIN)
    reponse = client.post("/api/v1/users", headers=bearer(admin), json={"username": "x"})
    assert reponse.status_code == 422
    (entry,) = journal.entries
    assert (entry["action"], entry["outcome"]) == ("POST /api/v1/users", "error")


# --- Sans jeton valide : pas d'entrée, mais un compte ---------------------------------------


@pytest.mark.parametrize(("path", "method"), PROTECTED, ids=IDS)
def test_a_call_without_token_writes_no_entry_but_is_counted(client, journal, path, method):
    reponse = call(client, path, method)
    assert reponse.status_code == 401
    assert journal.entries == []
    assert journal.usage.total(f"{method.upper()} {path}") == 1


@pytest.mark.parametrize(
    "header",
    [
        "Basic YWxpY2U6cGFzcw==",
        "Bearer",
        "Bearer pas-un-jeton",
        "Bearer eyJhbGciOiJub25lIn0.e30.",
        "",
    ],
)
def test_an_unreadable_token_writes_no_entry(client, journal, header):
    reponse = client.get("/api/v1/auth/me", headers={"Authorization": header})
    assert reponse.status_code == 401
    assert journal.entries == []
    assert journal.usage.total("GET /api/v1/auth/me") == 1


def test_a_token_signed_with_another_secret_writes_no_entry(client, repo, journal):
    appelant = repo.make("appelant", Role.ADMIN)
    reponse = client.get("/api/v1/auth/me", headers=bearer(appelant, secret="un-autre-secret" * 4))
    assert reponse.status_code == 401
    assert journal.entries == []


def test_a_valid_token_for_a_deleted_account_writes_no_entry(client, repo, journal):
    appelant = repo.make("fantome", Role.ADMIN)
    en_tete = bearer(appelant)
    del repo.users[appelant.user_id]
    assert client.get("/api/v1/auth/me", headers=en_tete).status_code == 401
    assert journal.entries == []


def test_a_valid_token_for_a_disabled_account_writes_no_entry(client, repo, journal):
    appelant = repo.make("desactive", Role.ADMIN)
    en_tete = bearer(appelant)
    appelant.is_active = False
    assert client.get("/api/v1/auth/me", headers=en_tete).status_code == 401
    assert journal.entries == []


# --- Sonde de santé -------------------------------------------------------------------------


def test_the_health_probe_is_neither_audited_nor_counted(client, journal):
    for _ in range(3):
        assert client.get("/api/v1/health").status_code == 200
    assert journal.entries == []
    assert journal.usage.counts == {}


# --- Connexion ------------------------------------------------------------------------------


def test_a_successful_login_is_audited_with_the_account_as_actor(client, repo, journal):
    compte = repo.make("operateur1", Role.OPERATOR)
    reponse = client.post(
        "/api/v1/auth/login", json={"username": "operateur1", "password": PASSWORD}
    )
    assert reponse.status_code == 200
    (entry,) = journal.entries
    assert entry["actor"] == str(compte.user_id)
    assert entry["action"] == "POST /api/v1/auth/login"
    assert entry["outcome"] == "ok"


@pytest.mark.parametrize(
    ("username", "password"),
    [("operateur1", "mauvais-mot-de-passe"), ("inconnu", PASSWORD)],
    ids=["mot de passe faux", "compte inconnu"],
)
def test_a_refused_login_is_audited_as_anonymous_and_denied(
    client, repo, journal, username, password
):
    repo.make("operateur1", Role.OPERATOR)
    reponse = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert reponse.status_code == 401
    (entry,) = journal.entries
    assert (entry["actor"], entry["outcome"]) == ("anonymous", "denied")
    assert entry["action"] == "POST /api/v1/auth/login"


def test_a_refused_login_of_a_disabled_account_gives_the_same_entry(client, repo, journal):
    repo.make("desactive", Role.OPERATOR, active=False)
    reponse = client.post(
        "/api/v1/auth/login", json={"username": "desactive", "password": PASSWORD}
    )
    assert reponse.status_code == 401
    (entry,) = journal.entries
    assert (entry["actor"], entry["outcome"]) == ("anonymous", "denied")


def test_a_login_with_an_invalid_body_is_audited_as_an_error(client, journal):
    reponse = client.post("/api/v1/auth/login", json={"username": "x"})
    assert reponse.status_code == 422
    (entry,) = journal.entries
    assert (entry["actor"], entry["outcome"]) == ("anonymous", "error")


# --- Chemins inconnus -----------------------------------------------------------------------


def test_an_unknown_path_is_counted_under_one_key_and_not_audited(client, journal):
    for chemin in ("/api/v1/nope", "/etc/passwd", "/api/v1/users/a/b/c"):
        assert client.get(chemin).status_code == 404
    assert journal.entries == []
    assert journal.usage.total(f"GET {UNMATCHED}") == 3
    assert len(journal.usage.counts) == 1


def test_an_unknown_path_is_not_audited_even_with_a_valid_token(client, repo, journal):
    appelant = repo.make("appelant", Role.ADMIN)
    assert client.get("/api/v1/nope", headers=bearer(appelant)).status_code == 404
    assert journal.entries == []
    assert journal.usage.total(f"GET {UNMATCHED}") == 1


def test_a_wrong_method_on_a_known_path_is_counted_without_a_token(client, journal):
    assert client.delete("/api/v1/users").status_code == 405
    assert journal.entries == []
    assert journal.usage.total("DELETE /api/v1/users") == 1


# --- Aucun secret, aucune donnée personnelle ------------------------------------------------


def test_nothing_secret_or_personal_reaches_the_journal(client, repo, journal):
    admin = repo.make("administrateur-secret", Role.ADMIN, password="le-mot-de-passe-de-l-admin")
    en_tete = bearer(admin)
    jeton = en_tete["Authorization"].split()[1]
    client.post(
        "/api/v1/auth/login",
        json={"username": "administrateur-secret", "password": "le-mot-de-passe-de-l-admin"},
        headers={
            "User-Agent": "Navigateur-Tres-Identifiable/9.9",
            "X-Forwarded-For": "203.0.113.7",
        },
    )
    client.post(
        "/api/v1/auth/login", json={"username": "pirate@example.org", "password": "tentative-12"}
    )
    client.post(
        "/api/v1/users",
        headers=en_tete | {"User-Agent": "Navigateur-Tres-Identifiable/9.9"},
        json={
            "username": "nouvel-utilisateur",
            "password": "mot-de-passe-du-nouveau",
            "role": "viewer",
        },
    )
    client.get(
        f"/api/v1/users/{uuid.uuid4()}?token={jeton}&password=abc&email=a@b.c", headers=en_tete
    )
    client.get(f"/api/v1/users/{jeton}", headers=en_tete)
    client.get(f"/api/v1/indicators/{jeton}", headers=en_tete)

    assert len(journal.entries) == 6
    texte = json.dumps([journal.entries, [list(k) for k in journal.usage.counts]], default=str)
    for interdit in (
        jeton,
        "Bearer",
        "le-mot-de-passe-de-l-admin",
        "tentative-12",
        "mot-de-passe-du-nouveau",
        "administrateur-secret",
        "pirate@example.org",
        "nouvel-utilisateur",
        "Navigateur-Tres-Identifiable",
        "203.0.113.7",
        "testclient",
        "testserver",
        "a@b.c",
        "password",
        "argon2",
    ):
        assert interdit not in texte, interdit


def test_the_fields_of_every_entry_are_the_closed_list(client, repo, journal):
    appelant = repo.make("appelant", Role.ADMIN)
    for path, method in PROTECTED:
        call(client, path, method, bearer(appelant))
    client.post("/api/v1/auth/login", json={"username": "appelant", "password": PASSWORD})
    assert len(journal.entries) == len(PROTECTED) + 1
    for entry in journal.entries:
        assert set(entry) <= {
            "ts",
            "service",
            "actor",
            "action",
            "outcome",
            "correlation_id",
            "details",
        }
        assert set(entry["details"]) <= {"status", "duration_ms", "role", "path_params"}
        assert entry["outcome"] in {"ok", "denied", "error"}
        assert entry["ts"].tzinfo is not None
