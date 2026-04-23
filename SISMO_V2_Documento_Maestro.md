# SISMO V2 — Documento Maestro

## Versión 2 = Todo desde cero

SISMO V2 se construye completamente desde cero. Repo nuevo (RoddosColombia/SISMO-V2), backend nuevo, frontend nuevo, MongoDB nueva, dominios nuevos en Render y Vercel.

Lo ÚNICO que se reutiliza:
- Alegra: credenciales, datos contables existentes (journals, facturas, contactos)
- Mercately: templates de WhatsApp aprobados

Metodología: al planear cada fase de trabajo, revisar qué existe de V1 que pueda servir como referencia, pero el default es construir desde cero. NO arrastrar código de V1.

---

## ROG-4 — La regla más importante del proyecto

ALEGRA ES LA FUENTE CANÓNICA DE TODA LA INFORMACIÓN CONTABLE.

Flujo SISMO → Alegra (escritura):
El Agente Contador razona el asiento contable correcto y envía a Alegra la instrucción de causación. Alegra recibe, procesa contablemente, y retorna el ID del registro.
- POST /journals — gastos, ingresos, CXC, nómina
- POST /invoices — facturas de venta de motos con VIN
- POST /payments — pagos de cuotas de cartera

Flujo Alegra → SISMO (lectura):
Alegra entrega información construida contablemente que SISMO consume:
- GET /categories — plan de cuentas 233 NIIF
- GET /journals — journals para P&L y análisis
- GET /invoices — facturas para CFO y cartera
- GET /payments — pagos para actualizar cartera

MongoDB NO recibe información contable. MongoDB es cache operativo temporal para sesiones, jobs, estado de proceso. NUNCA es fuente de verdad contable. NUNCA reemplaza a Alegra.

---

## Roles de trabajo

Claude.ai = Arquitecto y configurador:
- Diseñar especificaciones, flujos, fases
- Escribir system prompts de agentes
- Definir y actualizar registros canónicos
- Diagnosticar bugs
- Generar prompts para Claude Code
- Auditar resultados

Claude Code = Constructor:
- Todo el código (Python, React, TypeScript)
- Commits, push, tests
- Terminal y scripts
- Interacción directa con el repo

Interfaz: Los documentos de .planning/ son el contrato entre ambos.

Regla para Claude.ai: ANTES de cualquier propuesta que implique arquitectura, datos o decisiones de diseño, buscar primero en el Project Knowledge. No confiar en memoria — confiar en documentos aprobados.

---

## Objetivo Primario: Fase 0 + Fase 1

Fase 0 — 6 cimientos arquitectónicos:
C1. Router con threshold 0.70
C2. System prompts diferenciados por agente
C3. WRITE_PERMISSIONS en código
C4. Tool Use nativo (Anthropic API)
C5. Bus de eventos funcional
C6. request_with_verify() como patrón único

Fase 1 — 9 capacidades del Agente Contador + Backlog:
C1. Egresos por chat
C2. Conciliación bancaria + movimientos individuales
C3. Nómina mensual
C4. CXC socios
C5. Facturación directa en Alegra (POST /invoices)
C6. Ingresos por cuotas (doble operación: payment + journal)
C7. Ingresos no operacionales
C8. Módulo Backlog operativo (red de seguridad)
C9. P&L automático (resultado de las 8 anteriores)

Criterio de éxito: El P&L de RODDOS en Alegra refleja la realidad sin intervención manual.
22 smoke tests deben pasar antes de declarar V2 completo.

Todo lo demás es Backlog de proyecto — se construye después progresivamente.

---

## Reglas de Oro

ROG-1: Nunca reportar éxito sin verificar HTTP 200 en Alegra. El juez es Alegra, no el agente.
ROG-2: Sin atajos. Sin deuda técnica.
ROG-3: Todo funciona desde SISMO.
ROG-4: Alegra es la fuente canónica. MongoDB NO es el ERP. MongoDB NO recibe información contable.

---

## Reglas Técnicas Inamovibles

Alegra:
- Base URL: https://api.alegra.com/api/v1/
- Journals: POST /journals — NUNCA /journal-entries (da 403)
- Plan de cuentas: GET /categories — NUNCA /accounts (da 403)
- Fechas: yyyy-MM-dd — NUNCA ISO-8601 con timezone
- Fallback cuenta: ID 5493 — NUNCA 5495

Retenciones Colombia:
- Arrendamiento: 3.5% | Servicios: 4% | Honorarios PN: 10% | Honorarios PJ: 11%
- Compras: 2.5% (base > $1.344.573) | ReteICA Bogotá: 0.414%
- IVA: cuatrimestral (ene-abr / may-ago / sep-dic) — NUNCA bimestral
- Auteco NIT 860024781: autoretenedor — NUNCA ReteFuente

Socios:
- Andrés Sanjuan CC 80075452 — gastos personales = CXC socios, NUNCA gasto operativo
- Iván Echeverri CC 80086601 — gastos personales = CXC socios, NUNCA gasto operativo

Bancos en Alegra:
- Bancolombia: 111005 | BBVA: 111010 | Davivienda: 111015
- Banco de Bogotá: 111020 | Global66: 11100507

IDs de cuentas Alegra (las más usadas):
- Sueldos: 5462 | Honorarios: 5470 | Arriendo: 5480
- Gastos Generales (fallback): 5493 | ReteFuente: 236505 | ReteICA: 236560

---

## Negocio RODDOS

- Venta de motos TVS nuevas y usadas + repuestos
- Financiación 100% propia — sin bancos, sin leasing
- Planes: P39S, P52S, P78S (semanal x1.0, quincenal x2.2, mensual x4.4)
- Cobro: SIEMPRE miércoles. Cobranza 100% remota — llamadas + WhatsApp
- Mora: $2.000 COP/día, empieza jueves
- NUNCA sugerir visitas en campo ni geolocalización

Personas clave:
- Andrés Sanjuan: CEO/cofundador, lead developer
- Iván Echeverri: CGO/cofundador
- Liz: operaciones
