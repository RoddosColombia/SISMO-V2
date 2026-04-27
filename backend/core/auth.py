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
# API Key auth — integraciones externas read-only
# ═══════════════════════════════════════════

async def require_api_key(
    x_api_key: str = Depends(lambda x_api_key: x_api_key),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    """FastAPI dependency — valida X-API-Key header contra colección api_keys.

    Acepta API keys con scope='read_only' y active=True.
    Actualiza last_used_at en cada llamada.
    Uso: en endpoints de integraciones externas (ARGOS, etc.).
    """
    from fastapi import Header as _Header
    # Este import circular se evita: la función real está abajo como closure.
    # Ver get_api_key_dep() para el dependency real con Header injection.
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Use get_api_key_dep")


def get_api_key_dep():
    """Retorna el FastAPI dependency correcto para X-API-Key.

    Uso en routers:
        from core.auth import get_api_key_dep
        api_key_auth = get_api_key_dep()

        @router.get("/ruta")
        async def mi_endpoint(api_key: dict = Depends(api_key_auth)):
            ...
    """
    from fastapi import Header as _Header
    from core.datetime_utils import now_iso_bogota as _now_iso

    async def _dep(
        x_api_key: str | None = _Header(default=None),
        db: AsyncIOMotorDatabase = Depends(get_db),
    ) -> dict:
        if not x_api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Se requiere X-API-Key header",
            )

        key_doc = await db.api_keys.find_one({"key": x_api_key, "active": True})
        if not key_doc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key inválida o inactiva",
            )

        if key_doc.get("scope") != "read_only":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Esta API key no tiene permisos suficientes",
            )

        # Actualizar last_used_at (best-effort, no bloquea si falla)
        try:
            await db.api_keys.update_one(
                {"_id": key_doc["_id"]},
                {"$set": {"last_used_at": _now_iso()}},
            )
        except Exception:
            pass

        key_doc.pop("_id", None)
        return key_doc

    return _dep


# Top-level singleton — ready to use as Depends(get_api_key) in any router.
# Equivalent to get_api_key_dep() but importable as a plain async function.
from fastapi import Header as _HeaderTop

async def get_api_key(
    x_api_key: str | None = _HeaderTop(default=None),
    db: "AsyncIOMotorDatabase" = Depends(get_db),
) -> dict:
    """FastAPI dependency — valida X-API-Key header contra colección api_keys.

    Uso directo:
        from core.auth import get_api_key

        @router.get("/ruta")
        async def mi_endpoint(api_key: dict = Depends(get_api_key)):
            ...
    """
    from core.datetime_utils import now_iso_bogota as _now_iso

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere X-API-Key header",
        )

    key_doc = await db.api_keys.find_one({"key": x_api_key, "active": True})
    if not key_doc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida o inactiva",
        )

    if key_doc.get("scope") != "read_only":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta API key no tiene permisos suficientes",
        )

    try:
        await db.api_keys.update_one(
            {"_id": key_doc["_id"]},
            {"$set": {"last_used_at": _now_iso()}},
        )
    except Exception:
        pass

    key_doc.pop("_id", None)
    return key_doc


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
