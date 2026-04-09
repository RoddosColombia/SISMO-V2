"""
AlegraClient — The ONLY path for Alegra API calls in SISMO V2.

Rules (from ROG-1 and FOUND-06):
- EVERY write goes through request_with_verify(): POST → verify 200/201 → GET → return ID
- ALWAYS use /journals for accounting entries (NEVER the deprecated variant that returns 403)
- ALWAYS use /categories for account listing (NEVER the deprecated variant that returns 403)
- Dates: yyyy-MM-dd (NEVER ISO-8601 with timezone)
- Errors translated to Spanish before raising
"""
import os
import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

ALEGRA_BASE_URL = "https://api.alegra.com/api/v1"

ALEGRA_HTTP_ERROR_MESSAGES = {
    400: "Datos inválidos enviados a Alegra. Revise el formato del asiento.",
    401: "El token de Alegra venció o es incorrecto. Contacte al administrador.",
    403: "Alegra rechazó el endpoint — verifique que esté usando /journals (no /categories para listas).",
    404: "Registro no encontrado en Alegra.",
    422: "Alegra rechazó los datos del registro. Verifique montos, fechas (yyyy-MM-dd) y cuentas.",
    429: "Demasiadas peticiones a Alegra. Reintentando en 30 segundos.",
    500: "Error interno de Alegra. Reintente en unos minutos.",
    503: "Alegra no está disponible. Reintente en unos minutos.",
}


class AlegraError(Exception):
    """Alegra API error with a human-readable Spanish message."""
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


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
          1. POST/PUT to endpoint
          2. Verify HTTP 200 or 201
          3. GET /{endpoint}/{id} to confirm existence
          4. Return verified record with alegra_id

        Args:
            endpoint: e.g. 'journals', 'invoices', 'payments'
            method: 'POST' | 'PUT' | 'DELETE'
            payload: Request body dict

        Returns:
            Verified record dict from Alegra with 'id' key.

        Raises:
            AlegraError: If POST fails, returns unexpected status, or GET cannot confirm.
        """
        url = f"{ALEGRA_BASE_URL}/{endpoint}"

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
                    return {"deleted": True}
                else:
                    raise ValueError(f"Método no soportado: {method}")

                response.raise_for_status()

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                spanish_msg = ALEGRA_HTTP_ERROR_MESSAGES.get(
                    status,
                    f"Error inesperado de Alegra al intentar {method} {endpoint}."
                )
                raise AlegraError(spanish_msg, status_code=status) from e

            created = response.json()
            alegra_id = created.get("id")
            if not alegra_id:
                raise AlegraError(
                    f"Alegra no retornó un ID al crear el registro en {endpoint}. "
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
                    f"Registro creado en Alegra (ID: {alegra_id}) pero la verificación GET falló. "
                    "El registro puede estar incompleto. Verifique manualmente en Alegra."
                )

            verified = verify_response.json()
            verified["_alegra_id"] = str(alegra_id)  # convenience key
            return verified

    async def get(self, endpoint: str, params: dict | None = None) -> dict | list:
        """Read-only GET request to Alegra."""
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
