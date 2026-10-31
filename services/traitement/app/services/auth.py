"""Connexion, vérification du jeton et hiérarchie des rôles (BE-03).

Règles de gestion :
- un identifiant inconnu, un mauvais mot de passe et un compte désactivé donnent la même erreur
  (le client ne peut pas deviner lequel) et prennent le même temps ;
- le jeton ne vaut que si le compte existe et est actif au moment de la requête, et c'est le rôle
  enregistré en base qui compte, pas celui que le jeton annonçait : désactiver un compte ou changer
  son rôle agit tout de suite, sans attendre l'expiration du jeton ;
- les rôles sont hiérarchiques : `admin` inclut `operator`, qui inclut `viewer`.
"""

import logging

from app.core.security import (
    AccessToken,
    InvalidToken,
    create_access_token,
    decode_access_token,
    verify_against_decoy,
    verify_password,
)
from app.models import Role, User
from app.repositories.users import UserRepository

logger = logging.getLogger("app.auth")

ROLE_LEVEL = {Role.VIEWER: 1, Role.OPERATOR: 2, Role.ADMIN: 3}


class InvalidCredentials(Exception):
    """Identifiant inconnu, mot de passe incorrect ou compte désactivé."""


class NotAuthenticated(Exception):
    """Jeton absent, invalide, expiré, ou compte disparu ou désactivé."""


class AuthNotConfigured(Exception):
    """`JWT_SECRET` n'est pas fourni : aucun jeton ne peut être émis ni vérifié."""


def has_at_least(role: Role, minimum: Role) -> bool:
    return ROLE_LEVEL[role] >= ROLE_LEVEL[minimum]


class AuthService:
    def __init__(self, users: UserRepository, *, secret: str | None, ttl_s: int) -> None:
        self._users = users
        self._secret = secret
        self._ttl_s = ttl_s

    def _secret_or_fail(self) -> str:
        if not self._secret:
            raise AuthNotConfigured
        return self._secret

    def login(self, username: str, password: str) -> AccessToken:
        secret = self._secret_or_fail()
        user = self._users.get_by_username(username)
        if user is None:
            verify_against_decoy(password)
            logger.info("connexion refusée", extra={"fields": {"reason": "unknown_user"}})
            raise InvalidCredentials
        password_ok = verify_password(user.password_hash, password)
        if not password_ok or not user.is_active:
            reason = "inactive_user" if password_ok else "wrong_password"
            logger.info("connexion refusée", extra={"fields": {"reason": reason}})
            raise InvalidCredentials
        logger.info("connexion acceptée", extra={"fields": {"user_id": str(user.user_id)}})
        return create_access_token(user.user_id, user.role, secret=secret, ttl_s=self._ttl_s)

    def authenticate(self, token: str) -> User:
        secret = self._secret_or_fail()
        try:
            claims = decode_access_token(token, secret=secret)
        except InvalidToken as error:
            raise NotAuthenticated from error
        user = self._users.get(claims.user_id)
        if user is None or not user.is_active:
            raise NotAuthenticated
        return user
