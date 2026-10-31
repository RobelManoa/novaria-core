"""Empreintes de mots de passe et jetons d'accès (BE-03) : fonctions pures."""

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core import security
from app.core.security import (
    ALGORITHM,
    InvalidToken,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_against_decoy,
    verify_password,
)
from app.models import Role
from tests.fakes import SECRET, TTL_S, hash_of

USER_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")


def forge(payload: dict, *, secret: str = SECRET, algorithm: str = ALGORITHM) -> str:
    return jwt.encode(payload, secret, algorithm=algorithm)


def now_payload(**changes) -> dict:
    now = int(datetime.now(UTC).timestamp())
    return {
        "sub": str(USER_ID),
        "role": "viewer",
        "iat": now,
        "exp": now + 600,
    } | changes


def test_a_password_is_stored_as_an_argon2id_hash_never_as_itself():
    empreinte = hash_of("un mot de passe assez long")
    assert empreinte.startswith("$argon2id$")
    assert "un mot de passe" not in empreinte
    assert hash_password("a") != hash_password("a"), "chaque empreinte porte son propre sel"


def test_the_right_password_is_accepted_and_every_other_case_is_refused():
    empreinte = hash_of("un mot de passe assez long")
    assert verify_password(empreinte, "un mot de passe assez long") is True
    assert verify_password(empreinte, "un mot de passe assez lonG") is False
    assert verify_password(empreinte, "") is False
    assert verify_password("pas-une-empreinte", "x") is False, (
        "empreinte illisible : refus, pas erreur"
    )
    assert verify_password("", "x") is False


def test_the_decoy_check_takes_a_hash_computation_and_returns_nothing(monkeypatch):
    appels = []
    monkeypatch.setattr(security, "verify_password", lambda h, p: appels.append((h, p)) or False)
    assert verify_against_decoy("secret") is None
    assert appels[0][0].startswith("$argon2id$")
    assert appels[0][1] == "secret"


def test_a_token_carries_subject_role_issue_and_expiry():
    now = datetime(2026, 10, 30, 12, 0, 0, 999999, tzinfo=UTC)
    jeton = create_access_token(USER_ID, Role.OPERATOR, secret=SECRET, ttl_s=TTL_S, now=now)
    assert jeton.expires_in == TTL_S
    brut = jwt.decode(jeton.value, options={"verify_signature": False})
    assert brut == {
        "sub": str(USER_ID),
        "role": "operator",
        "iat": int(datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC).timestamp()),
        "exp": int(datetime(2026, 10, 30, 12, 30, 0, tzinfo=UTC).timestamp()),
    }
    assert jwt.get_unverified_header(jeton.value)["alg"] == "HS256"


def test_a_fresh_token_is_decoded_into_claims():
    jeton = create_access_token(USER_ID, Role.ADMIN, secret=SECRET, ttl_s=TTL_S)
    claims = decode_access_token(jeton.value, secret=SECRET)
    assert claims.user_id == USER_ID
    assert claims.role is Role.ADMIN
    assert claims.expires_at - claims.issued_at == timedelta(seconds=TTL_S)


def test_an_expired_token_is_refused_and_one_about_to_expire_is_not():
    vieux = datetime.now(UTC) - timedelta(seconds=TTL_S + 5)
    expire = create_access_token(USER_ID, Role.VIEWER, secret=SECRET, ttl_s=TTL_S, now=vieux)
    with pytest.raises(InvalidToken):
        decode_access_token(expire.value, secret=SECRET)
    presque = datetime.now(UTC) - timedelta(seconds=TTL_S - 10)
    valide = create_access_token(USER_ID, Role.VIEWER, secret=SECRET, ttl_s=TTL_S, now=presque)
    assert decode_access_token(valide.value, secret=SECRET).user_id == USER_ID


def test_a_token_signed_with_another_secret_is_refused():
    jeton = create_access_token(USER_ID, Role.ADMIN, secret="un-autre-secret" * 3, ttl_s=TTL_S)
    with pytest.raises(InvalidToken):
        decode_access_token(jeton.value, secret=SECRET)


def test_a_token_whose_payload_was_edited_is_refused():
    jeton = create_access_token(USER_ID, Role.VIEWER, secret=SECRET, ttl_s=TTL_S).value
    entete, charge, signature = jeton.split(".")
    donnees = json.loads(base64.urlsafe_b64decode(charge + "=" * (-len(charge) % 4)))
    donnees["role"] = "admin"
    nouvelle = base64.urlsafe_b64encode(json.dumps(donnees).encode()).decode().rstrip("=")
    with pytest.raises(InvalidToken):
        decode_access_token(f"{entete}.{nouvelle}.{signature}", secret=SECRET)


def test_an_unsigned_token_with_alg_none_is_refused():
    sans_signature = jwt.encode(now_payload(), None, algorithm="none")
    with pytest.raises(InvalidToken):
        decode_access_token(sans_signature, secret=SECRET)


def test_another_signature_algorithm_is_refused_even_with_the_right_secret():
    for algorithme in ("HS384", "HS512"):
        with pytest.raises(InvalidToken):
            decode_access_token(forge(now_payload(), algorithm=algorithme), secret=SECRET)


@pytest.mark.parametrize("missing", ["sub", "role", "iat", "exp"])
def test_a_token_missing_a_claim_is_refused(missing):
    charge = {k: v for k, v in now_payload().items() if k != missing}
    with pytest.raises(InvalidToken):
        decode_access_token(forge(charge), secret=SECRET)


@pytest.mark.parametrize(
    "changes",
    [{"sub": "pas-un-uuid"}, {"sub": 12}, {"role": "root"}, {"role": None}, {"role": ["admin"]}],
)
def test_a_token_with_a_malformed_claim_is_refused(changes):
    with pytest.raises(InvalidToken):
        decode_access_token(forge(now_payload(**changes)), secret=SECRET)


@pytest.mark.parametrize("texte", ["", "abc", "a.b.c", "....", "Bearer x", "é"])
def test_something_that_is_not_a_token_is_refused(texte):
    with pytest.raises(InvalidToken):
        decode_access_token(texte, secret=SECRET)


def test_the_algorithm_is_fixed_to_hs256():
    assert ALGORITHM == "HS256"
    assert security.REQUIRED_CLAIMS == ("sub", "role", "iat", "exp")
