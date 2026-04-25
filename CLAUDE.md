# CLAUDE.md — Instrucciones canónicas para Claude Code en SISMO-V2

## Entorno local (Windows)

- **Shell:** PowerShell
- **Python:** usar `python` (no `python3` ni `py`)
- **Tests:** `python -m pytest` (pytest no está en PATH directo)
- **Directorio raíz:** `C:\Users\AndresSanJuan\roddos-workspace\SISMO-V2`
- **Backend:** `C:\Users\AndresSanJuan\roddos-workspace\SISMO-V2\backend`

## Comandos canónicos

Correr todos los tests:
```
cd backend
python -m pytest tests/ -v
```

Correr un test específico:
```
cd backend
python -m pytest tests/test_nombre.py -v
```

Instalar dependencias:
```
cd backend
pip install -r requirements.txt
```

## Entorno de producción (Render)

- **Servicio:** SISMO-V2 (`srv-d7dr9khkh4rs739vti0g`)
- **Shell:** Render Web Shell en dashboard.render.com
- **Python en Render:** `python3`
- **Directorio en Render:** `/opt/render/project/src`
- **Variables `MONGO_URL` y `DB_NAME`** solo existen en Render, no en `.env` local

Correr scripts en Render Shell:
```
cd /opt/render/project/src
python3 scripts/nombre_script.py
```

## Reglas de trabajo inamovibles

- **Una tarea a la vez** — ejecutar, mostrar resultado, esperar OK antes de la siguiente
- Antes de cualquier propuesta leer `SISMO_V2_Registro_Canonico.md` y `reglas_negocio.py`
- **NO sobrescribir funciones existentes** — solo agregar al final
- **NUNCA usar `date.today()` ni `datetime.utcnow()`** — usar `today_bogota()` o `now_bogota()` de `core/datetime_utils.py`
- Antes de merge a main correr `/ultrareview`

## Cálculos financieros — regla de oro

Todos los cálculos de `saldo_capital` y `saldo_intereses` deben usar **ÚNICAMENTE** la función `calcular_saldos()` de `backend/services/loanbook/reglas_negocio.py`. Nunca calcular estos valores inline en routers ni en otros servicios.

`capital_plan` por moto (precio venta base sin extras ni IVA):

| Modelo | capital_plan |
|--------|-------------|
| Raider 125 | 7_800_000 |
| TVS Sport 100 | 5_750_000 |
| RODANTE | monto_original del producto |

## Fechas de cobro — regla de oro

La primera cuota siempre se calcula con `primer_miercoles_cobro()` de `backend/services/loanbook/reglas_negocio.py`. Nunca calcular fechas de cuota inline.

## Estructura del proyecto

```
SISMO-V2/
├── backend/
│   ├── core/
│   │   ├── datetime_utils.py     <- ÚNICA fuente de fecha/hora Bogotá
│   │   └── database.py
│   ├── routers/
│   │   └── loanbook.py
│   ├── services/
│   │   └── loanbook/
│   │       ├── reglas_negocio.py <- ÚNICA fuente de cálculos financieros
│   │       └── state_calculator.py
│   ├── scripts/                  <- scripts one-shot, no usar en runtime
│   └── tests/
├── frontend/
├── .planning/
│   ├── SISMO_V2_Registro_Canonico.md  <- leer ANTES de cualquier cambio
│   └── LOANBOOK_MAESTRO_v1.1.md
└── CLAUDE.md                     <- este archivo
```

## RADAR — Alertas de cobranza WhatsApp

- **Proveedor:** Mercately (`services/mercately/client.py`)
- **Scheduler:** miércoles 08:00 AM `America/Bogota` — ley colombiana Ley 2300/2023
- **Templates Mercately:**
  - `MERCATELY_TEMPLATE_COBRO_ID`: 3 params — `[nombre_corto, monto_formato, fecha_ddmmm]`
  - `MERCATELY_TEMPLATE_MORA_ID`: 3 params — `[nombre_corto, dpd_str, mora_cop_formato]`
- **dry_run=True** para testing/preview sin enviar mensajes reales
- **Colección audit:** `radar_alertas` — un doc por envío con estado (enviado/error/skip_*)
- **Endpoints:** `GET /api/radar/preview` (dry run) + `POST /api/radar/enviar` (real)
- **Módulo:** `agents/radar/alertas.py` → función `enviar_alertas_cobro(db, dry_run)`

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health
