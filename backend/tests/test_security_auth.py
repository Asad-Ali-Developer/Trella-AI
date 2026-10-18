import uuid
from datetime import timedelta

import pytest

from app.core.security.auth import (
    InvalidTokenError,
    TokenExpiredError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hashing() -> None:
    pw = "SuperSecretPassword123!"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password("", hashed) is False


def test_jwt_access_token() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id, extra_claims={"email": "test@example.com"})
    payload = decode_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["email"] == "test@example.com"
    assert payload["type"] == "access"


def test_jwt_refresh_token() -> None:
    user_id = uuid.uuid4()
    token = create_refresh_token(user_id)
    payload = decode_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "refresh"


def test_jwt_expired_token() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id, expires_delta=timedelta(seconds=-1))
    with pytest.raises(TokenExpiredError):
        decode_token(token)


def test_jwt_invalid_token() -> None:
    with pytest.raises(InvalidTokenError):
        decode_token("not.a.valid.jwt")
