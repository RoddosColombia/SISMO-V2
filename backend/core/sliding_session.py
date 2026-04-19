"""
SlidingSessionMiddleware — renews JWT when close to expiry.

Inspects every incoming request for a Bearer token. After the response is
produced, if the token is valid and has less than SLIDING_RENEWAL_THRESHOLD_HOURS
remaining, injects header `X-New-Token: <jwt>` into the response.

Design notes:
  - Pure ASGI middleware (no BaseHTTPMiddleware) to avoid conflicts with
    multipart/file uploads which BaseHTTPMiddleware can break.
  - Additive: clients that don't handle the header simply ignore it.
  - Never blocks the request: any failure in renewal silently falls through.
  - No DB lookups — renewal reuses the claims already signed into the token.
"""
from __future__ import annotations

from typing import Callable

from core.auth import maybe_renew_token

HEADER_NAME = "x-new-token"
HEADER_NAME_DISPLAY = "X-New-Token"


class SlidingSessionMiddleware:
    """Pure ASGI middleware — safe with multipart uploads and streaming."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract bearer token from request headers
        token: str | None = None
        for name, value in scope.get("headers", []):
            if name.lower() == b"authorization":
                auth = value.decode("latin-1")
                if auth.lower().startswith("bearer "):
                    token = auth.split(" ", 1)[1].strip()
                break

        # Compute new token (if renewal needed) before forwarding
        new_token: str | None = None
        if token:
            try:
                new_token = maybe_renew_token(token)
            except Exception:
                pass

        if not new_token:
            # No renewal needed — pass through unchanged
            await self.app(scope, receive, send)
            return

        # Inject X-New-Token into response headers
        new_token_bytes = new_token.encode("latin-1")

        async def send_with_renewal(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((HEADER_NAME.encode(), new_token_bytes))

                # Expose header via CORS
                expose = None
                for i, (k, v) in enumerate(headers):
                    if k.lower() == b"access-control-expose-headers":
                        existing = v.decode("latin-1")
                        if HEADER_NAME_DISPLAY.lower() not in existing.lower():
                            headers[i] = (k, f"{existing}, {HEADER_NAME_DISPLAY}".encode("latin-1"))
                        expose = True
                        break
                if not expose:
                    headers.append((b"access-control-expose-headers", HEADER_NAME_DISPLAY.encode("latin-1")))

                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_renewal)
