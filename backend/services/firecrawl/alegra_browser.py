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


    async def crear_factura_venta(self, datos: dict) -> dict:
        """
        Crea factura de venta de moto en Alegra via Playwright.
        datos = {
            cliente_nombre, cliente_cedula, cliente_telefono,
            cliente_direccion, cliente_email,
            moto_vin, moto_motor, moto_modelo, moto_color,
            plan, modo_pago, cuota_inicial,
            incluir_soat=True, incluir_matricula=True, incluir_gps=True
        }
        """
        if not FIRECRAWL_KEY:
            return {"success": False, "error": "FIRECRAWL_API_KEY no configurada"}
        fc = _get_fc()
        scrape_id = None
        try:
            scrape_id = await _start_session(fc, f"{ALEGRA_BASE}/income/invoices/add")
            cliente = datos.get("cliente_nombre", "")
            vin     = datos.get("moto_vin", "")
            motor   = datos.get("moto_motor", "")
            modelo  = datos.get("moto_modelo", "TVS Raider 125")
            color   = datos.get("moto_color", "")
            plan    = datos.get("plan", "P52S")
            modo    = datos.get("modo_pago", "semanal")
            cuota   = datos.get("cuota_inicial", 0)
            obs     = f"Plan:{plan} | Pago:{modo} | Cuota:${cuota:,} | VIN:{vin} | Motor:{motor}"

            code = f"""
import asyncio, json
await page.wait_for_load_state('networkidle', timeout=20000)
# Cliente
try:
    ci = await page.query_selector_all('input[placeholder*="liente"], input[placeholder*="ontacto"], input[id*="client"]')
    if ci:
        await ci[0].fill('{cliente}')
        await page.wait_for_timeout(1500)
        op = await page.query_selector('[role="option"],[class*="option"],[class*="item"]')
        if op: await op.click()
except: pass
# Moto por VIN
try:
    ii = await page.query_selector_all('input[placeholder*="tem"],input[placeholder*="roducto"],input[id*="item"]')
    if ii:
        await ii[0].fill('{vin}')
        await page.wait_for_timeout(2000)
        op = await page.query_selector('[role="option"],[class*="option"]')
        if op: await op.click()
except: pass
# Observaciones
try:
    ob = await page.query_selector('textarea,input[placeholder*="bs"],input[placeholder*="ota"]')
    if ob: await ob.fill('{obs}')
except: pass
# Guardar
await page.click('button:has-text("Guardar"),button:has-text("Crear"),button[type="submit"]')
await page.wait_for_load_state('networkidle', timeout=15000)
print(json.dumps({{"url": page.url, "title": await page.title()}}))
"""
            out = _interact(fc, scrape_id, code=code, language="python")
            logger.info(f"crear_factura_venta output: {out[:200]}")
            ok = any(k in (out or "").lower() for k in ["invoice", "factura", "view", "/income/", "guardado"])
            return {"success": ok, "output": (out or "")[:400]}
        except Exception as ex:
            logger.error(f"crear_factura_venta error: {ex}")
            return {"success": False, "error": str(ex)}
        finally:
            if scrape_id:
                try:
                    fc.stop_interaction(scrape_id)
                except Exception:
                    pass

    async def registrar_journal(self, datos: dict) -> dict:
        """
        Registra un asiento contable (journal) en Alegra via Playwright.
        datos = {
            descripcion, fecha,
            entries: [{"cuenta_nombre": str, "debito": float, "credito": float}]
        }
        """
        if not FIRECRAWL_KEY:
            return {"success": False, "error": "FIRECRAWL_API_KEY no configurada"}
        fc = _get_fc()
        scrape_id = None
        try:
            scrape_id = await _start_session(fc, f"{ALEGRA_BASE}/accounting/journals/add")
            descripcion = datos.get("descripcion", "")
            fecha = datos.get("fecha", "")

            code = f"""
import asyncio, json
await page.wait_for_load_state('networkidle', timeout=20000)
try:
    desc = await page.query_selector('input[placeholder*="escripcion"],textarea[placeholder*="escripcion"],input[id*="desc"]')
    if desc: await desc.fill('{descripcion}')
except: pass
try:
    di = await page.query_selector_all('input[type="date"],input[id*="date"]')
    if di: await di[0].fill('{fecha}')
except: pass
await page.click('button:has-text("Guardar"),button[type="submit"]')
await page.wait_for_load_state('networkidle', timeout=15000)
print(json.dumps({{"url": page.url, "title": await page.title()}}))
"""
            out = _interact(fc, scrape_id, code=code, language="python")
            ok = any(k in (out or "").lower() for k in ["journal", "asiento", "view", "guardado"])
            return {"success": ok, "output": (out or "")[:400]}
        except Exception as ex:
            logger.error(f"registrar_journal error: {ex}")
            return {"success": False, "error": str(ex)}
        finally:
            if scrape_id:
                try:
                    fc.stop_interaction(scrape_id)
                except Exception:
                    pass

    async def registrar_pago(self, datos: dict) -> dict:
        """
        Registra un pago recibido en Alegra via Playwright.
        datos = {
            cliente_nombre, monto, fecha, banco_nombre,
            concepto, factura_numero (opcional)
        }
        """
        if not FIRECRAWL_KEY:
            return {"success": False, "error": "FIRECRAWL_API_KEY no configurada"}
        fc = _get_fc()
        scrape_id = None
        try:
            scrape_id = await _start_session(fc, f"{ALEGRA_BASE}/income/payments/add")
            cliente  = datos.get("cliente_nombre", "")
            monto    = datos.get("monto", 0)
            fecha    = datos.get("fecha", "")
            concepto = datos.get("concepto", "")

            code = f"""
import asyncio, json
await page.wait_for_load_state('networkidle', timeout=20000)
try:
    ci = await page.query_selector_all('input[placeholder*="liente"],input[id*="client"]')
    if ci:
        await ci[0].fill('{cliente}')
        await page.wait_for_timeout(1500)
        op = await page.query_selector('[role="option"]')
        if op: await op.click()
except: pass
try:
    mi = await page.query_selector_all('input[placeholder*="onto"],input[id*="amount"],input[id*="value"]')
    if mi: await mi[0].fill(str({monto}))
except: pass
try:
    di = await page.query_selector_all('input[type="date"],input[id*="date"]')
    if di: await di[0].fill('{fecha}')
except: pass
try:
    ob = await page.query_selector('textarea,input[placeholder*="obs"],input[placeholder*="nota"]')
    if ob: await ob.fill('{concepto}')
except: pass
await page.click('button:has-text("Guardar"),button:has-text("Registrar"),button[type="submit"]')
await page.wait_for_load_state('networkidle', timeout=15000)
print(json.dumps({{"url": page.url, "title": await page.title()}}))
"""
            out = _interact(fc, scrape_id, code=code, language="python")
            ok = any(k in (out or "").lower() for k in ["payment", "pago", "view", "guardado"])
            return {"success": ok, "output": (out or "")[:400]}
        except Exception as ex:
            logger.error(f"registrar_pago error: {ex}")
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


# ─────────────────────────────────────────────────────────────────────────────
# V2 — Estrategia robusta vía fc.agent()
# Agregado 2026-04-27. NO sobrescribe funciones previas (CLAUDE.md regla de oro).
# Diagnóstico completo en .planning/DIAGNOSTICO_CONTADOR_FIRECRAWL.md
# ─────────────────────────────────────────────────────────────────────────────
import re
import json as _json

# ALEGRA_UI_PASSWORD: contraseña real de la UI Alegra (NO la API key).
# La versión vieja confundía esto con ALEGRA_TOKEN (la API key). Aquí lo
# leemos del slot correcto y validamos antes de cualquier login.
ALEGRA_UI_PASSWORD = os.getenv("ALEGRA_PASSWORD", "")

# Schema que pedimos al agente IA de Firecrawl tras completar la factura.
_FACTURA_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "factura_creada":   {"type": "boolean"},
        "alegra_invoice_id": {"type": "string", "description": "ID numérico de Alegra extraído de la URL final, ej '12345'"},
        "alegra_url":        {"type": "string", "description": "URL final tras guardar, ej 'https://app.alegra.com/invoice/12345'"},
        "factura_total":     {"type": "number", "description": "Total final mostrado en la factura"},
        "error":             {"type": "string", "description": "Si factura_creada=false, motivo concreto"},
    },
    "required": ["factura_creada"],
}


def _validar_credenciales_alegra() -> str | None:
    """Devuelve None si todo OK, o un mensaje de error en español."""
    if not FIRECRAWL_KEY:
        return "FIRECRAWL_API_KEY no configurada en el entorno."
    if not ALEGRA_EMAIL:
        return "ALEGRA_EMAIL no configurado en el entorno."
    if not ALEGRA_UI_PASSWORD:
        return (
            "ALEGRA_PASSWORD (contraseña UI) no configurado. "
            "OJO: ALEGRA_TOKEN es la API key, NO la contraseña UI. "
            "Configura ALEGRA_PASSWORD con la contraseña real de app.alegra.com."
        )
    return None


def _build_factura_prompt(datos: dict) -> str:
    """Construye el prompt para fc.agent() con todos los datos requeridos.

    El agente IA de Firecrawl resuelve los selectores y completa el formulario
    de Alegra paso a paso (mucho más robusto que escribir Playwright a mano).
    """
    cliente = datos.get("cliente_nombre", "").strip()
    cedula  = datos.get("cliente_cedula", "").strip()
    tel     = datos.get("cliente_telefono", "")
    direc   = datos.get("cliente_direccion", "")
    email   = datos.get("cliente_email", "")
    vin     = datos.get("moto_vin", "").strip()
    motor   = datos.get("moto_motor", "").strip()
    modelo  = datos.get("moto_modelo", "TVS Raider 125")
    color   = datos.get("moto_color", "")
    plan    = datos.get("plan", "P52S")
    modo    = datos.get("modo_pago", "semanal")
    cuota_inicial = datos.get("cuota_inicial") or 0
    incluir_soat      = datos.get("incluir_soat", True)
    incluir_matricula = datos.get("incluir_matricula", True)
    incluir_gps       = datos.get("incluir_gps", True)

    lineas_extras: list[str] = []
    if incluir_soat:
        lineas_extras.append("- Línea SOAT: $363.300 (exento de IVA, ítem ID 30 en Alegra)")
    if incluir_matricula:
        lineas_extras.append("- Línea Matrícula: $296.700 (exento de IVA, ítem ID 29)")
    if incluir_gps:
        lineas_extras.append("- Línea GPS: $69.580 base + IVA 19% = $82.800 cliente (ítem ID 28)")

    extras_block = "\n".join(lineas_extras) if lineas_extras else "(sin rubros adicionales)"

    return f"""Estás autenticado en Alegra Colombia (https://app.alegra.com) con la cuenta de RODDOS S.A.S.
Si la sesión está cerrada, inicia sesión con email "{ALEGRA_EMAIL}" y contraseña "{ALEGRA_UI_PASSWORD}".

OBJETIVO: Crear una factura de venta de moto a crédito (status open, paymentForm CREDIT) con los siguientes datos.

NAVEGA a: https://app.alegra.com/income/invoices/add

CLIENTE
- Nombre: {cliente}
- Cédula/identificación: {cedula}
{f"- Teléfono: {tel}" if tel else ""}
{f"- Dirección: {direc}" if direc else ""}
{f"- Email: {email}" if email else ""}

Si el cliente con esa cédula NO existe en Alegra, créalo como persona natural, régimen simplificado, tipo "client",
identification type "CC" y guárdalo antes de continuar con la factura.

ÍTEMS DE LA FACTURA (en orden)
1. Moto. Buscar el ítem por su VIN (referencia) "{vin}" en el campo de productos. Si NO aparece, reportar error con
   error="ITEM_VIN_NO_ENCONTRADO". Si aparece, seleccionarlo, cantidad 1.
   El nombre debe contener: "{modelo} {color} - VIN: {vin} / Motor: {motor}".
{extras_block}

CONFIGURACIÓN
- Forma de pago: CRÉDITO (paymentForm CREDIT, no contado)
- Estado: open (no borrador)
- Operación: STANDARD (factura electrónica DIAN)
- Observaciones: "Venta moto {modelo} {color} plan {plan} {modo} — VIN: {vin} — Motor: {motor} — Cuota inicial $({cuota_inicial:,})"

PASOS
1. Si la página de login aparece, ingresa con las credenciales de arriba.
2. Navega a /income/invoices/add.
3. Llena los campos en el orden indicado: cliente → ítems → forma de pago → observaciones.
4. Haz clic en "Guardar" o "Crear" para emitir la factura.
5. Espera que la URL cambie a un patrón con un id numérico (ej: /invoice/12345 o /sales/invoices/12345).
6. Extrae el id numérico de la URL final → eso es alegra_invoice_id.
7. Devuelve el JSON del schema con factura_creada=true, alegra_invoice_id, alegra_url y factura_total.

REGLAS
- NO uses caracteres extra como apóstrofes invertidos ni código.
- Si falla cualquier paso, devuelve factura_creada=false y error con la causa concreta.
- NO marques success si la URL final sigue siendo /income/invoices/add o /login.
- VIN y motor son obligatorios — si faltan, error="VIN_O_MOTOR_FALTANTE".
"""


_RE_INVOICE_ID = re.compile(r"/(?:invoice|sales/invoices?)/(\d+)", re.IGNORECASE)


def _coerce_agent_response(raw) -> dict:
    """Acepta respuestas pydantic / dict / str-json y devuelve dict normalizado."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        try:
            return raw.model_dump()
        except Exception:
            pass
    if hasattr(raw, "dict"):
        try:
            return raw.dict()
        except Exception:
            pass
    if isinstance(raw, str):
        try:
            return _json.loads(raw)
        except Exception:
            return {"raw_text": raw}
    # Fallback: introspect attributes
    out = {}
    for k in ("factura_creada", "alegra_invoice_id", "alegra_url", "factura_total", "error", "data", "json", "result"):
        v = getattr(raw, k, None)
        if v is not None:
            out[k] = v
    return out


async def crear_factura_venta_agente(datos: dict) -> dict:
    """V2 — Crea factura de venta vía fc.agent() (LLM-driven UI automation).

    Mucho más robusto que `crear_factura_venta` porque:
    - El agente IA de Firecrawl resuelve los selectores dinámicamente.
    - Maneja redirects post-login automáticamente.
    - Devuelve JSON estructurado (no heurística sobre texto).
    - Sin f-string injection: todos los datos van en prompt natural.

    Args:
        datos: dict con cliente_nombre, cliente_cedula, moto_vin, moto_motor,
               moto_modelo, plan, modo_pago, cuota_inicial, e flags
               incluir_soat / incluir_matricula / incluir_gps.

    Returns:
        dict con success, alegra_id (id numérico real, NO "firecrawl"),
        alegra_url, factura_total, error si aplica.
    """
    err = _validar_credenciales_alegra()
    if err:
        logger.error("crear_factura_venta_agente — credenciales: %s", err)
        return {"success": False, "error": err, "stage": "credentials"}

    # Validación temprana de campos críticos
    vin   = (datos.get("moto_vin") or "").strip()
    motor = (datos.get("moto_motor") or "").strip()
    cliente_nombre = (datos.get("cliente_nombre") or "").strip()
    cliente_cedula = (datos.get("cliente_cedula") or "").strip()
    if not vin or not motor:
        return {"success": False, "error": "VIN y motor son obligatorios para facturar.", "stage": "validation"}
    if not cliente_nombre or not cliente_cedula:
        return {"success": False, "error": "Nombre y cédula del cliente son obligatorios.", "stage": "validation"}

    fc = _get_fc()
    prompt = _build_factura_prompt(datos)

    logger.info(
        "crear_factura_venta_agente.start vin=%s cliente=%s modelo=%s plan=%s",
        vin, cliente_cedula, datos.get("moto_modelo"), datos.get("plan"),
    )

    try:
        # fc.agent es síncrono; lo dejamos en thread para no bloquear el event loop.
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        raw = await loop.run_in_executor(
            None,
            lambda: fc.agent(
                urls=[f"{ALEGRA_BASE}/income/invoices/add"],
                prompt=prompt,
                schema=_FACTURA_RESPONSE_SCHEMA,
                model="spark-1-pro",
            ),
        )
    except AttributeError as ex:
        # SDK no expone .agent — usar fallback manual con scrape+interact
        logger.exception("Firecrawl SDK no expone .agent — fallback no implementado en V2")
        return {
            "success": False,
            "error": (
                f"Firecrawl SDK incompatible: {ex}. "
                f"Versión instalada no expone .agent(). Pinea firecrawl==4.23.0."
            ),
            "stage": "sdk_incompatible",
        }
    except Exception as ex:
        logger.exception("crear_factura_venta_agente — fc.agent lanzó excepción")
        return {
            "success": False,
            "error": f"Firecrawl agent error: {type(ex).__name__}: {ex}",
            "stage": "agent_call",
        }

    parsed = _coerce_agent_response(raw)
    logger.info("crear_factura_venta_agente.parsed=%s", _json.dumps(parsed)[:500])

    # Algunos SDKs envuelven el JSON en data.json o data.result
    inner = parsed.get("data") or parsed.get("json") or parsed.get("result") or parsed
    if isinstance(inner, dict) and not parsed.get("alegra_invoice_id") and inner.get("alegra_invoice_id"):
        parsed = inner

    factura_creada = bool(parsed.get("factura_creada"))
    alegra_id    = (parsed.get("alegra_invoice_id") or "").strip()
    alegra_url   = (parsed.get("alegra_url") or "").strip()
    total        = parsed.get("factura_total")
    agent_error  = parsed.get("error")

    # Recurso de seguridad: si el agente dijo success pero no extrajo id,
    # intentar parsearlo de la URL final.
    if factura_creada and not alegra_id and alegra_url:
        m = _RE_INVOICE_ID.search(alegra_url)
        if m:
            alegra_id = m.group(1)

    # Verificación dura: success solo si tenemos id numérico real.
    if not factura_creada or not alegra_id.isdigit():
        return {
            "success": False,
            "error": agent_error or "El agente no logró confirmar la creación de la factura (sin id numérico).",
            "stage": "verification",
            "agent_response": parsed,
        }

    return {
        "success":      True,
        "alegra_id":    alegra_id,
        "alegra_url":   alegra_url,
        "factura_total": total,
        "stage":        "completed",
        "agent_response": parsed,
    }


async def healthcheck_alegra_session() -> dict:
    """Verifica que la sesión Alegra esté logeada vía Firecrawl.

    Útil para `GET /api/health/firecrawl`. Hace un scrape del dashboard y
    chequea que NO devuelva "iniciar sesión" en el markdown.
    """
    err = _validar_credenciales_alegra()
    if err:
        return {"ok": False, "error": err}
    try:
        fc = _get_fc()
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: fc.scrape(
                f"{ALEGRA_BASE}/dashboard",
                formats=["markdown"],
                profile={"name": PROFILE_NAME, "save_changes": True},
            ),
        )
        markdown = getattr(result, "markdown", "") or ""
        if isinstance(result, dict):
            markdown = markdown or result.get("markdown", "")
        logueado = not any(k in markdown.lower() for k in ["iniciar sesión", "iniciar sesion", "ingresar", "log in", "sign in"])
        return {
            "ok":            logueado,
            "logueado":      logueado,
            "markdown_chars": len(markdown),
            "url":           ALEGRA_BASE + "/dashboard",
        }
    except Exception as ex:
        logger.exception("healthcheck_alegra_session falló")
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}


# ─────────────────────────────────────────────────────────────────────────────
# V2 — Crear lote de motos (referencia=VIN) vía fc.agent()
# Cada moto es un ítem inventariable independiente con cuenta motos.
# ─────────────────────────────────────────────────────────────────────────────

_LOTE_MOTOS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "items_creados": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "vin":       {"type": "string"},
                    "alegra_id": {"type": "string"},
                    "nombre":    {"type": "string"},
                },
                "required": ["vin", "alegra_id"],
            },
        },
        "items_omitidos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "vin":       {"type": "string"},
                    "alegra_id": {"type": "string"},
                    "razon":     {"type": "string"},
                },
            },
        },
        "bill_alegra_id":  {"type": "string"},
        "bill_alegra_url": {"type": "string"},
        "errores":         {"type": "array", "items": {"type": "object"}},
        "todo_ok":         {"type": "boolean"},
    },
    "required": ["items_creados", "todo_ok"],
}


# Precio base Alegra (sin IVA) — catálogo canónico RODDOS 27-abril-2026
_PRECIO_BASE_ALEGRA_MOTO = {
    "TVS Raider 125": 6_554_622,
    "TVS Sport 100":  4_831_933,
}


def _build_lote_motos_prompt(motos: list[dict], proveedor_nit: str,
                             proveedor_nombre: str, numero_factura: str,
                             fecha: str) -> str:
    """Prompt para crear N ítems moto + bill al proveedor en una sesión."""
    lineas = []
    for m in motos:
        vin    = (m.get("vin") or "").strip().upper()
        motor  = (m.get("motor") or "").strip()
        modelo = m.get("modelo", "TVS Raider 125")
        color  = m.get("color", "")
        costo  = float(m.get("precio_costo") or _PRECIO_BASE_ALEGRA_MOTO.get(modelo, 6_554_622))
        precio = _PRECIO_BASE_ALEGRA_MOTO.get(modelo, 6_554_622)
        nombre = f"{modelo} {color} - VIN: {vin} / Motor: {motor}".strip()
        lineas.append(
            f"- VIN={vin} | motor={motor} | modelo={modelo} | color={color} | "
            f"costo_unitario={costo} | precio_venta_base={precio} | nombre={nombre!r}"
        )
    lista_motos = "\n".join(lineas) if lineas else "(lote vacío)"

    return f"""Estás autenticado en Alegra Colombia (https://app.alegra.com) con cuenta RODDOS S.A.S.
Si la sesión está cerrada, inicia sesión: email "{ALEGRA_EMAIL}" / password "{ALEGRA_UI_PASSWORD}".

OBJETIVO: Registrar la llegada de un lote de motos. Esto requiere DOS pasos en Alegra:
  PASO A — Crear un ítem inventariable INDIVIDUAL por cada moto (referencia = VIN).
  PASO B — Crear una factura de compra (bill) al proveedor con todas las motos del lote.

CONFIGURACIÓN OBLIGATORIA por ÍTEM moto:
- Tipo: producto inventariable (isInventoriable=true)
- Categoría: "Motos nuevas" (id=1)
- Reference: VIN exacto (en mayúsculas, sin espacios)
- Cuentas contables (CRÍTICAS — sin estas Alegra rechaza con code 1008):
    Ingreso ventas:       5442 (NIIF 41350501)
    Inventario activo:    5348 (NIIF 14350101)
    Costo de ventas:      5520 (NIIF 61350501)
- Precio venta sin IVA: según modelo (Raider 6554622 / Sport 4831933)
- IVA: 19% (id 4 en Alegra)
- Costo unitario: el indicado en la lista
- Cantidad inicial: 1
- Bodega/almacén: la default de motos (la creada por defecto está bien)

LISTA DEL LOTE ({len(motos)} motos):
{lista_motos}

REGLAS DE IDEMPOTENCIA:
- Antes de crear, busca por reference=VIN en /items?reference=. Si ya existe un ítem con ese VIN exacto,
  NO lo dupliques: márcalo en items_omitidos con razon="ya_existia" y reusa su id en el bill.
- Si encuentras un VIN duplicado en el lote, créalo solo una vez.

PASO B — BILL al proveedor:
- Proveedor identification: {proveedor_nit}
- Proveedor nombre: {proveedor_nombre or 'Auteco Mobility S.A.S.'}
- Número factura proveedor: {numero_factura}
- Fecha: {fecha}
- Fecha vencimiento: misma fecha o +90 días, según política Auteco
- Líneas del bill: una por cada moto del lote, cantidad=1, precio=costo_unitario
- Observaciones: "[AC] Compra lote {len(motos)} motos — Factura proveedor {numero_factura}"
- Si proveedor NIT en {{"860024781","901249413"}} → es AUTORETENEDOR (no aplicar ReteFuente).

ENTREGABLE — devuelve JSON con:
- items_creados: lista de {{vin, alegra_id, nombre}} por cada ítem moto creado.
- items_omitidos: lista de {{vin, alegra_id, razon}} por motos que ya existían.
- bill_alegra_id: id numérico del bill creado en Alegra (extraído de la URL final tipo /bill/12345 o /purchases/bills/12345).
- bill_alegra_url: URL del bill recién creado.
- errores: lista de {{vin?, etapa, mensaje}} por cualquier fallo individual.
- todo_ok: true SOLO si todas las motos quedaron en Alegra y el bill se creó con id numérico real.

NO inventes IDs. NO uses la cadena "firecrawl" como id. Si no logras extraer un id numérico, marca error.
"""


async def crear_lote_motos_agente(
    motos: list[dict],
    proveedor_nit: str,
    numero_factura: str,
    fecha: str,
    proveedor_nombre: str = "Auteco Mobility S.A.S.",
) -> dict:
    """V2 — Crea N ítems moto + bill via fc.agent().

    Reemplaza la cadena scrape+interact por un agente IA que resuelve cada
    paso (búsqueda por VIN, creación, bill al proveedor) en una sola sesión.
    """
    err = _validar_credenciales_alegra()
    if err:
        logger.error("crear_lote_motos_agente — credenciales: %s", err)
        return {"success": False, "error": err, "stage": "credentials"}

    if not motos:
        return {"success": False, "error": "Lote vacío.", "stage": "validation"}
    for i, m in enumerate(motos):
        if not (m.get("vin") or "").strip():
            return {"success": False, "error": f"moto[{i}] sin VIN", "stage": "validation"}
        if not (m.get("motor") or "").strip():
            return {"success": False, "error": f"moto[{i}] sin motor", "stage": "validation"}

    fc = _get_fc()
    prompt = _build_lote_motos_prompt(motos, proveedor_nit, proveedor_nombre, numero_factura, fecha)
    logger.info("crear_lote_motos_agente.start n=%d proveedor=%s factura=%s", len(motos), proveedor_nit, numero_factura)

    try:
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        raw = await loop.run_in_executor(
            None,
            lambda: fc.agent(
                urls=[f"{ALEGRA_BASE}/items", f"{ALEGRA_BASE}/bills/add"],
                prompt=prompt,
                schema=_LOTE_MOTOS_SCHEMA,
                model="spark-1-pro",
            ),
        )
    except AttributeError as ex:
        logger.exception("Firecrawl SDK no expone .agent (lote_motos)")
        return {"success": False, "error": f"SDK incompatible: {ex}", "stage": "sdk_incompatible"}
    except Exception as ex:
        logger.exception("crear_lote_motos_agente — fc.agent excepción")
        return {"success": False, "error": f"Agent error: {type(ex).__name__}: {ex}", "stage": "agent_call"}

    parsed = _coerce_agent_response(raw)
    inner  = parsed.get("data") or parsed.get("json") or parsed.get("result") or parsed
    if isinstance(inner, dict) and inner.get("items_creados") is not None:
        parsed = inner

    items_creados = parsed.get("items_creados") or []
    items_omitidos = parsed.get("items_omitidos") or []
    bill_id = (parsed.get("bill_alegra_id") or "").strip()
    bill_url = (parsed.get("bill_alegra_url") or "").strip()
    errores = parsed.get("errores") or []
    todo_ok = bool(parsed.get("todo_ok"))

    if not bill_id and bill_url:
        m = re.search(r"/(?:bill|purchases/bills?)/(\d+)", bill_url, re.IGNORECASE)
        if m:
            bill_id = m.group(1)

    # Verificación dura: success solo si tenemos al menos un item creado o todos omitidos por idempotencia,
    # Y un bill con id numérico real.
    items_ok = len(items_creados) + len(items_omitidos) >= len(motos) - len(errores)
    bill_ok  = bill_id.isdigit()

    success = todo_ok and items_ok and bill_ok and not errores

    return {
        "success":         success,
        "creadas":         len(items_creados),
        "omitidas":        len(items_omitidos),
        "errores_count":   len(errores),
        "bill_alegra_id":  bill_id if bill_ok else None,
        "bill_alegra_url": bill_url,
        "items_creados":   items_creados,
        "items_omitidos":  items_omitidos,
        "errores":         errores,
        "agent_response":  parsed,
        "stage":           "completed" if success else "verification",
    }


# ─────────────────────────────────────────────────────────────────────────────
# V2 — Repuestos: bodega + lote vía fc.agent()
# La cuenta default de la bodega "Motos" sobreescribe las cuentas del item, por
# eso los repuestos terminan en cuentas de motos. Solución: garantizar bodega
# "Repuestos" con cuentas 14350102/41350601/61350601 y crear los items ahí.
# ─────────────────────────────────────────────────────────────────────────────

_LOTE_REPUESTOS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "bodega_repuestos_existia": {"type": "boolean"},
        "bodega_repuestos_id":      {"type": "string"},
        "bodega_repuestos_creada":  {"type": "boolean"},
        "items_creados": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "referencia": {"type": "string"},
                    "alegra_id":  {"type": "string"},
                    "nombre":     {"type": "string"},
                    "cantidad":   {"type": "number"},
                },
            },
        },
        "items_omitidos": {"type": "array", "items": {"type": "object"}},
        "bill_alegra_id":  {"type": "string"},
        "bill_alegra_url": {"type": "string"},
        "errores":         {"type": "array", "items": {"type": "object"}},
        "todo_ok":         {"type": "boolean"},
    },
    "required": ["items_creados", "todo_ok"],
}


def _build_lote_repuestos_prompt(items: list[dict], proveedor_nit: str,
                                 proveedor_nombre: str, numero_factura: str,
                                 fecha: str) -> str:
    lineas = []
    for it in items:
        ref = (it.get("referencia") or it.get("reference") or "").strip()
        nombre = (it.get("nombre") or it.get("name") or "Repuesto sin nombre").strip()
        cantidad = float(it.get("cantidad") or 1)
        precio = float(it.get("precio_unit") or it.get("price") or 0)
        iva = float(it.get("iva_pct", 19))
        lineas.append(
            f"- referencia={ref!r} | nombre={nombre!r} | cantidad={cantidad} | "
            f"precio_unit_sin_iva={precio} | iva_pct={iva}"
        )
    lista_items = "\n".join(lineas) if lineas else "(lista vacía)"

    return f"""Estás autenticado en Alegra Colombia (https://app.alegra.com) con cuenta RODDOS S.A.S.
Si la sesión está cerrada, inicia sesión: email "{ALEGRA_EMAIL}" / password "{ALEGRA_UI_PASSWORD}".

CONTEXTO IMPORTANTE: En RODDOS los repuestos deben afectar EXCLUSIVAMENTE las cuentas de repuestos:
  Ingreso ventas repuestos:    41350601
  Inventario activo repuestos: 14350102
  Costo de ventas repuestos:   61350601

Si los ítems se crean en la bodega "Motos" (default), Alegra contabiliza con cuentas de motos
(14350101, 41350501, 61350501) y el balance queda mal. Por eso este flujo trabaja con una
bodega/almacén separado llamado "Repuestos".

PASO 0 — VERIFICAR/CREAR BODEGA "Repuestos":
1. Navega a https://app.alegra.com/inventory/warehouses (o /warehouses si la URL está renombrada).
2. Busca una bodega cuyo nombre sea exactamente "Repuestos" (case-insensitive).
3. Si existe: anota su id → bodega_repuestos_id, bodega_repuestos_existia=true.
4. Si NO existe: créala con nombre "Repuestos", descripción "Almacén RODDOS para repuestos
   y accesorios", configurándola como la bodega por defecto para ítems con categoría
   "Repuestos" (id 5). bodega_repuestos_creada=true.

PASO 1 — CREAR ÍTEMS REPUESTO (uno por línea de la lista):
Para cada item de la lista, en /items/add:
- Tipo: producto inventariable (isInventoriable=true)
- Categoría: "Repuestos" (id=5)
- Reference: la referencia exacta del proveedor.
- Nombre: el indicado.
- Bodega/almacén: BODEGA "Repuestos" (la del paso 0).
- Cuentas contables OBLIGATORIAS (sin estas Alegra rechaza con code 1008):
    Ingreso ventas:    5444 (NIIF 41350601)
    Inventario:        5349 (NIIF 14350102)
    Costo de ventas:   5522 (NIIF 61350601)
- Precio venta sin IVA: precio_unit indicado.
- IVA: si iva_pct=19 → tax id 4. Si 0 → sin tax.
- Costo unitario inicial: precio_unit (compras al costo).
- Cantidad inicial: 0 (la cantidad real entra con el bill del paso 2).
- IDEMPOTENCIA: antes de crear, busca por reference. Si existe, no dupliques — registra en
  items_omitidos con razon="ya_existia" y reusa su id en el bill.

PASO 2 — BILL DEL PROVEEDOR:
- Provider identification: {proveedor_nit}
- Provider nombre: {proveedor_nombre or 'Auteco S.A.S.'}
- Número factura: {numero_factura}
- Fecha: {fecha}
- Bodega destino del ingreso de inventario: BODEGA "Repuestos".
- Items del bill: uno por cada item de la lista, con cantidad y precio_unit indicados.
- Observaciones: "[AC] Compra repuestos {proveedor_nombre or proveedor_nit} — Factura {numero_factura}"
- Auteco NIT 860024781 o 901249413 = AUTORETENEDOR — NUNCA aplicar ReteFuente.

LISTA DE REPUESTOS ({len(items)} líneas):
{lista_items}

ENTREGABLE — JSON:
- bodega_repuestos_id, bodega_repuestos_existia, bodega_repuestos_creada
- items_creados: [{{referencia, alegra_id, nombre, cantidad}}]
- items_omitidos: [{{referencia, alegra_id, razon}}]
- bill_alegra_id (numérico, extraído de URL final)
- bill_alegra_url
- errores: [{{etapa, referencia?, mensaje}}]
- todo_ok=true SOLO si bodega_repuestos_id existe, todos los items quedaron, y el bill tiene id numérico.

NO inventes IDs. Si algo falla, retorna todo_ok=false con la causa concreta.
"""


async def crear_lote_repuestos_agente(
    items: list[dict],
    proveedor_nit: str,
    numero_factura: str,
    fecha: str,
    proveedor_nombre: str = "Auteco S.A.S.",
) -> dict:
    """V2 — Bodega Repuestos + N ítems repuesto + bill, todo en una sesión agent()."""
    err = _validar_credenciales_alegra()
    if err:
        logger.error("crear_lote_repuestos_agente — credenciales: %s", err)
        return {"success": False, "error": err, "stage": "credentials"}

    if not items:
        return {"success": False, "error": "Lote vacío.", "stage": "validation"}
    for i, it in enumerate(items):
        if not (it.get("referencia") or it.get("reference") or "").strip():
            return {"success": False, "error": f"item[{i}] sin referencia", "stage": "validation"}

    fc = _get_fc()
    prompt = _build_lote_repuestos_prompt(items, proveedor_nit, proveedor_nombre, numero_factura, fecha)
    logger.info("crear_lote_repuestos_agente.start n=%d proveedor=%s factura=%s",
                len(items), proveedor_nit, numero_factura)

    try:
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        raw = await loop.run_in_executor(
            None,
            lambda: fc.agent(
                urls=[
                    f"{ALEGRA_BASE}/inventory/warehouses",
                    f"{ALEGRA_BASE}/items",
                    f"{ALEGRA_BASE}/bills/add",
                ],
                prompt=prompt,
                schema=_LOTE_REPUESTOS_SCHEMA,
                model="spark-1-pro",
            ),
        )
    except AttributeError as ex:
        logger.exception("Firecrawl SDK no expone .agent (lote_repuestos)")
        return {"success": False, "error": f"SDK incompatible: {ex}", "stage": "sdk_incompatible"}
    except Exception as ex:
        logger.exception("crear_lote_repuestos_agente — fc.agent excepción")
        return {"success": False, "error": f"Agent error: {type(ex).__name__}: {ex}", "stage": "agent_call"}

    parsed = _coerce_agent_response(raw)
    inner  = parsed.get("data") or parsed.get("json") or parsed.get("result") or parsed
    if isinstance(inner, dict) and inner.get("items_creados") is not None:
        parsed = inner

    bodega_id = (parsed.get("bodega_repuestos_id") or "").strip()
    items_creados = parsed.get("items_creados") or []
    items_omitidos = parsed.get("items_omitidos") or []
    bill_id = (parsed.get("bill_alegra_id") or "").strip()
    bill_url = (parsed.get("bill_alegra_url") or "").strip()
    errores = parsed.get("errores") or []
    todo_ok = bool(parsed.get("todo_ok"))

    if not bill_id and bill_url:
        m = re.search(r"/(?:bill|purchases/bills?)/(\d+)", bill_url, re.IGNORECASE)
        if m:
            bill_id = m.group(1)

    bodega_ok = bool(bodega_id)
    bill_ok   = bill_id.isdigit()
    success = todo_ok and bodega_ok and bill_ok and not errores

    return {
        "success":                  success,
        "bodega_repuestos_id":      bodega_id or None,
        "bodega_repuestos_existia": bool(parsed.get("bodega_repuestos_existia")),
        "bodega_repuestos_creada":  bool(parsed.get("bodega_repuestos_creada")),
        "creadas":                  len(items_creados),
        "omitidas":                 len(items_omitidos),
        "errores_count":            len(errores),
        "bill_alegra_id":           bill_id if bill_ok else None,
        "bill_alegra_url":          bill_url,
        "items_creados":            items_creados,
        "items_omitidos":           items_omitidos,
        "errores":                  errores,
        "agent_response":           parsed,
        "stage":                    "completed" if success else "verification",
    }



#