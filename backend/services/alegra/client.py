"""
AlegraClient — The ONLY path for Alegra API calls in SISMO V2.

Rules (from ROG-1 and FOUND-06):
- EVERY write goes through request_with_verify(): POST → verify 200/201 → GET → return ID
- ALWAYS use /journals for accounting entries (NEVER the deprecated variant that returns 403)
- ALWAYS use /categories for account listing (NEVER the deprecated variant that returns 403)
- Dates: yyyy-MM-dd (NEVER ISO-8601 with timezone)
- Errors translated to Spanish before raising

Circuit Breaker (DT-11):
- Estado persiste en MongoDB colección 'system_health'
- CLOSED  → requests fluyen normalmente; si fallos/total > 50% en 60s → OPEN
- OPEN    → rechaza inmediatamente; después de 5 min → HALF_OPEN
- HALF_OPEN → deja pasar 1 request de prueba; éxito → CLOSED; fallo → OPEN
"""
import os
from datetime import datetime, timezone, timedelta

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

ALEGRA_BASE_URL = "https://api.alegra.com/api/v1"

# ── Circuit breaker constants ─────────────────────────────────────────────────
CB_DOC_ID          = "alegra_circuit_breaker"
CB_COLLECTION      = "system_health"
CB_VENTANA_SEG     = 60        # ventana de conteo en segundos
CB_OPEN_TIMEOUT    = 300       # segundos en OPEN antes de pasar a HALF_OPEN
CB_FALLO_UMBRAL    = 0.50      # 50% de fallos en ventana → OPEN
CB_MINIMO_REQUESTS = 3         # mínimo de requests en ventana para activar CB

ALEGRA_HTTP_ERROR_MESSAGES = {
    400: "Datos invalidos enviados a Alegra. Revise el formato del asiento.",
    401: "El token de Alegra vencio o es incorrecto. Contacte al administrador.",
    403: "Alegra rechazo el endpoint — verifique que este usando /journals (no /categories para listas).",
    404: "Registro no encontrado en Alegra.",
    422: "Alegra rechazo los datos del registro. Verifique montos, fechas (yyyy-MM-dd) y cuentas.",
    429: "Demasiadas peticiones a Alegra. Reintentando en 30 segundos.",
    500: "Error interno de Alegra. Reintente en unos minutos.",
    503: "Alegra no esta disponible. Reintente en unos minutos.",
}


class AlegraError(Exception):
    """Alegra API error with a human-readable Spanish message."""
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class CircuitBreakerOpenError(AlegraError):
    """Raised when the circuit breaker is OPEN and no request should be sent."""
    def __init__(self, estado: str = "OPEN"):
        super().__init__(
            f"Circuit breaker Alegra en estado {estado}. "
            "Demasiados fallos recientes — esperando recuperacion automatica.",
            status_code=503,
        )
        self.cb_estado = estado


# ── Circuit breaker state helpers ─────────────────────────────────────────────

async def _cb_init(db: AsyncIOMotorDatabase) -> dict:
    """Read or create the CB document in system_health."""
    now = datetime.now(timezone.utc)
    doc = await db[CB_COLLECTION].find_one({"_id": CB_DOC_ID})
    if doc is None:
        doc = {
            "_id":           CB_DOC_ID,
            "estado":        "CLOSED",
            "fallos_ventana": 0,
            "total_ventana":  0,
            "ventana_inicio": now,
            "open_desde":    None,
            "ultimo_update": now,
        }
        await db[CB_COLLECTION].insert_one(doc)
    return doc


async def _cb_get_estado(db: AsyncIOMotorDatabase) -> str:
    """Return current CB estado string (for health endpoint)."""
    doc = await db[CB_COLLECTION].find_one({"_id": CB_DOC_ID})
    if doc is None:
        return "CLOSED"
    return doc.get("estado", "CLOSED")


async def _cb_before_request(db: AsyncIOMotorDatabase) -> None:
    """
    Called before every Alegra request.
    Raises CircuitBreakerOpenError if the request should be blocked.
    Handles OPEN→HALF_OPEN transition after timeout.
    """
    doc = await _cb_init(db)
    now = datetime.now(timezone.utc)
    estado = doc.get("estado", "CLOSED")

    if estado == "OPEN":
        open_desde = doc.get("open_desde")
        if open_desde and now >= open_desde + timedelta(seconds=CB_OPEN_TIMEOUT):
            # Transition OPEN → HALF_OPEN
            await db[CB_COLLECTION].update_one(
                {"_id": CB_DOC_ID},
                {"$set": {
                    "estado":        "HALF_OPEN",
                    "ultimo_update": now,
                }},
            )
        else:
            raise CircuitBreakerOpenError("OPEN")

    elif estado == "HALF_OPEN":
        # Allow the probe request through — no blocking needed
        pass

    # CLOSED: always allow


async def _cb_after_request(db: AsyncIOMotorDatabase, success: bool) -> None:
    """
    Called after every Alegra request (success or failure).
    Updates counters, resets window if needed, transitions state.
    Publishes event if CB opens.
    """
    doc = await _cb_init(db)
    now = datetime.now(timezone.utc)
    estado = doc.get("estado", "CLOSED")

    # ── HALF_OPEN resolution ──────────────────────────────────────────────
    if estado == "HALF_OPEN":
        if success:
            await db[CB_COLLECTION].update_one(
                {"_id": CB_DOC_ID},
                {"$set": {
                    "estado":         "CLOSED",
                    "fallos_ventana": 0,
                    "total_ventana":  0,
                    "ventana_inicio": now,
                    "open_desde":     None,
                    "ultimo_update":  now,
                }},
            )
        else:
            await db[CB_COLLECTION].update_one(
                {"_id": CB_DOC_ID},
                {"$set": {
                    "estado":        "OPEN",
                    "open_desde":    now,
                    "ultimo_update": now,
                }},
            )
            await _cb_publish_open_event(db, now, "HALF_OPEN probe fallida")
        return

    # ── CLOSED: update window counters ────────────────────────────────────
    ventana_inicio = doc.get("ventana_inicio", now)
    if isinstance(ventana_inicio, str):
        ventana_inicio = datetime.fromisoformat(ventana_inicio)

    # Reset window if expired
    if now >= ventana_inicio + timedelta(seconds=CB_VENTANA_SEG):
        fallos = 1 if not success else 0
        total  = 1
        await db[CB_COLLECTION].update_one(
            {"_id": CB_DOC_ID},
            {"$set": {
                "fallos_ventana": fallos,
                "total_ventana":  total,
                "ventana_inicio": now,
                "ultimo_update":  now,
            }},
        )
        return

    # Increment within current window
    inc = {"total_ventana": 1}
    if not success:
        inc["fallos_ventana"] = 1

    updated = await db[CB_COLLECTION].find_one_and_update(
        {"_id": CB_DOC_ID},
        {"$inc": inc, "$set": {"ultimo_update": now}},
        return_document=True,
    )
    if updated is None:
        return

    fallos = updated.get("fallos_ventana", 0)
    total  = updated.get("total_ventana", 0)

    # Check if CB should open
    if (
        total >= CB_MINIMO_REQUESTS
        and total > 0
        and (fallos / total) > CB_FALLO_UMBRAL
    ):
        await db[CB_COLLECTION].update_one(
            {"_id": CB_DOC_ID},
            {"$set": {
                "estado":        "OPEN",
                "open_desde":    now,
                "ultimo_update": now,
            }},
        )
        await _cb_publish_open_event(
            db, now,
            f"Tasa de fallo {fallos}/{total} ({fallos/total*100:.0f}%) supero umbral {CB_FALLO_UMBRAL*100:.0f}%"
        )


async def _cb_publish_open_event(db: AsyncIOMotorDatabase, now: datetime, motivo: str) -> None:
    """Publish circuit_breaker.open event to roddos_events bus."""
    try:
        from core.events import publish_event
        await publish_event(
            db=db,
            event_type="alegra.circuit_breaker.open",
            source="alegra_client",
            datos={"motivo": motivo, "timestamp": now.isoformat()},
            alegra_id=None,
            accion_ejecutada=f"Circuit breaker OPEN: {motivo}",
        )
    except Exception:
        pass  # Never let CB event failure break the caller


# ── AlegraClient ──────────────────────────────────────────────────────────────

class AlegraClient:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self._email = os.environ.get("ALEGRA_EMAIL", "")
        self._token = os.environ.get("ALEGRA_TOKEN", "")
        self._auth = (self._email, self._token)

    async def request_with_verify(
        self,
        endpoint: str,
        method: str,
        payload: dict | None = None,
    ) -> dict:
        """
        Execute a write to Alegra and verify the record was created.

        Pattern (FOUND-06, ROG-1):
          1. Check circuit breaker (OPEN → raise immediately, no HTTP call)
          2. POST/PUT to endpoint
          3. Verify HTTP 200 or 201
          4. GET /{endpoint}/{id} to confirm existence
          5. Update circuit breaker counters
          6. Return verified record with alegra_id

        Args:
            endpoint: e.g. 'journals', 'invoices', 'payments'
            method: 'POST' | 'PUT' | 'DELETE'
            payload: Request body dict

        Returns:
            Verified record dict from Alegra with '_alegra_id' key.

        Raises:
            CircuitBreakerOpenError: If CB is OPEN (no HTTP request made).
            AlegraError: If POST fails, returns unexpected status, or GET cannot confirm.
        """
        # ── Circuit breaker check ─────────────────────────────────────────
        await _cb_before_request(self.db)

        url = f"{ALEGRA_BASE_URL}/{endpoint}"
        success = False

        try:
            async with httpx.AsyncClient(timeout=30.0) as http:
                # Step 1: Execute the write
                try:
                    if method == "POST":
                        response = await http.post(url, json=payload, auth=self._auth)
                    elif method == "PUT":
                        response = await http.put(url, json=payload, auth=self._auth)
                    elif method == "DELETE":
                        response = await http.delete(url, auth=self._auth)
                        response.raise_for_status()
                        success = True
                        return {"deleted": True}
                    else:
                        raise ValueError(f"Metodo no soportado: {method}")

                    response.raise_for_status()

                except httpx.HTTPStatusError as e:
                    status = e.response.status_code
                    alegra_msg = ""
                    try:
                        body = e.response.json()
                        alegra_msg = body.get("message", "")
                    except Exception:
                        pass
                    spanish_msg = ALEGRA_HTTP_ERROR_MESSAGES.get(
                        status,
                        f"Error inesperado de Alegra al intentar {method} {endpoint}."
                    )
                    if alegra_msg:
                        spanish_msg = f"{spanish_msg} Detalle: {alegra_msg}"
                    raise AlegraError(spanish_msg, status_code=status) from e

                created = response.json()
                alegra_id = created.get("id")
                if not alegra_id:
                    raise AlegraError(
                        f"Alegra no retorno un ID al crear el registro en {endpoint}. "
                        "El registro puede no haberse creado."
                    )

                # Step 2: GET verification
                try:
                    verify_response = await http.get(
                        f"{ALEGRA_BASE_URL}/{endpoint}/{alegra_id}",
                        auth=self._auth,
                    )
                    verify_response.raise_for_status()
                except httpx.HTTPStatusError:
                    raise AlegraError(
                        f"Registro creado en Alegra (ID: {alegra_id}) pero la verificacion GET fallo. "
                        "El registro puede estar incompleto. Verifique manualmente en Alegra."
                    )

                verified = verify_response.json()
                verified["_alegra_id"] = str(alegra_id)
                success = True
                return verified

        finally:
            # Always update CB counters (success or failure)
            try:
                await _cb_after_request(self.db, success)
            except Exception:
                pass  # Never let CB update failure break the caller

    async def get(self, endpoint: str, params: dict | None = None) -> dict | list:
        """Read-only GET request to Alegra. Does NOT count toward circuit breaker."""
        url = f"{ALEGRA_BASE_URL}/{endpoint}"
        async with httpx.AsyncClient(timeout=30.0) as http:
            try:
                response = await http.get(url, params=params, auth=self._auth)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                spanish_msg = ALEGRA_HTTP_ERROR_MESSAGES.get(
                    status, f"Error consultando {endpoint} en Alegra."
                )
                raise AlegraError(spanish_msg, status_code=status) from e


async def get_alegra_client(db=None) -> AlegraClient:
    """FastAPI Depends() factory for AlegraClient."""
    return AlegraClient(db=db)


async def get_circuit_breaker_estado(db: AsyncIOMotorDatabase) -> str:
    """Public helper for health endpoint — returns CB estado string."""
    return await _cb_get_estado(db)
