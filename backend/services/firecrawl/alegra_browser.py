"""
AlegraFirecrawlClient — Firecrawl /interact con Playwright para crear ítems y bills en Alegra.
Profile persistente guarda login entre sesiones.
"""
import os
import logging

logger = logging.getLogger("firecrawl.alegra")

ALEGRA_BASE     = "https://app.alegra.com"
ALEGRA_EMAIL    = os.getenv("ALEGRA_EMAIL", "")
ALEGRA_PASSWORD = os.getenv("ALEGRA_TOKEN", "")  # ALEGRA_TOKEN = contraseña UI de Alegra
FIRECRAWL_KEY   = os.getenv("FIRECRAWL_API_KEY", "")
PROFILE_NAME    = "alegra-roddos"


def _get_fc():
    from firecrawl import Firecrawl  # noqa: PLC0415
    return Firecrawl(api_key=FIRECRAWL_KEY)


def _extract_scrape_id(result) -> str:
    if hasattr(result, "metadata") and result.metadata:
        sid = getattr(result.metadata, "scrape_id", None) or getattr(result.metadata, "scrapeId", None)
        if sid:
            return str(sid)
    if isinstance(result, dict):
        meta = result.get("metadata") or {}
        sid = meta.get("scrape_id") or meta.get("scrapeId")
        if sid:
            return str(sid)
    return ""


def _interact(fc, scrape_id: str, prompt: str = None, code: str = None, language: str = "python") -> str:
    try:
        if code:
            resp = fc.interact(scrape_id, code=code, language=language)
        else:
            resp = fc.interact(scrape_id, prompt=prompt)
        if isinstance(resp, dict):
            return resp.get("output") or resp.get("stdout") or resp.get("result") or ""
        return (
            getattr(resp, "output", None)
            or getattr(resp, "stdout", None)
            or getattr(resp, "result", None)
            or ""
        )
    except Exception as ex:
        logger.error(f"interact error: {ex}")
        return f"ERROR: {ex}"


async def _start_session(fc, url: str) -> str:
    """Scrape con profile persistente. Hace login si detecta pantalla de login."""
    result = fc.scrape(
        url,
        formats=["markdown"],
        profile={"name": PROFILE_NAME, "save_changes": True},
    )
    scrape_id = _extract_scrape_id(result)

    content = getattr(result, "markdown", "") or (result.get("markdown", "") if isinstance(result, dict) else "")

    if any(k in content.lower() for k in ["ingresar", "contraseña", "sign in", "log in", "iniciar"]):
        logger.info("Alegra requiere login — autenticando con Playwright...")
        playwright_login = f"""
import asyncio
await page.fill('input[type="email"], input[name="email"], input[id*="email"]', '{ALEGRA_EMAIL}')
await page.fill('input[type="password"]', '{ALEGRA_PASSWORD}')
await page.click('button[type="submit"], button:has-text("Ingresar"), button:has-text("Login")')
await page.wait_for_load_state('networkidle', timeout=15000)
print(await page.title())
"""
        out = _interact(fc, scrape_id, code=playwright_login, language="python")
        logger.info(f"Login result: {out[:100]}")

    return scrape_id


class AlegraFirecrawlClient:

    async def crear_item_moto(
        self,
        nombre: str,
        vin: str,
        precio_base: float,
        precio_costo: float,
        categoria: str = "Motos nuevas",
    ) -> dict:
        """
        Crea un ítem de moto individual en Alegra via Firecrawl + Playwright.
        Retorna {"success": True, "nombre": nombre, "vin": vin} o {"success": False, "error": ...}
        """
        if not FIRECRAWL_KEY:
            return {"success": False, "error": "FIRECRAWL_API_KEY no configurada"}

        fc = _get_fc()
        scrape_id = None
        try:
            scrape_id = await _start_session(fc, f"{ALEGRA_BASE}/item/add")

            playwright_code = f"""
import asyncio, json

# Esperar que cargue el formulario
await page.wait_for_load_state('networkidle', timeout=15000)

# Nombre
await page.fill('input[id*="name"], input[placeholder*="nombre"], input[name*="name"]', '{nombre}')

# Referencia
await page.fill('input[id*="reference"], input[placeholder*="referencia"], input[name*="reference"]', '{vin}')

# Categoría
cat_selectors = ['select[id*="category"]', 'select[name*="category"]', '[aria-label*="ategor"]']
for sel in cat_selectors:
    try:
        if await page.is_visible(sel):
            await page.select_option(sel, label='{categoria}')
            break
    except:
        pass

# Precio base
price_inputs = await page.query_selector_all('input[id*="price"], input[placeholder*="precio"]')
if price_inputs:
    await price_inputs[0].fill('{precio_base}')

# Costo
cost_inputs = await page.query_selector_all('input[id*="cost"], input[placeholder*="costo"]')
if cost_inputs:
    await cost_inputs[0].fill('{precio_costo}')

# Cantidad inicial = 1
qty_inputs = await page.query_selector_all('input[id*="quantity"], input[placeholder*="cantidad"]')
if qty_inputs:
    await qty_inputs[0].fill('1')

# Inventariable toggle — activar si no está
try:
    toggle = await page.query_selector('[id*="inventoriable"], [id*="inventariable"]')
    if toggle:
        checked = await toggle.is_checked()
        if not checked:
            await toggle.click()
except:
    pass

# Scroll para ver Configuración contable
await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
await page.wait_for_timeout(1000)

# Guardar
await page.click('button:has-text("Guardar"), button[type="submit"]')
await page.wait_for_load_state('networkidle', timeout=10000)

title = await page.title()
url = page.url
print(json.dumps({{"title": title, "url": url}}))
"""
            out = _interact(fc, scrape_id, code=playwright_code, language="python")
            logger.info(f"crear_item_moto output: {out[:200]}")

            success = any(k in (out or "").lower() for k in ["item", "view", "edit", "guardado", "created"])
            return {"success": success, "nombre": nombre, "vin": vin, "firecrawl_output": (out or "")[:300]}

        except Exception as ex:
            logger.error(f"crear_item_moto error: {ex}")
            return {"success": False, "error": str(ex)}
        finally:
            if scrape_id:
                try:
                    fc.stop_interaction(scrape_id)  # guarda el profile
                except Exception:
                    pass

    async def crear_item_repuesto(
        self,
        nombre: str,
        referencia: str,
        precio: float,
        costo: float,
    ) -> dict:
        """Crea un ítem de repuesto en Alegra via Firecrawl + Playwright."""
        if not FIRECRAWL_KEY:
            return {"success": False, "error": "FIRECRAWL_API_KEY no configurada"}

        fc = _get_fc()
        scrape_id = None
        try:
            scrape_id = await _start_session(fc, f"{ALEGRA_BASE}/item/add")

            playwright_code = f"""
import asyncio, json
await page.wait_for_load_state('networkidle', timeout=15000)
await page.fill('input[id*="name"], input[placeholder*="nombre"]', '{nombre}')
await page.fill('input[id*="reference"], input[placeholder*="referencia"]', '{referencia}')
for sel in ['select[id*="category"]', 'select[name*="category"]']:
    try:
        if await page.is_visible(sel):
            await page.select_option(sel, label='Repuestos')
            break
    except:
        pass
price_inputs = await page.query_selector_all('input[id*="price"], input[placeholder*="precio"]')
if price_inputs:
    await price_inputs[0].fill('{precio}')
cost_inputs = await page.query_selector_all('input[id*="cost"], input[placeholder*="costo"]')
if cost_inputs:
    await cost_inputs[0].fill('{costo}')
qty_inputs = await page.query_selector_all('input[id*="quantity"], input[placeholder*="cantidad"]')
if qty_inputs:
    await qty_inputs[0].fill('0')
await page.click('button:has-text("Guardar"), button[type="submit"]')
await page.wait_for_load_state('networkidle', timeout=10000)
print(json.dumps({{"url": page.url, "title": await page.title()}}))
"""
            out = _interact(fc, scrape_id, code=playwright_code, language="python")
            success = any(k in (out or "").lower() for k in ["item", "view", "edit", "guardado", "created"])
            return {"success": success, "referencia": referencia, "firecrawl_output": (out or "")[:300]}

        except Exception as ex:
            logger.error(f"crear_item_repuesto error: {ex}")
            return {"success": False, "error": str(ex)}
        finally:
            if scrape_id:
                try:
                    fc.stop_interaction(scrape_id)
                except Exception:
                    pass

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
        Registra una factura de compra (bill) en Alegra via Firecrawl + Playwright.
        items_para_bill: [{"nombre": ..., "cantidad": ..., "precio": ...}]
        """
        if not FIRECRAWL_KEY:
            return {"success": False, "error": "FIRECRAWL_API_KEY no configurada"}

        fc = _get_fc()
        scrape_id = None
        try:
            scrape_id = await _start_session(fc, f"{ALEGRA_BASE}/bills/add")

            playwright_code = f"""
import asyncio, json
await page.wait_for_load_state('networkidle', timeout=15000)

# Proveedor
prov_input = await page.query_selector('input[id*="provider"], input[id*="supplier"], input[placeholder*="proveedor"]')
if prov_input:
    await prov_input.fill('{proveedor_nit}')
    await page.wait_for_timeout(1000)
    option = await page.query_selector('.dropdown-item, [role="option"]')
    if option:
        await option.click()

# Número factura proveedor
await page.fill('input[id*="number"], input[placeholder*="número"], input[placeholder*="factura"]', '{numero_factura}')

# Fechas
date_inputs = await page.query_selector_all('input[type="date"], input[id*="date"]')
if len(date_inputs) > 0:
    await date_inputs[0].fill('{fecha}')
if len(date_inputs) > 1:
    await date_inputs[1].fill('{fecha_vencimiento}')

# Guardar
await page.click('button:has-text("Guardar"), button[type="submit"]')
await page.wait_for_load_state('networkidle', timeout=10000)
print(json.dumps({{"url": page.url, "title": await page.title()}}))
"""
            out = _interact(fc, scrape_id, code=playwright_code, language="python")
            logger.info(f"registrar_bill output: {out[:200]}")
            success = any(k in (out or "").lower() for k in ["bill", "view", "guardado", "created"])
            return {"success": success, "numero_factura": numero_factura, "firecrawl_output": (out or "")[:300]}

        except Exception as ex:
            logger.error(f"registrar_bill error: {ex}")
            return {"success": False, "error": str(ex)}
        finally:
            if scrape_id:
                try:
                    fc.stop_interaction(scrape_id)
                except Exception:
                    pass


# ── Singleton ─────────────────────────────────────────────────────────────────
_alegra_browser: AlegraFirecrawlClient | None = None


def get_alegra_browser() -> AlegraFirecrawlClient:
    global _alegra_browser
    if _alegra_browser is None:
        _alegra_browser = AlegraFirecrawlClient()
    return _alegra_browser
