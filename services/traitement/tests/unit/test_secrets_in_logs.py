"""Aucun secret dans les journaux (BE-08) : le critère « aucun secret en clair dans les journaux ».

Deux niveaux, testés séparément :
1. la discipline du code : sur chaque parcours (connexion réussie ou refusée, jeton faux,
   validation, base en panne, erreur imprévue, limite de débit), les lignes que le code écrit,
   **sans** le filet de masquage, ne contiennent ni secret de configuration, ni mot de passe,
   ni jeton, ni empreinte ;
2. le filet (`app/core/redaction.py`) : une ligne qui en contiendrait malgré tout, par exemple le
   message d'une bibliothèque, sort masquée.
Les valeurs d'essai sont générées à l'exécution : aucun secret, même factice, n'est écrit ici.
"""

import json
import logging
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from sqlalchemy.exc import OperationalError

from app.api.deps import get_user_repository
from app.core.config import get_settings
from app.core.logs import JsonFormatter, configure_logging
from app.core.redaction import (
    MASK,
    RedactingFormatter,
    install_redaction,
    redact,
    secret_values,
)
from app.main import app
from tests.fakes import PASSWORD

LOGIN = "/api/v1/auth/login"
SERVICE = Path(__file__).resolve().parents[2]


@pytest.fixture
def credentials(monkeypatch):
    """Des secrets de forme réaliste, présents dans l'environnement comme en exploitation."""
    values = {
        "jwt": secrets.token_urlsafe(48),
        "pg": secrets.token_urlsafe(24),
        "mongo": secrets.token_urlsafe(24),
        "admin": secrets.token_urlsafe(24),
    }
    monkeypatch.setenv("JWT_SECRET", values["jwt"])
    monkeypatch.setenv(
        "APP_DATABASE_URL", f"postgresql+psycopg://svc_app:{values['pg']}@postgres:5432/novaria"
    )
    monkeypatch.setenv(
        "POSTGRES_URL", f"postgresql+psycopg://svc_traitement:{values['pg']}@postgres:5432/novaria"
    )
    monkeypatch.setenv(
        "AUDIT_MONGO_URL",
        f"mongodb://svc_backend:{values['mongo']}@mongo:27017/novaria?authSource=novaria",
    )
    monkeypatch.setenv("MONGO_PASSWORD_BACKEND", values["mongo"])
    monkeypatch.setenv("POSTGRES_PASSWORD", values["admin"])
    get_settings.cache_clear()
    yield values
    get_settings.cache_clear()


@pytest.fixture
def raw_lines(caplog):
    """Les lignes JSON telles que le code les écrit, avant tout masquage."""
    caplog.set_level(logging.DEBUG)
    formatter = JsonFormatter("traitement")

    def lines() -> str:
        # `httpx` est le client du `TestClient`, pas le service : il journalise l'adresse appelée,
        # query string comprise. Le service n'écrit jamais la query string (CorrelationMiddleware).
        records = [
            r for r in caplog.records if not r.name.startswith(("httpx", "httpcore", "asyncio"))
        ]
        return "\n".join(formatter.format(record) for record in records)

    return lines


def everything_secret(credentials, *extra: str) -> list[str]:
    return [*credentials.values(), PASSWORD, "$argon2", *extra]


def assert_clean(text: str, secrets_: list[str]) -> None:
    for secret in secrets_:
        assert secret not in text, f"un secret est dans le journal : {secret[:4]}..."
        assert quote(secret, safe="") not in text


# --- 1. La discipline du code -----------------------------------------------------------------


def test_a_successful_login_and_the_calls_that_follow_write_no_secret_and_no_token(
    client, repo, credentials, raw_lines, journal
):
    repo.make("alice")
    login = client.post(LOGIN, json={"username": "alice", "password": PASSWORD})
    token = login.json()["access_token"]
    client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    client.get(f"/api/v1/indicators?token={token}")
    wanted = everything_secret(credentials, token)
    assert_clean(raw_lines(), wanted)
    assert_clean(json.dumps(journal.entries, default=str), wanted)  # le journal d'audit aussi


def test_refused_logins_write_neither_the_attempted_password_nor_the_name(
    client, repo, credentials, raw_lines, journal
):
    repo.make("alice")
    attempted = secrets.token_urlsafe(20)
    client.post(LOGIN, json={"username": "alice", "password": attempted})
    client.post(LOGIN, json={"username": "inconnu-de-tous", "password": attempted})
    wanted = everything_secret(credentials, attempted)
    assert_clean(raw_lines(), wanted)
    assert_clean(json.dumps(journal.entries, default=str), wanted)


def test_a_password_refused_by_validation_is_written_nowhere_and_not_echoed(
    client, credentials, raw_lines, journal
):
    too_long = secrets.token_urlsafe(200)
    response = client.post(LOGIN, json={"username": "alice", "password": too_long})
    assert response.status_code == 422
    assert too_long not in response.text
    wanted = everything_secret(credentials, too_long)
    assert_clean(raw_lines(), wanted)
    assert_clean(json.dumps(journal.entries, default=str), wanted)


def test_a_bad_token_is_not_written(client, credentials, raw_lines, journal):
    forged = (
        "eyJ"
        + secrets.token_urlsafe(20)
        + "."
        + secrets.token_urlsafe(30)
        + "."
        + secrets.token_urlsafe(20)
    )
    client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    wanted = everything_secret(credentials, forged)
    assert_clean(raw_lines(), wanted)
    assert_clean(json.dumps(journal.entries, default=str), wanted)


def test_the_limit_of_the_login_writes_no_secret(client, repo, credentials, raw_lines):
    repo.make("alice")
    for _ in range(7):
        client.post(LOGIN, json={"username": "alice", "password": PASSWORD + "x"})
    assert "connexion limitée" in raw_lines()
    assert_clean(raw_lines(), everything_secret(credentials))


def test_a_database_failure_writes_the_type_of_the_error_not_its_message(
    client, repo, credentials, raw_lines
):
    url = f"postgresql+psycopg://svc_app:{credentials['pg']}@postgres:5432/novaria"

    def broken():
        raise OperationalError("SELECT 1", {}, Exception(f"connexion refusée : {url}"))

    app.dependency_overrides[get_user_repository] = broken
    response = client.post(LOGIN, json={"username": "alice", "password": PASSWORD})
    assert response.status_code == 503
    assert credentials["pg"] not in response.text
    assert "base injoignable" in raw_lines()
    assert_clean(raw_lines(), everything_secret(credentials, url))


def test_an_unexpected_error_writes_its_type_and_stack_not_its_message(
    client, credentials, raw_lines
):
    leaked = f"valeur interne {credentials['jwt']}"

    def broken():
        raise RuntimeError(leaked)

    app.dependency_overrides[get_user_repository] = broken
    response = client.post(LOGIN, json={"username": "alice", "password": PASSWORD})
    assert response.status_code == 500
    assert credentials["jwt"] not in response.text
    assert "RuntimeError" in raw_lines()
    assert_clean(raw_lines(), everything_secret(credentials))


# --- 2. Le filet : ce qui échapperait au code -------------------------------------------------


@pytest.fixture
def written(credentials, capsys):
    """Le journal réellement écrit sur la sortie standard, filet installé comme dans `app.main`."""
    configure_logging("traitement", "DEBUG")
    install_redaction()

    def write(message: str, **fields) -> str:
        capsys.readouterr()
        logging.getLogger("app.test").warning(message, extra={"fields": fields})
        return capsys.readouterr().out

    return write


def test_a_secret_written_by_mistake_in_a_message_comes_out_masked(written, credentials):
    out = written(f"le secret est {credentials['jwt']} ; le mot de passe {credentials['admin']}")
    assert_clean(out, [credentials["jwt"], credentials["admin"]])
    assert MASK in out
    assert json.loads(out)["message"].startswith(
        "le secret est ***"
    )  # la ligne reste du JSON valide


def test_a_configured_connection_address_comes_out_masked_whole_wherever_it_is(
    written, credentials
):
    url = f"postgresql+psycopg://svc_app:{credentials['pg']}@postgres:5432/novaria"
    out = written("échec", url=url, detail=[url], nested={"dsn": url})
    assert_clean(out, [credentials["pg"], url])
    assert json.loads(out)["nested"] == {"dsn": MASK}


def test_an_address_the_configuration_does_not_know_keeps_its_host_and_loses_its_password(written):
    password = secrets.token_urlsafe(16)
    out = written("échec", url=f"mongodb://autre:{password}@hote-inconnu:27017/base")
    assert password not in out
    assert json.loads(out)["url"] == "mongodb://autre:***@hote-inconnu:27017/base"


def test_a_secret_in_an_exception_message_comes_out_masked(credentials, capsys):
    configure_logging("traitement", "DEBUG")
    install_redaction()
    capsys.readouterr()
    try:
        raise RuntimeError(f"échec avec {credentials['mongo']}")
    except RuntimeError:
        logging.getLogger("app.test").exception("panne")
    out = capsys.readouterr().out
    assert_clean(out, [credentials["mongo"]])
    assert "RuntimeError" in out


def test_secrets_with_characters_json_escapes_are_still_found(monkeypatch, capsys):
    awkward = 'p"a\\ss/wörd:+&' + secrets.token_urlsafe(8)
    monkeypatch.setenv("SERVICE_PASSWORD", awkward)
    configure_logging("traitement", "DEBUG")
    install_redaction()
    capsys.readouterr()
    logging.getLogger("app.test").warning("valeur %s", awkward)
    out = capsys.readouterr().out
    assert awkward not in out
    assert json.dumps(awkward)[1:-1] not in out
    assert quote(awkward, safe="") not in out
    assert json.loads(out)["message"] == f"valeur {MASK}"


def test_the_secrets_of_the_env_file_are_masked_even_when_not_exported(
    tmp_path, monkeypatch, capsys
):
    in_file = secrets.token_urlsafe(48)
    (tmp_path / ".env").write_text(f"JWT_SECRET={in_file}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        configure_logging("traitement", "DEBUG")
        install_redaction()
        capsys.readouterr()
        logging.getLogger("app.test").warning("clé %s", in_file)
        assert in_file not in capsys.readouterr().out
    finally:
        get_settings.cache_clear()


def test_an_invalid_configuration_does_not_break_the_logging(monkeypatch, capsys):
    monkeypatch.setenv("JWT_SECRET", "trop-court")
    get_settings.cache_clear()
    try:
        configure_logging("traitement", "DEBUG")
        install_redaction()
        capsys.readouterr()
        logging.getLogger("app.test").warning("toujours écrit")
        assert "toujours écrit" in capsys.readouterr().out
    finally:
        get_settings.cache_clear()


# --- Le masquage lui-même ---------------------------------------------------------------------


def test_a_bearer_header_and_a_jwt_shaped_value_are_masked_without_knowing_them():
    jwt_like = (
        "eyJ"
        + secrets.token_urlsafe(20)
        + "."
        + secrets.token_urlsafe(30)
        + "."
        + secrets.token_urlsafe(20)
    )
    text = redact(f"Authorization: Bearer {jwt_like} puis seul {jwt_like}", [])
    assert jwt_like not in text
    assert text.count(MASK) == 2
    assert "Authorization: Bearer ***" in text


def test_url_credentials_are_masked_but_not_the_rest_of_the_address():
    password = secrets.token_urlsafe(12)
    text = redact(f"mongodb://compte:{password}@hote:27017/base?authSource=base", [])
    assert text == "mongodb://compte:***@hote:27017/base?authSource=base"


def test_an_address_without_password_and_ordinary_text_are_left_alone():
    plain = "GET /api/v1/health 200 postgresql://hote:5432/base http://localhost:8080 a@b.c"
    assert redact(plain, []) == plain


@pytest.mark.parametrize("short", ["", "x", "abc123", "1234567"])
def test_values_shorter_than_eight_characters_are_not_searched(short):
    assert short not in secret_values({"SERVICE_PASSWORD": short}) or short == ""
    assert secret_values({"SERVICE_PASSWORD": short}) == []


def test_only_variables_that_look_secret_are_collected_and_the_host_of_an_address_is_not():
    password, in_url, token, key = (secrets.token_urlsafe(12) for _ in range(4))
    values = secret_values(
        {
            "ENVIRONMENT": "localisation",
            "LOG_LEVEL": "INFORMATION",
            "DB_PASSWORD": password,
            "POSTGRES_URL": f"postgresql://compte:{in_url}@hote-de-base/novaria",
            "API_TOKEN": token,
            "SIGNING_KEY": key,
        }
    )
    assert {password, in_url, token, key} <= set(values)
    assert not {"localisation", "INFORMATION", "hote-de-base", "compte"} & set(values)


def test_a_malformed_address_does_not_break_the_collection():
    password = secrets.token_urlsafe(12)
    assert secret_values({"BROKEN_URL": "http://[::1/x", "SERVICE_PASSWORD": password}) == [
        password
    ]


def test_the_longest_values_are_searched_first_so_an_address_is_masked_whole():
    password = secrets.token_urlsafe(16)
    url = f"postgresql://compte:{password}@hote/base"
    ordered = secret_values({"DB_URL_SECRET": url, "DB_PASSWORD": password})
    assert ordered.index(url) < ordered.index(password)
    assert redact(f"erreur sur {url}", ordered) == f"erreur sur {MASK}"


def test_the_formatter_wraps_without_changing_the_content_of_a_clean_line():
    inner = JsonFormatter("traitement")
    record = logging.LogRecord("app.x", logging.INFO, __file__, 1, "bonjour %s", ("monde",), None)
    assert RedactingFormatter(inner).format(record) == inner.format(record)


def test_installing_twice_does_not_stack_formatters():
    configure_logging("traitement", "INFO")
    install_redaction()
    install_redaction()
    for handler in logging.getLogger().handlers:
        assert isinstance(handler.formatter, RedactingFormatter)
        assert not isinstance(handler.formatter.inner, RedactingFormatter)


def test_the_application_installs_the_net_at_startup():
    """Dans un interpréteur neuf : ce que d'autres tests ont installé avant ne compte pas."""
    code = (
        "import logging, app.main\n"
        "from app.core.redaction import RedactingFormatter\n"
        "handlers = logging.getLogger().handlers\n"
        "ok = all(isinstance(h.formatter, RedactingFormatter) for h in handlers)\n"
        "print(bool(handlers) and ok)"
    )
    done = subprocess.run(  # noqa: S603 - notre interpréteur, un code écrit ci-dessus
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=SERVICE, timeout=120
    )
    assert done.stdout.strip().splitlines()[-1] == "True", done.stderr[-500:]


def test_an_opaque_bearer_token_is_masked_without_being_known():
    token = secrets.token_urlsafe(24)  # ni de forme JWT, ni dans l'environnement
    assert redact(f"Authorization: Bearer {token}", []) == f"Authorization: Bearer {MASK}"


def test_a_secret_written_url_encoded_outside_an_address_is_masked(monkeypatch, capsys):
    awkward = "p/a:s+s w@rd" + secrets.token_urlsafe(8)
    monkeypatch.setenv("SERVICE_PASSWORD", awkward)
    configure_logging("traitement", "DEBUG")
    install_redaction()
    capsys.readouterr()
    logging.getLogger("app.test").warning("param=%s", quote(awkward, safe=""))
    out = capsys.readouterr().out
    assert quote(awkward, safe="") not in out
    assert json.loads(out)["message"] == f"param={MASK}"
