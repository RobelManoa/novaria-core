"""Création du premier compte en ligne de commande (BE-03)."""

from contextlib import nullcontext

import pytest

from app import cli
from app.core.security import verify_password
from app.db.session import DatabaseNotConfigured
from app.models import Role
from tests.fakes import PASSWORD, FakeUserRepository


@pytest.fixture
def repo():
    return FakeUserRepository()


def saisies(*valeurs):
    reste = iter(valeurs)
    return lambda _invite: next(reste)


def test_a_valid_account_is_created_with_a_hash_and_reported(repo):
    reussi, message = cli.create_user("alice", "admin", PASSWORD, repo)
    assert reussi is True
    assert "alice (admin)" in message
    user = repo.get_by_username("alice")
    assert user.role is Role.ADMIN
    assert verify_password(user.password_hash, PASSWORD)
    assert PASSWORD not in message


@pytest.mark.parametrize(
    ("username", "password", "champ"),
    [("ab", PASSWORD, "username"), ("Alice", PASSWORD, "username"), ("alice", "court", "password")],
)
def test_the_api_rules_apply_to_the_command_line_too(repo, username, password, champ):
    reussi, message = cli.create_user(username, "viewer", password, repo)
    assert reussi is False
    assert champ in message
    assert password not in message or password == PASSWORD
    assert repo.users == {}


def test_a_taken_username_is_reported_not_raised(repo):
    repo.make("alice")
    reussi, message = cli.create_user("alice", "viewer", PASSWORD, repo)
    assert (reussi, message) == (False, "Ce nom d'utilisateur existe déjà.")


def test_the_password_is_asked_twice_and_must_match():
    assert cli.ask_password(saisies("a" * 12, "a" * 12)) == "a" * 12
    with pytest.raises(ValueError, match="diffèrent"):
        cli.ask_password(saisies("a" * 12, "b" * 12))


def test_the_password_is_never_an_argument_of_the_command():
    arguments = cli.build_parser().parse_args(["create-user", "alice", "--role", "admin"])
    assert set(vars(arguments)) == {"command", "username", "role"}
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["create-user", "alice", "--role", "admin", "--password", "x"]
        )


def test_the_role_is_required_and_limited_to_the_known_roles():
    for argv in (["create-user", "alice"], ["create-user", "alice", "--role", "root"]):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(argv)


def test_the_command_creates_the_account_and_exits_with_0(repo, monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_session_factory", lambda: lambda: nullcontext(repo))
    monkeypatch.setattr(cli, "SqlUserRepository", lambda session: session)
    code = cli.main(["create-user", "alice", "--role", "admin"], prompt=saisies(PASSWORD, PASSWORD))
    sortie = capsys.readouterr()
    assert code == 0
    assert "Compte créé" in sortie.out
    assert repo.get_by_username("alice") is not None


def test_the_command_exits_with_1_and_creates_nothing_when_the_entries_differ(repo, capsys):
    code = cli.main(["create-user", "alice", "--role", "admin"], prompt=saisies(PASSWORD, "autre"))
    assert code == 1
    assert "diffèrent" in capsys.readouterr().err
    assert repo.users == {}


def test_the_command_exits_with_1_without_a_database_address(monkeypatch, capsys):
    def sans_base():
        raise DatabaseNotConfigured

    monkeypatch.setattr(cli, "get_session_factory", sans_base)
    code = cli.main(["create-user", "alice", "--role", "admin"], prompt=saisies(PASSWORD, PASSWORD))
    assert code == 1
    assert "APP_DATABASE_URL" in capsys.readouterr().err


def test_the_command_exits_with_1_when_the_account_is_refused(repo, monkeypatch, capsys):
    repo.make("alice")
    monkeypatch.setattr(cli, "get_session_factory", lambda: lambda: nullcontext(repo))
    monkeypatch.setattr(cli, "SqlUserRepository", lambda session: session)
    code = cli.main(
        ["create-user", "alice", "--role", "viewer"], prompt=saisies(PASSWORD, PASSWORD)
    )
    assert code == 1
    assert "existe déjà" in capsys.readouterr().err
