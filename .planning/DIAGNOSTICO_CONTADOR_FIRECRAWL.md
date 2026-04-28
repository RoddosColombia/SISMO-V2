# DIAGNÓSTICO — Agente Contador no ejecuta tareas en Alegra vía Firecrawl

**Fecha:** 27-abril-2026
**Autor:** Revisión técnica integral
**Caso piloto solicitado:** Crear factura de venta de moto desde SISMO V2 → Alegra UI vía Firecrawl
**Veredicto:** El stack actual **no puede funcionar end-to-end** por una combinación de 4 fallos en cascada y otros 8 problemas estructurales. El más grave es invisible: la contraseña UI de Alegra está vacía y el código intenta loguear con la API key.

---

## TL;DR — Las 4 razones por las que nada llega a Alegra

| # | Capa | Problema | Severidad |
|---|------|----------|-----------|
| 1 | Configuración | `ALEGRA_PASSWORD` está vacío en `.env`. El código toma la password desde `ALEGRA_TOKEN` (que es la API key, no la contraseña UI). Firecrawl intenta loguear con un hex de API → Alegra rechaza el login → la sesión queda en pantalla de login → todos los selectores del formulario fallan. | **P0 — bloqueante** |
| 2 | Logging | El proyecto no tiene `logging.basicConfig` ni `dictConfig`. Los `logger.error(...)` en `firecrawl/alegra_browser.py` y `handlers/facturacion.py` se descartan sin handler. El traceback nunca se imprime. Por eso "falla sin lograr ver el por qué". | **P0 — invisible** |
| 3 | Flujo Firecrawl | `_start_session()` ejecuta el script de login, pero después del login no vuelve a navegar a `/income/invoices/add`. Los `interact()` siguientes corren sobre el dashboard de Alegra, no sobre el formulario. | **P0 — silencioso** |
| 4 | Heurística de éxito | El check `any(k in out.lower() for k in ["invoice","factura","view","/income/","guardado"])` da falso positivo cuando el HTML del dashboard contiene la palabra "factura" en el menú lateral. El handler reporta `success=True` aunque no se haya creado nada. | **P0 — corrupción de estado** |

Cualquiera de las 4 sola hace que la factura nunca llegue a Alegra. Las 4 juntas hacen que el agente *crea* que tuvo éxito y **publique el evento `factura.venta.creada`**, lo que dispara la cascada en MongoDB con datos fantasma.

---

## Mapa del flujo actual (cómo está hoy)

```
Usuario: "facturar Raider VIN ABC123 a Juan Pérez plan P52S..."
                  ↓
backend/routers/chat.py  POST /api/chat
                  ↓
core/router.route_with_sticky()  → agent_type='contador' (matchea 'facturar', 'raider')
                  ↓
agents/chat.process_chat()
  ├─ Carga SYSTEM_PROMPT_CONTADOR + CONTADOR_TOOLS (44 tools)
  └─ anthropic.messages.stream(...)
                  ↓
LLM emite tool_use:
  - PUEDE escoger crear_factura_venta (API REST) ❌ Alegra bloquea bots
  - PUEDE escoger crear_factura_venta_via_firecrawl ✅ camino deseado
                  ↓
ExecutionCard SSE → frontend confirma → POST /api/chat/approve-plan
                  ↓
ToolDispatcher.dispatch('crear_factura_venta_via_firecrawl', tool_input)
  └─ try / except Exception → captura solo str(e), sin traceback
                  ↓
handle_crear_factura_venta_via_firecrawl(...)        [facturacion.py:408-434]
  └─ AlegraFirecrawlClient.crear_factura_venta(datos) [alegra_browser.py:298-368]
       ├─ _start_session() → login con ALEGRA_TOKEN como password ❌
       ├─ fc.interact(scrape_id, code=playwright_f_string) ❌ corre sobre dashboard, no sobre form
       ├─ Heurística "success" sobre output ❌ falso positivo
       └─ stop_interaction()
                  ↓
publish_event("factura.venta.creada", datos) ❌ se publica aunque no hubo factura
                  ↓
event_handlers cascada: dashboard cache → Loanbook listener crea credito fantasma
```

---

## Hallazgos detallados (12 bugs ordenados por impacto)

### F-1 — `ALEGRA_PASSWORD` vacía, login con API key
**Archivo:** `backend/services/firecrawl/alegra_browser.py:11-12`, `backend/.env.example:14-15`

```python
# alegra_browser.py
ALEGRA_PASSWORD = os.getenv("ALEGRA_TOKEN", "")  # ❌ comentario engañoso
```

```bash
# .env.example
ALEGRA_TOKEN=17a8a3b7016e1c15c514   # API key (correcto para httpx Basic Auth)
ALEGRA_PASSWORD=                    # ❌ vacío
```

`ALEGRA_TOKEN` es el token de la API REST de Alegra (Basic Auth en `services/alegra/client.py:236-237`). NO es la contraseña UI. El código de Firecrawl intenta loguear en `app.alegra.com` con un hex de 20 chars → Alegra responde "credenciales inválidas" → el script de Playwright termina en pantalla de login → todos los `page.fill('input[id*="name"]', ...)` siguientes no encuentran el selector → `try/except: pass` los traga → output vacío → falso positivo en heurística.

**Fix:** leer `ALEGRA_PASSWORD` de su propia variable y validar al inicio que no esté vacía.

### F-2 — Logging silenciado a nivel global
**Archivo:** todo `backend/`

Búsqueda negativa: `logging.basicConfig`, `logging.dictConfig`, `LogConfig` no existen en el repo. El root logger de Python por defecto sólo emite WARNING+ a stderr **sin formato y a veces capturado por uvicorn**. Los `logger.info(...)` y `logger.error(...)` específicos se pierden.

Esto es la razón directa de "falla sin lograr ver el por qué". Hay 17 `logger.error(...)` y 8 `logger.info(...)` en el flujo Firecrawl que **nunca se imprimen**.

**Fix:** llamar `logging.basicConfig(level=INFO, format=...)` en el entrypoint de FastAPI (server.py / main.py) y usar `logger.exception(...)` (no `logger.error(str(ex))`) para capturar traceback.

### F-3 — Login no re-navega al formulario
**Archivo:** `backend/services/firecrawl/alegra_browser.py:54-78`

```python
async def _start_session(fc, url):
    result = fc.scrape(url, profile=...)         # 1) abre /income/invoices/add
    scrape_id = _extract_scrape_id(result)
    if "ingresar" in content.lower():            # 2) detecta login
        playwright_login = "..."                 # 3) llena email + password + submit
        _interact(fc, scrape_id, code=...)       # 4) Alegra redirige a /
    return scrape_id                             # 5) ❌ scrape_id apunta al dashboard, no al form
```

Después del login, Alegra redirige al dashboard `/`. Los `interact()` siguientes en `crear_factura_venta()` ejecutan `page.fill('input[id*="client"]', ...)` sobre el dashboard. No hay form, no hay error visible (los `try/except: pass` los tragan), termina con `print({"url": "/", "title": "Dashboard"})`.

**Fix:** después del login, hacer `page.goto(target_url)` y `wait_for_load_state('networkidle')` antes de retornar el scrape_id.

### F-4 — Heurística de éxito da falsos positivos
**Archivo:** `backend/services/firecrawl/alegra_browser.py:358, 165, 220, 284, 403, 462`

```python
ok = any(k in out.lower() for k in ["invoice","factura","view","/income/","guardado"])
```

Si `out` es el HTML/texto del dashboard de Alegra, contiene la palabra "factura" en el menú lateral. Resultado: `success=True`, `_alegra_id="firecrawl"`, evento `factura.venta.creada` publicado, listeners crean loanbook fantasma.

**Fix:** verificar que la URL final cambia a `/invoice/{id}` o `/sales/invoices/{id}` y extraer el id real del path. Si no hay id, fail.

### F-5 — La factura via Firecrawl no incluye los campos prometidos
**Archivo:** `backend/services/firecrawl/alegra_browser.py:298-368`

La tool description en `tools.py:507` dice:

> "Incluye SOAT $363.300 + Matrícula $296.700 + GPS $82.800 por defecto."

Pero el código de `crear_factura_venta` solo llena: cliente, item por VIN, observaciones. **No agrega líneas SOAT/Matrícula/GPS, no marca paymentForm CREDIT, no setea cuota_inicial, no envía a DIAN.** Si el "Guardar" funcionara, dejaría una factura *borrador* con un solo ítem y total incorrecto.

**Fix:** rediseñar el flujo Firecrawl para usar `fc.agent(prompt=...)` (ver F-12) o bien construir paso a paso todas las líneas y campos requeridos.

### F-6 — F-string injection en código Playwright
**Archivo:** `backend/services/firecrawl/alegra_browser.py:67-74, 103-161, 194-218, 254-281, 325-355, 387-401, 434-460`

```python
playwright_login = f"""
await page.fill('input[type="email"]', '{ALEGRA_EMAIL}')
await page.fill('input[type="password"]', '{ALEGRA_PASSWORD}')
"""
```

Una contraseña con apóstrofe (`p4ss'word`) o un cliente llamado `María D'Alessandro` rompe la sintaxis del Python interpolado:

```python
await page.fill('...', 'María D'Alessandro')   # ❌ SyntaxError
```

Firecrawl lo recibe como código inválido y lanza un error que termina en `_interact` → "ERROR: ..." → la heurística decide si encuentra "factura" en el string de error.

Adicional: `${cuota:,}` (línea 323) revienta si `cuota_inicial` viene `None`.

**Fix:** pasar las variables vía un dict serializado (JSON) y dentro del código Playwright leerlas con `json.loads(os.environ["DATA"])`. O usar `fc.agent()` que recibe prompt natural-language.

### F-7 — Selectores CSS demasiado laxos
**Archivo:** `backend/services/firecrawl/alegra_browser.py:110-138, 330-355, etc.`

`input[id*="name"]`, `input[placeholder*="cliente"]`, `[role="option"]` son tan amplios que pueden seleccionar la barra de búsqueda global, un campo de "buscar contacto", o el primer dropdown abierto en cualquier parte de la página. Alegra es una SPA con IDs generados; estos selectores son inestables entre releases de Alegra.

**Fix:** delegar la resolución de selectores a `fc.agent()` que usa LLM para decidir, o capturar screenshots (`fc.scrape(formats=["screenshot"])`) y validar visualmente.

### F-8 — Tool ambigua: el LLM puede usar la equivocada
**Archivo:** `backend/agents/contador/tools.py:533-570` y `502-531`

Hay DOS tools expuestas al LLM:

- `crear_factura_venta` → usa API REST (`POST /invoices`). **Alegra bloquea bots** según la decisión arquitectónica.
- `crear_factura_venta_via_firecrawl` → usa Firecrawl.

El system prompt dice "SIEMPRE usar via_firecrawl", pero el LLM puede ignorar o el roteo del intent puede empujar a la otra. Si elige la API REST → 401/403/422 → el handler ya tiene fallback a Firecrawl pero el bug F-1 hace que también falle.

**Fix:** retirar `crear_factura_venta` (API) del set de tools del Contador hasta que Firecrawl funcione. Dejar una sola tool de cara al LLM.

### F-9 — `firecrawl` sin pin de versión
**Archivo:** `backend/requirements.txt:20`

```
firecrawl
```

Sin pin. Cualquier `pip install -r requirements.txt` baja la última (hoy 4.23.0). Una nueva versión puede cambiar firmas o renombrar `interact` → `browser_execute` (la 4.23.0 ya tiene **ambas**, lo cual sugiere que Firecrawl está en transición).

**Fix:** pinear a `firecrawl==4.23.0` y validar antes de subir versión.

### F-10 — Sin tests de Firecrawl
**Archivo:** `backend/tests/`

Cero tests cubren `AlegraFirecrawlClient.crear_factura_venta`, `crear_item_moto`, `registrar_bill`, ni el handler `handle_crear_factura_venta_via_firecrawl`. El único test de tooling (`test_tool_use.py`) sólo valida que la tool aparezca en la lista, no que ejecute.

**Fix:** test con mock de `firecrawl.Firecrawl` que simule un flujo exitoso y otro fallido, y que valide que el handler captura ambos correctamente.

### F-11 — Dispatcher captura `str(e)` sin traceback
**Archivo:** `backend/agents/contador/handlers/dispatcher.py:227-230`

```python
except Exception as e:
    return {"success": False, "error": f"Error ejecutando {tool_name}: {str(e)}"}
```

Combinado con F-2, esto significa que **un `AttributeError` o `KeyError` en `alegra_browser.py` no deja rastro en logs**. Solo se ve un mensaje corto en el frontend.

**Fix:** `logger.exception(...)` antes del return + publicar evento `tool.error` en `roddos_events` con stack y tool_input para auditoría.

### F-12 — Estrategia Firecrawl subóptima para este caso
**SDK actual (4.23.0)** ofrece:

- `fc.scrape(...)` → un solo HTTP scrape, con login posible vía profile persistente.
- `fc.interact(job_id, code=..., language="python")` → ejecuta Playwright en la sesión scrapeada.
- `fc.browser(...) + fc.browser_execute(session_id, code=...)` → sesión browser explícita más larga (lo que se acerca más al caso de uso).
- **`fc.agent(prompt="Crea una factura...", urls=[...])` → agente IA propio de Firecrawl (modelo "spark-1-pro") que resuelve los selectores y completa formularios usando LLM.** Es la herramienta correcta para el caso "automatizar UI sin escribir Playwright a mano".

El código actual elige el camino más frágil: `scrape + interact` con código Playwright literal. **`fc.agent()` es 10x más robusto** para flujos de varios pasos sobre apps SPA con DOM dinámico.

**Fix:** reemplazar el cuerpo de `crear_factura_venta` por una llamada a `fc.agent()` con prompt natural y schema de respuesta.

---

## Plan de acción priorizado

### P0 — Hacer que el caso piloto funcione (1 día)

1. **`alegra_browser.py`:** leer `ALEGRA_PASSWORD` de su propio env var, validar no-vacío.
2. **`.env.example`:** documentar diferencia `ALEGRA_TOKEN` (API) vs `ALEGRA_PASSWORD` (UI).
3. **`server.py` / `main.py`:** agregar `logging.basicConfig(level=INFO, format=...)` al inicio.
4. **`alegra_browser.py`:** añadir nueva función `crear_factura_venta_v2(datos)` que use `fc.agent(prompt=..., urls=[...])` con schema. Dejar la vieja sin tocar (regla CLAUDE.md "no sobrescribir").
5. **`facturacion.py`:** agregar handler `handle_crear_factura_venta_v2` que invoque la nueva función, valide URL final, y solo publique evento si el id es real (regex `/invoice/(\d+)` o similar).
6. **`tools.py`:** registrar nueva tool `crear_factura_venta_alegra_agente` y **retirar `crear_factura_venta` (API REST) de la lista visible al LLM** mientras Alegra siga bloqueando bots.
7. **`prompts.py`:** simplificar el system prompt — sólo mencionar la tool nueva.
8. **`dispatcher.py`:** agregar `logger.exception(...)` en el catch genérico y publicar `tool.error` en `roddos_events`.
9. **`requirements.txt`:** pinear `firecrawl==4.23.0`.

### P1 — Cerrar la brecha de visibilidad (½ día)

10. Test `tests/test_facturacion_firecrawl.py` con mock del SDK.
11. Endpoint `GET /api/health/firecrawl` que ejecute un `fc.scrape(app.alegra.com)` y reporte si la sesión está logeada.
12. Migrar handlers `crear_item_moto`, `registrar_bill`, `registrar_pago`, `registrar_journal` a `fc.agent()` (mismo patrón).

### P2 — Calidad estructural (1-2 días)

13. Retirar f-string injection: pasar payload como variable de entorno en el código Playwright.
14. Agregar `event handlers` sólo después de validar éxito real (no por heurística).
15. Documentar en `.planning/` el contrato de Firecrawl + ejemplo de respuesta esperada.

---

## Criterios de aceptación del fix P0

Para considerar resuelto el caso piloto "Crear factura de venta":

1. Desde el chat de SISMO V2, el operador escribe:
   `facturar Raider 125 VIN MD2A4CY3XRW123456 motor CY3RW123456 a Juan Pérez CC 1234567 plan P52S semanal cuota inicial 500.000`

2. El frontend muestra ExecutionCard con `tool=crear_factura_venta_alegra_agente`. Al aprobar:

3. En logs del backend (visibles, no silenciados) aparece:
   ```
   firecrawl.alegra | INFO | agent.start prompt="Crear factura venta..." urls=[...]
   firecrawl.alegra | INFO | agent.completed status=completed factura_id=12345 url=https://app.alegra.com/invoice/12345
   handlers.facturacion | INFO | factura.venta.creada published alegra_id=12345
   ```

4. En Alegra (verificación manual), aparece la factura con:
   - Cliente Juan Pérez CC 1234567
   - Línea 1: TVS Raider 125 - VIN MD2A4CY3XRW123456 - Motor CY3RW123456
   - Línea 2: SOAT $363.300
   - Línea 3: Matrícula $296.700
   - Línea 4: GPS $82.800
   - Forma de pago: CRÉDITO
   - Status: open / por DIAN

5. En MongoDB: doc en `roddos_events` con `event_type="factura.venta.creada"` y `alegra_id="12345"` (no `"firecrawl"`).

6. Si Firecrawl falla, el log muestra traceback completo y el frontend recibe el motivo concreto (`"Login a Alegra rechazado: contraseña UI no configurada"`, `"Selector cliente no encontrado en formulario invoice/add"`, etc.).

---

## Riesgos del fix

- `fc.agent()` consume créditos Firecrawl proporcionales a la complejidad del prompt y al tiempo en sesión. Recomendable monitorear `get_credit_usage()`.
- El agente IA de Firecrawl puede equivocarse de cliente si hay homónimos. Mitigación: pasarle la cédula explícitamente y pedir validación con el `identification` field.
- Si Alegra cambia el HTML, el agente puede tardar más o fallar. Mitigación: pasarle screenshots como contexto cuando esté disponible.

---

## Apéndice A — Comandos de verificación

```powershell
# Local Windows
cd C:\Users\AndresSanJuan\roddos-workspace\SISMO-V2\backend
python -m pytest tests/test_facturacion_firecrawl.py -v
python -c "from services.firecrawl.alegra_browser import get_alegra_browser; import asyncio; print(asyncio.run(get_alegra_browser().healthcheck()))"
```

```bash
# Render shell
cd /opt/render/project/src
python3 -c "import firecrawl; print(firecrawl.__version__)"   # debe ser 4.23.0
python3 scripts/firecrawl_smoke_test.py                       # smoke test
```

## Apéndice B — Confirmación SDK Firecrawl 4.23.0

Métodos verificados en instancia de `firecrawl.Firecrawl(api_key=...)`:
- `scrape(url, *, formats, profile, ...)` → `Document`
- `interact(job_id, code=None, *, prompt=None, language='node'|'python'|'bash')`
- `browser(*, ttl, profile, ...)` → `BrowserCreateResponse`
- `browser_execute(session_id, code, *, language)`
- `agent(urls=None, *, prompt, schema=None, model='spark-1-pro')` → respuesta agente
- `start_agent(...)` y `get_agent_status(...)` para polling
- `stop_interaction(job_id)`

`Document.metadata.scrape_id` (snake_case) confirmado en `firecrawl.v2.types.DocumentMetadata`. El extractor actual `_extract_scrape_id` está OK.
