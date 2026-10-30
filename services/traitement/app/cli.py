"""Création d'un compte en ligne de commande : amorce le premier administrateur (BE-03).

    python -m app.cli create-user alice --role admin

Sans compte administrateur, personne ne peut appeler `POST /api/v1/users` : la première personne
est créée ici, avec le compte `svc_app` (variable `APP_DATABASE_URL`). Le mot de passe est saisi
sans écho, jamais passé en argument (il resterait dans l'historique du terminal).
"""

import argparse
import getpass
import sys
from collections.abc import Callable, Sequence

from pydantic import ValidationError

from app.db.session import DatabaseNotConfigured, get_session_factory
from app.models import Role
from app.repositories.users import DuplicateUsername, SqlUserRepository, UserRepository
from app.schemas.users import UserCreate
from app.services.users import UserService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="crée un compte")
    create.add_argument("username", help="3 à 64 caractères parmi a-z, 0-9, _ . -")
    create.add_argument("--role", required=True, choices=[role.value for role in Role])
    return parser


def ask_password(prompt: Callable[[str], str] = getpass.getpass) -> str:
    password = prompt("Mot de passe (12 caractères au moins) : ")
    if prompt("Confirmer le mot de passe : ") != password:
        raise ValueError("Les deux saisies diffèrent.")
    return password


def create_user(
    username: str, role: str, password: str, repository: UserRepository
) -> tuple[bool, str]:
    """Rend (réussi, message). Les règles sont celles de l'API : un seul schéma de validation."""
    try:
        data = UserCreate(username=username, password=password, role=Role(role))
    except ValidationError as error:
        champs = ", ".join(str(e["loc"][0]) for e in error.errors())
        return False, f"Valeur refusée ({champs}) : voir les bornes du contrat OpenAPI."
    try:
        user = UserService(repository).create(data.username, data.password, data.role)
    except DuplicateUsername:
        return False, "Ce nom d'utilisateur existe déjà."
    return True, f"Compte créé : {user.username} ({user.role.value}), identifiant {user.user_id}."


def main(
    argv: Sequence[str] | None = None, *, prompt: Callable[[str], str] = getpass.getpass
) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        password = ask_password(prompt)
    except ValueError as error:
        print(f"ERREUR : {error}", file=sys.stderr)
        return 1
    try:
        factory = get_session_factory()
    except DatabaseNotConfigured:
        print("ERREUR : variable APP_DATABASE_URL absente.", file=sys.stderr)
        return 1
    with factory() as session:
        reussi, message = create_user(
            arguments.username, arguments.role, password, SqlUserRepository(session)
        )
    print(message, file=sys.stdout if reussi else sys.stderr)
    return 0 if reussi else 1


if __name__ == "__main__":
    sys.exit(main())
