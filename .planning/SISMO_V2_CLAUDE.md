# SISMO V2 — Contexto Maestro para Claude Code

## Identidad del Proyecto
- Nombre: SISMO — Sistema Inteligente de Soporte y Monitoreo Operativo
- Empresa: RODDOS S.A.S. — Calle 127 con Autopista Norte, Bogotá D.C.
- Repo: github.com/RoddosColombia/SISMO (público)
- Stack: FastAPI Python 3.11 + React 19 + MongoDB Atlas (async Motor) + Claude via Anthropic SDK + Alegra API + Mercately WhatsApp
- Deploy: Render (backend) + Vercel (frontend) + Atlas M0
- Backend URL: sismo-backend-40ca.onrender.com
- Frontend URL: sismo-bice.vercel.app
- Git config: user.name="RODDOS SAS"

## Estado Actual
- BUILD actual: FASE 8-A completada (ab7d4aa) — 10/10 tests GREEN
- HOTFIX plan_id→ExecutionCard completado (4f417ea)
- Modelo LLM: claude-opus-4-6 en Claude.ai / Claude Sonnet via Anthropic SDK en SISMO
- Colecciones MongoDB: 34 | Índices: 64 | Tests: 67
- Agente Contador: ~4.8/10 → objetivo 9.0/10 con SISMO V2

## OBJETIVO PRIMARIO: Fase 0 + Fase 1
- Fase 0: 6 cimientos arquitectónicos (router, identidad, permisos, tool use, bus, verificación)
- Fase 1: 9 capacidades del Agente Contador + módulo Backlog operativo
- Criterio de éxito: El P&L de RODDOS en Alegra refleja la realidad sin intervención manual
- Especificación completa: .planning/SISMO_V2_Fase0_Fase1.md
- Todo lo demás es Backlog de proyecto

## Reglas de Oro — NUNCA violar

ROG-1: Nunca reportar éxito sin verificar HTTP 200 en Alegra. request_with_verify() siempre. El juez es Alegra, no el agente.

ROG-2: Sin atajos. Cada build deja el sistema mejor. Sin deuda técnica.

ROG-3: Todo funciona desde SISMO. PowerShell solo para lo estrictamente necesario.

## Reglas Técnicas Permanentes

ALEGRA:
- Base URL: https://api.alegra.com/api/v1/
- Auth: Basic Base64(contabilidad@roddos.com:token)
- Journals: POST /journals — NUNCA /journal-entries (da 403)
- Plan de cuentas: GET /categories — NUNCA /accounts (da 403)
- Fechas: yyyy-MM-dd — NUNCA ISO-8601 con timezone
- Fallback cuenta: ID 5493 (Gastos Generales) — NUNCA 5495 (causó 143 asientos incorrectos)

MONGODB:
- DB_NAME siempre viene de variable de entorno. Nunca hardcodear 'sismo' o 'sismo-prod'
- Patrón canónico: client = AsyncIOMotorClient(os.environ['MONGO_URL']); db = client[os.environ['DB_NAME']]
- Leer database.py antes de cualquier script en Render
- sismo_knowledge es la colección del Knowledge Base Service (no sismo_knowledge_base)

DESARROLLO:
- Worktrees GSD: discuss+plan only — siempre ejecutar directo en main
- Cualquier archivo generado en Claude.ai debe commitearse en Claude Code antes de referenciarlo
- BackgroundTasks + job_id obligatorio para lotes > 10 registros
- Anti-duplicados 3 capas: hash extracto + hash movimiento + GET Alegra

## Retenciones Colombia 2026
- Arrendamiento: ReteFuente 3.5%
- Servicios: ReteFuente 4%
- Honorarios PN: ReteFuente 10%
- Honorarios PJ: ReteFuente 11%
- Compras: ReteFuente 2.5% (base > $1.344.573)
- ReteICA Bogotá: 0.414%
- IVA: cuatrimestral (ene-abr / may-ago / sep-dic) — NUNCA bimestral
- Auteco NIT 860024781: autoretenedor → NUNCA ReteFuente

## IDs de Cuentas Alegra (plan_cuentas_roddos)
- Sueldos: 5462 | Honorarios: 5470 | Seguridad social: 5471
- Arrendamientos: 5480 | Servicios públicos: 5484 | Teléfono: 5487
- Mantenimiento: 5490 | Transporte: 5491 | Gastos Generales (fallback): 5493
- Papelería: 5497 | Publicidad: 5500 | Comisiones bancarias: 5508
- Seguros: 5510 | Intereses: 5533
- ReteFuente practicada: 236505 | ReteICA practicada: 236560

## Bancos en Alegra
- Bancolombia: 111005 | BBVA: 111010 | Davivienda: 111015
- Banco de Bogotá: 111020 | Global66: 11100507

## Socios RODDOS
- Andrés Sanjuan: CC 80075452 — gastos personales = CXC socios, NUNCA gasto operativo
- Iván Echeverri: CC 80086601 — gastos personales = CXC socios, NUNCA gasto operativo

## Personas Clave
- Andrés: CEO/cofundador, lead developer, CC 80075452
- Iván Echeverri: CGO/cofundador, CC 80086601
- Liz: operaciones, concilia backlog de movimientos via modal Causar

## Planes de Crédito (desde catalogo_planes en MongoDB)
- Cuota multiplicadores: Semanal ×1.0 (base), Quincenal ×2.2, Mensual ×4.4
- Mora: $2.000 COP/día, empieza jueves (día después del miércoles de vencimiento)

## Formatos de Extracto Bancario (siempre .xlsx, NUNCA CSV)
- Bancolombia: sheet "Extracto", headers row 15, cols FECHA (d/m) / DESCRIPCIÓN / VALOR
- BBVA: headers row 14, cols "FECHA DE OPERACIÓN" (DD-MM-YYYY) / "CONCEPTO" / "IMPORTE (COP)"
- Davivienda: skiprows=4, cols Fecha / Descripción / Valor / Naturaleza (C=ingreso, D=egreso)
- Global66: en Banco enum — parser NO implementado aún
- Banco de Bogotá: parser NO implementado

## Arquitectura de Agentes
- Nivel 1 (Operativo): Agente Contador — el ÚNICO que escribe en Alegra
- Nivel 2 (Coordinador): RADAR (cobranza) + Agente Loanbook (ciclo crédito)
- Nivel 3 (Estratégico): CFO — solo lectura, autoridad de veto
- Comunicación: SOLO via bus de eventos roddos_events — ningún agente llama a otro directamente
- Permisos: WRITE_PERMISSIONS en código, no solo en prompt

## WRITE_PERMISSIONS (verificar en código antes de cada escritura)
- Contador: cartera_pagos, cxc_socios, cxc_clientes, plan_cuentas_roddos, inventario_motos + POST /journals, /invoices, /payments
- CFO: cfo_informes, cfo_alertas (solo sus propias) + Solo GET en Alegra
- RADAR: crm_clientes, gestiones_cobranza + Ningún endpoint Alegra
- Loanbook: inventario_motos, loanbook + Ningún endpoint Alegra
- Todos: roddos_events (append-only)

## Bugs Conocidos Activos
- pago_pse_nequi en accounting_engine.py: falta cuenta_debito → cae a CXC Socios (5329) en vez de Gastos Generales (5493)
- 298 movimientos pendientes en Backlog: BBVA 33, Bancolombia 188, Nequi 76, Davivienda 0

## PowerShell Gotchas (Windows)
- Heredoc (<< 'EOF') NO funciona — escribir archivo .py primero
- head no disponible — usar Select-String -Pattern
- Comandos largos (>~200 chars) fallan por clipboard — push script a GitHub
- Set env vars: $env:MONGO_URL y $env:DB_NAME antes de scripts
- Git operations desde C:\Users\AndresSanJuan\roddos-workspace\SISMO\
