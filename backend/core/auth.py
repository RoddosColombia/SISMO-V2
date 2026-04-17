"""
JWT authentication — login, token creation, dependency for protected routes.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorDatabase
from passlib.context import CryptContext

from core.database import get_db

JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7  # 7 days — sliding session per B7-UX
# If remaining time < this threshold, middleware renews and sets X-New-Token
SLIDING_RENEWAL_THRESHOLD_HOURS = 24 * 2  # 2 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    """FastAPI dependency — extracts and validates JWT, returns user dict."""
    payload = decode_token(credentials.credentials)
    user = await db.users.find_one({"email": payload["email"]})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")
    user["_id"] = str(user["_id"])
    return user


# ═══════════════════════════════════════════
# Sliding session helpers (B7-UX)
# ═══════════════════════════════════════════


def should_renew(exp_timestamp: int, now: datetime | None = None) -> bool:
    """Return True when remaining time on the token is below the sliding
    renewal threshold. Caller decides what to do with the decision."""
    now = now or datetime.now(timezone.utc)
    exp = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
    remaining = exp - now
    return remaining <= timedelta(hours=SLIDING_RENEWAL_THRESHOLD_HOURS)


def maybe_renew_token(token: str) -> str | None:
    """Inspect a bearer token and, if it's valid and close to expiry, return a
    freshly-issued token (same user, exp = now + JWT_EXPIRATION_HOURS).

    Returns None when:
      - the token is invalid or already expired
      - the token is still far from expiry (no renewal needed)
      - any unexpected error occurs (renewal MUST NOT break the request)
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None

    exp = payload.get("exp")
    if not isinstance(exp, int):
        return None

    if not should_renew(exp):
        return None

    try:
        return create_token(
            user_id=str(payload.get("sub", "")),
            email=str(payload.get("email", "")),
            role=str(payload.get("role", "")),
        )
    except Exception:  # pragma: no cover — defensive
        return None
