"""
SlidingSessionMiddleware — renews JWT when close to expiry.

Inspects every incoming request for a Bearer token. After the response is
produced, if the token is valid and has less than SLIDING_RENEWAL_THRESHOLD_HOURS
remaining, injects header `X-New-Token: <jwt>` into the response.

Design notes:
  - Additive per P7: clients that don't handle the header simply ignore it.
  - Never blocks the request: any failure in renewal silently falls through.
  - No DB lookups — renewal reuses the claims already signed into the token.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.auth import maybe_renew_token


HEADER_NAME = "X-New-Token"


class SlidingSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        response = await call_next(request)

        auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
        if not auth_header or not auth_header.lower().startswith("bearer "):
            return response

        token = auth_header.split(" ", 1)[1].strip()
        if not token:
            return response

        try:
            new_token = maybe_renew_token(token)
        except Exception:  # pragma: no cover — defensive
            return response

        if new_token:
            # Expose the custom header through CORS so browsers can read it.
            response.headers[HEADER_NAME] = new_token
            existing_expose = response.headers.get("access-control-expose-headers")
            if existing_expose:
                if HEADER_NAME.lower() not in existing_expose.lower():
                    response.headers["access-control-expose-headers"] = (
                        f"{existing_expose}, {HEADER_NAME}"
                    )
            else:
                response.headers["access-control-expose-headers"] = HEADER_NAME

        return response
