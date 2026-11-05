"""Aucun secret dans les journaux (BE-08) : dernier filet, après le code qui évite d'en écrire.

Le code ne journalise jamais un mot de passe, un jeton ni une adresse de base (voir les tests de
`tests/unit/test_secrets_in_logs.py`). Ce module protège contre l'erreur qu'on n'a pas prévue : un
message d'une bibliothèque qui recopie une adresse de connexion, une valeur de configuration collée
dans un message. Il masque, dans chaque ligne JSON écrite, par ordre :

1. la valeur de toute variable d'environnement dont le nom dit « secret » (mot de passe, jeton,
   clé, secret, identifiant d'accès) et le mot de passe de toute adresse de connexion que porte
   une variable (`POSTGRES_URL`...), sous leurs formes brute, JSON et encodée pour une adresse ;
2. le mot de passe d'une adresse `schéma://compte:mot-de-passe@hôte` ;
3. un en-tête `Bearer <jeton>` et tout jeton de forme JWT (`xxx.yyy.zzz` commençant par `eyJ`).

Le masquage s'applique à la ligne déjà sérialisée : il couvre le message, les champs et la trace
d'exécution. Il ne remplace pas la discipline : une valeur trop courte (moins de 8 caractères) n'est
pas cherchée, faute de pouvoir la distinguer d'un mot courant.
"""

import json
import logging
import os
import re
from urllib.parse import quote, unquote, urlsplit

from app.core.config import SECRET_SETTINGS, get_settings

MASK = "***"
MIN_SECRET_LENGTH = 8

_SECRET_NAME = re.compile(r"PASSWORD|SECRET|TOKEN|_KEY$|CREDENTIAL", re.IGNORECASE)
_URL_PASSWORD = re.compile(r"(?<=://)([^/\s:@\"'\\]+):([^/\s@\"'\\]+)(?=@)")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")


def _variants(value: str) -> set[str]:
    """Formes sous lesquelles une valeur peut apparaître dans une ligne de journal."""
    return {
        value,
        # la forme de `JsonFormatter` : guillemets et barres inverses échappés, accents gardés
        json.dumps(value, ensure_ascii=False)[1:-1],
        quote(value, safe=""),  # la forme d'un mot de passe dans une adresse
    }


def _candidates(value: str, *, secret_by_name: bool) -> set[str]:
    candidates = {value} if secret_by_name else set()
    if "://" in value:  # une adresse de connexion : son mot de passe est secret, pas son hôte
        try:
            password = urlsplit(value).password
        except ValueError:  # adresse mal formée : rien à extraire
            password = None
        if password:
            candidates |= {password, unquote(password)}
    return candidates


def _configured_secrets() -> list[str]:
    """Secrets de la configuration, y compris ceux lus dans `.env` (absents de l'environnement)."""
    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001 - une configuration invalide ne doit pas casser le journal
        return []
    values = [getattr(settings, name) for name in SECRET_SETTINGS]
    return [value.get_secret_value() for value in values if value is not None]


def secret_values(environ: dict[str, str] | None = None) -> list[str]:
    """Valeurs à masquer, les plus longues d'abord (une adresse avant son mot de passe)."""
    found: set[str] = set()
    sources = [
        (_SECRET_NAME.search(name) is not None, value)
        for name, value in (os.environ if environ is None else environ).items()
    ]
    if environ is None:
        sources += [(True, value) for value in _configured_secrets()]
    for secret_by_name, value in sources:
        for candidate in _candidates(value, secret_by_name=secret_by_name) if value else ():
            if len(candidate) >= MIN_SECRET_LENGTH:
                found |= _variants(candidate)
    return sorted(found, key=len, reverse=True)


def redact(text: str, values: list[str] | None = None) -> str:
    for value in secret_values() if values is None else values:
        text = text.replace(value, MASK)
    text = _URL_PASSWORD.sub(lambda match: f"{match.group(1)}:{MASK}", text)
    text = _BEARER.sub(f"Bearer {MASK}", text)
    return _JWT.sub(MASK, text)


class RedactingFormatter(logging.Formatter):
    """Enveloppe un formateur et masque les secrets de la ligne qu'il produit."""

    def __init__(self, inner: logging.Formatter) -> None:
        super().__init__()
        self.inner = inner

    def format(self, record: logging.LogRecord) -> str:
        return redact(self.inner.format(record))


def install_redaction() -> None:
    """À appeler après `configure_logging` : chaque gestionnaire écrit des lignes masquées."""
    for handler in logging.getLogger().handlers:
        formatter = handler.formatter
        if formatter is not None and not isinstance(formatter, RedactingFormatter):
            handler.setFormatter(RedactingFormatter(formatter))
