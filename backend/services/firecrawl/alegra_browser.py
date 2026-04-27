"""
Firecrawl browser client para operaciones en Alegra que la API REST bloquea.
Usa /interact para navegar la UI de Alegra como un humano.
Se activa SOLO cuando la API REST falla con 403/401 en items o bills.
"""
import os
import logging

logger = logging.getLogger("firecrawl.alegra")

ALEGRA_BASE = "https://app.alegra.com"
ALEGRA_EMAIL = os.getenv("ALEGRA_EMAIL", "")
ALEGRA_PASSWORD = os.getenv("ALEGRA_PASSWORD", "")  # contraseña UI (distinta del token API)
FIRECRAWL_KEY = os.getenv("FIRECRAWL_API_KEY", "")


class AlegraFirecrawlClient:
    def __init__(self):
        self._scrape_id: str | None = None
        self._fc = None  # lazy init para no crashear si SDK no instalado

    def _get_fc(self):
        """Lazy-init Firecrawl client. Raises ImportError si no instalado."""
        if self._fc is None:
            from firecrawl import FirecrawlApp  # noqa: PLC0415
            self._fc = FirecrawlApp(api_key=FIRECRAWL_KEY)
        return self._fc

    async def _start_session(self) -> str:
        """Inicia sesión en Alegra vía Firecrawl y retorna scrapeId."""
        fc = self._get_fc()
        result = fc.scrape_url(
            f"{ALEGRA_BASE}/inventory/items",
            params={"formats": ["markdown"]},
        )
        # SDK puede devolver dict o objeto — normalizar
        if isinstance(result, dict):
            scrape_id = (result.get("metadata") or {}).get("scrapeId") or result.get("scrapeId", "")
            markdown = result.get("markdown", "")
        else:
            scrape_id = getattr(getattr(result, "metadata", None), "scrapeId", "") or ""
            markdown = getattr(result, "markdown", "") or ""

        self._scrape_id = scrape_id

        # Verificar si está logueado
        if "login" in markdown.lower() or "contraseña" in markdown.lower() or "sign in" in markdown.lower():
            logger.info("Alegra requiere login — autenticando con Firecrawl")
            self._interact(
                scrape_id,
                f"Login con email {ALEGRA_EMAIL} y contraseña. Espera a que cargue el inventario.",
            )

        return scrape_id

    def _interact(self, scrape_id: str, prompt: str) -> str:
        """Llama a interact y retorna el output como string."""
        fc = self._get_fc()
        try:
            response = fc.interact(scrape_id, prompt=prompt)
        except AttributeError:
            # Versión SDK sin método interact — intentar vía scrape_url con actions
            try:
                response = fc.scrape_url(
                    f"{ALEGRA_BASE}/",
                    params={"actions": [{"type": "prompt", "prompt": prompt}]},
                )
            except Exception:
                return ""

        if isinstance(response, dict):
            return response.get("output") or response.get("markdown") or ""
        return getattr(response, "output", None) or getattr(response, "markdown", None) or ""

    def _stop_session(self) -> None:
        if self._scrape_id:
            try:
                fc = self._get_fc()
                if hasattr(fc, "stop_interaction"):
                    fc.stop_interaction(self._scrape_id)
            except Exception:
                pass
            self._scrape_id = None

    async def crear_item_moto(
        self,
        nombre: str,
        vin: str,
        precio_base: float,
        precio_costo: float,
        categoria: str = "Motos nuevas",
    ) -> dict:
        """
        Crea un ítem de moto individual en Alegra via Firecrawl /interact.
        Retorna {"success": True, "nombre": nombre, "vin": vin} o {"success": False, "error": ...}
        """
        if not FIRECRAWL_KEY:
            return {"success": False, "error": "FIRECRAWL_API_KEY no configurada"}

        try:
            scrape_id = await self._start_session()

            prompt = (
                f"Crea un nuevo producto de venta con estos datos exactos:\n"
                f"- Tipo: Producto\n"
                f"- Nombre: {nombre}\n"
                f"- Referencia: {vin}\n"
                f"- Categoría: {categoria}\n"
                f"- Precio base (sin IVA): {precio_base}\n"
                f"- Impuesto: IVA 19%\n"
                f"- Costo: {precio_costo}\n"
                f"- Inventariable: activado\n"
                f"- Cantidad inicial: 1\n"
                f"Haz clic en Guardar y confirma que el ítem fue creado."
            )

            output = self._interact(scrape_id, prompt)
            success = any(
                k in output.lower()
                for k in ["guardado", "creado", "exitosamente", "saved", "created"]
            )
            return {
                "success": success,
                "nombre": nombre,
                "vin": vin,
                "firecrawl_output": output[:300],
            }

        except Exception as ex:
            logger.error(f"Firecrawl crear_item_moto error: {ex}")
            return {"success": False, "error": str(ex)}
        finally:
            self._stop_session()

    async def crear_item_repuesto(
        self,
        nombre: str,
        referencia: str,
        precio: float,
        costo: float,
    ) -> dict:
        """Crea un ítem de repuesto en Alegra via Firecrawl /interact."""
        if not FIRECRAWL_KEY:
            return {"success": False, "error": "FIRECRAWL_API_KEY no configurada"}

        try:
            scrape_id = await self._start_session()

            prompt = (
                f"Crea un nuevo producto de venta con estos datos:\n"
                f"- Nombre: {nombre}\n"
                f"- Referencia: {referencia}\n"
                f"- Categoría: Repuestos\n"
                f"- Precio base (sin IVA): {precio}\n"
                f"- Impuesto: IVA 19%\n"
                f"- Costo: {costo}\n"
                f"- Inventariable: activado\n"
                f"Haz clic en Guardar."
            )

            output = self._interact(scrape_id, prompt)
            success = any(
                k in output.lower()
                for k in ["guardado", "creado", "exitosamente", "saved", "created"]
            )
            return {
                "success": success,
                "referencia": referencia,
                "firecrawl_output": output[:300],
            }

        except Exception as ex:
            logger.error(f"Firecrawl crear_item_repuesto error: {ex}")
            return {"success": False, "error": str(ex)}
        finally:
            self._stop_session()

    async def registrar_bill(
        self,
        proveedor_nit: str,
        numero_factura: str,
        fecha: str,
        fecha_vencimiento: str,
        items_para_bill: list[dict],
        observations: str = "",
    ) -> dict:
        """
        Registra una factura de compra (bill) en Alegra via Firecrawl /interact.
        items_para_bill: [{"nombre": ..., "cantidad": ..., "precio": ...}]
        """
        if not FIRECRAWL_KEY:
            return {"success": False, "error": "FIRECRAWL_API_KEY no configurada"}

        try:
            fc = self._get_fc()
            # Navegar directo a crear bill
            result = fc.scrape_url(
                f"{ALEGRA_BASE}/bills/add",
                params={"formats": ["markdown"]},
            )
            if isinstance(result, dict):
                scrape_id = (result.get("metadata") or {}).get("scrapeId") or result.get("scrapeId", "")
            else:
                scrape_id = getattr(getattr(result, "metadata", None), "scrapeId", "") or ""
            self._scrape_id = scrape_id

            items_str = "\n".join(
                f"  - {it['nombre']}: {it['cantidad']} unidades a ${it['precio']:,.0f}"
                for it in items_para_bill
            )

            prompt = (
                f"Crea una factura de compra con estos datos:\n"
                f"- Proveedor NIT: {proveedor_nit}\n"
                f"- Número de factura del proveedor: {numero_factura}\n"
                f"- Fecha: {fecha}\n"
                f"- Fecha vencimiento: {fecha_vencimiento}\n"
                f"- Observaciones: {observations}\n"
                f"- Ítems:\n{items_str}\n"
                f"Haz clic en Guardar y confirma que la factura de compra fue creada."
            )

            output = self._interact(scrape_id, prompt)
            success = any(
                k in output.lower()
                for k in ["guardado", "creado", "exitosamente", "saved", "created"]
            )
            return {
                "success": success,
                "numero_factura": numero_factura,
                "firecrawl_output": output[:300],
            }

        except Exception as ex:
            logger.error(f"Firecrawl registrar_bill error: {ex}")
            return {"success": False, "error": str(ex)}
        finally:
            self._stop_session()


# ── Singleton ─────────────────────────────────────────────────────────────────
_alegra_browser: AlegraFirecrawlClient | None = None


def get_alegra_browser() -> AlegraFirecrawlClient:
    global _alegra_browser
    if _alegra_browser is None:
        _alegra_browser = AlegraFirecrawlClient()
    return _alegra_browser
