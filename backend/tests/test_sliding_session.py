"""
Sliding session tests (B7-UX).

- should_renew() triggers when < 2 days remain
- maybe_renew_token() returns fresh token only when close to expiry
- New token carries the same identity and a bumped exp
"""
from datetime import datetime, timedelta, timezone

import jwt

from core.auth import (
    JWT_ALGORITHM,
    JWT_EXPIRATION_HOURS,
    JWT_SECRET,
    SLIDING_RENEWAL_THRESHOLD_HOURS,
    create_token,
    maybe_renew_token,
    should_renew,
)


def _make_token_with_exp(hours_ahead: float) -> str:
    payload = {
        "sub": "u1",
        "email": "user@roddos.com",
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours_ahead),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def test_should_renew_returns_false_when_far_from_expiry():
    exp_ts = int((datetime.now(timezone.utc) + timedelta(hours=5 * 24)).timestamp())
    assert should_renew(exp_ts) is False


def test_should_renew_returns_true_when_below_threshold():
    # Below threshold: 1 day remaining < 2 days
    exp_ts = int((datetime.now(timezone.utc) + timedelta(hours=24)).timestamp())
    assert should_renew(exp_ts) is True


def test_maybe_renew_returns_none_when_token_is_fresh():
    token = _make_token_with_exp(hours_ahead=5 * 24)  # 5 days ahead
    assert maybe_renew_token(token) is None


def test_maybe_renew_returns_new_token_when_close_to_expiry():
    token = _make_token_with_exp(hours_ahead=24)  # 1 day ahead — within threshold
    new_token = maybe_renew_token(token)
    assert new_token is not None
    assert new_token != token
    payload = jwt.decode(new_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    # Fresh exp should be ~JWT_EXPIRATION_HOURS ahead of now
    remaining = datetime.fromtimestamp(payload["exp"], tz=timezone.utc) - datetime.now(timezone.utc)
    assert remaining >= timedelta(hours=JWT_EXPIRATION_HOURS - 1)
    # Same identity claims preserved
    assert payload["email"] == "user@roddos.com"
    assert payload["role"] == "admin"
    assert payload["sub"] == "u1"


def test_maybe_renew_returns_none_for_invalid_token():
    assert maybe_renew_token("not.a.jwt") is None
    assert maybe_renew_token("") is None


def test_maybe_renew_returns_none_for_expired_token():
    token = _make_token_with_exp(hours_ahead=-1)  # already expired
    assert maybe_renew_token(token) is None


def test_jwt_expiration_is_seven_days():
    """Bumped from 24h to 7 days per B7-UX."""
    token = create_token(user_id="u", email="e", role="r")
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    remaining = datetime.fromtimestamp(payload["exp"], tz=timezone.utc) - datetime.now(timezone.utc)
    # Expect ~7 days (168h), allow some slack
    assert remaining >= timedelta(hours=167)


def test_sliding_renewal_threshold_is_two_days():
    assert SLIDING_RENEWAL_THRESHOLD_HOURS == 48
