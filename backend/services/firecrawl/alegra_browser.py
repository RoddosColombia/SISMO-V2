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
ALEGRA_PASSWORD = os.getenv("ALEGRA_TOKEN", "")  # en Render, ALEGRA_TOKEN ES la contraseña de usuario
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

    def _extract_scrape_id(self, result) -> str:
        """Extrae scrape_id del resultado de fc.scrape() — soporta snake_case y camelCase."""
        # Objeto con atributo metadata
        if hasattr(result, "metadata") and result.metadata:
            meta = result.metadata
            sid = getattr(meta, "scrape_id", None) or getattr(meta, "scrapeId", None)
            if sid:
                return str(sid)
        # Dict plano
        if isinstance(result, dict):
            meta = result.get("metadata") or {}
            sid = (
                meta.get("scrape_id")
                or meta.get("scrapeId")
                or result.get("scrape_id")
                or result.get("scrapeId")
            )
            if sid:
                return str(sid)
        return ""

    async def _start_session(self, url: str | None = None) -> str:
        """Navega a url (o /inventory/items/add) y hace login si es necesario. Retorna scrapeId."""
        target = url or f"{ALEGRA_BASE}/inventory/items/add"
        fc = self._get_fc()
        result = fc.scrape(target)

        # Normalizar resultado (SDK puede devolver dict o objeto)
        if isinstance(result, dict):
            content = result.get("markdown", "") or ""
        else:
            content = getattr(result, "markdown", "") or ""

        scrape_id = self._extract_scrape_id(result)
        self._scrape_id = scrape_id

        # Detectar página de login y autenticar
        login_keywords = ["ingresar", "contraseña", "login", "sign in", "iniciar sesión", "password"]
        if any(k in content.lower() for k in login_keywords):
            logger.info("Alegra requiere login — autenticando con Firecrawl")
            login_prompt = (
                f"Estoy en la página de login de Alegra. "
                f"Ingresa el email '{ALEGRA_EMAIL}' en el campo de email. "
                f"Ingresa la contraseña '{ALEGRA_PASSWORD}' en el campo de contraseña. "
                f"Haz clic en el botón de ingresar/login. "
                f"Espera a que cargue el dashboard de Alegra."
            )
            login_output = self._interact(scrape_id, login_prompt)
            if any(k in login_output.lower() for k in ["error", "incorrecto", "invalid", "failed"]):
                logger.error(f"Firecrawl login Alegra falló: {login_output[:200]}")
            else:
                logger.info("Firecrawl login Alegra exitoso")

        return scrape_id

    def _interact(self, scrape_id: str, prompt: str) -> str:
        """Llama a interact y retorna el output como string."""
        fc = self._get_fc()
        try:
            response = fc.interact(scrape_id, prompt=prompt)
        except AttributeError:
            # Versión SDK sin método interact — intentar vía scrape con actions
            try:
                response = fc.scrape(
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
            scrape_id = await self._start_session(f"{ALEGRA_BASE}/item/add")

            prompt = (
                f"Rellena el formulario de nuevo producto con estos datos exactos:\n"
                f"1. Campo 'Nombre': escribe '{nombre}'\n"
                f"2. Campo 'Referencia': escribe '{vin}'\n"
                f"3. Campo 'Categoría': selecciona 'Motos nuevas'\n"
                f"4. Campo 'Precio base': escribe '{precio_base}'\n"
                f"5. Campo 'Impuesto': selecciona 'IVA - (19%)'\n"
                f"6. Campo 'Costo': escribe '{precio_costo}'\n"
                f"7. Activa el toggle 'Inventariable' si no está activado\n"
                f"8. Campo 'Cantidad inicial': escribe '1'\n"
                f"9. En 'Configuración contable':\n"
                f"   - 'Cuenta Contable': selecciona '41350501 - Motos'\n"
                f"   - 'Cuenta de inventario': selecciona '14350101 - Motos'\n"
                f"   - 'Cuenta de costo de venta': selecciona '61350501 - Motos'\n"
                f"10. Haz clic en el botón 'Guardar'\n"
                f"11. Confirma que el ítem fue creado exitosamente"
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
            scrape_id = await self._start_session(f"{ALEGRA_BASE}/item/add")

            prompt = (
                f"Rellena el formulario de nuevo producto con estos datos:\n"
                f"1. Campo 'Nombre': escribe '{nombre}'\n"
                f"2. Campo 'Referencia': escribe '{referencia}'\n"
                f"3. Campo 'Categoría': selecciona 'Repuestos'\n"
                f"4. Campo 'Precio base': escribe '{precio}'\n"
                f"5. Campo 'Impuesto': selecciona 'IVA - (19%)'\n"
                f"6. Campo 'Costo': escribe '{costo}'\n"
                f"7. Activa el toggle 'Inventariable' si no está activado\n"
                f"8. En 'Configuración contable':\n"
                f"   - 'Cuenta Contable': selecciona '41350601 - Repuestos'\n"
                f"   - 'Cuenta de inventario': selecciona '14350102 - Repuestos'\n"
                f"   - 'Cuenta de costo de venta': selecciona '61350601 - Repuestos'\n"
                f"9. Haz clic en el botón 'Guardar'\n"
                f"10. Confirma que el ítem fue creado exitosamente"
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
            scrape_id = await self._start_session(f"{ALEGRA_BASE}/bills/add")

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
