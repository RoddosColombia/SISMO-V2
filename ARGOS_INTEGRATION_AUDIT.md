# ARGOS Integration Audit — SISMO V2
**Fecha:** 2026-04-21  
**Auditor:** Claude Code (solo diagnóstico — sin modificaciones de código)  
**Propósito:** Determinar qué existe, qué no existe y qué esfuerzo requiere cada uno de los 4 endpoints que ARGOS necesita consumir de SISMO V2.

---

## Resumen Ejecutivo

| Endpoint | Estado | Esfuerzo estimado |
|---|---|---|
| `GET /api/inventory/repuestos` | Existe parcialmente (ruta diferente, schema incompleto, **actualmente retorna vacío**) | 4-6h básico · +5-10d si se implementan `dias_inventario` y `compatible_motos` |
| `GET /api/inventory/motos` | Existe parcialmente (ruta diferente, schema diferente, faltan cuotas por plazo) | 4-6h para adaptar · conversión semanas→meses requiere decisión de diseño |
| `GET /api/sales/daily` | **NO EXISTE** | 8-12h para construir desde cero |
| `GET /api/loanbook/snapshot` | **NO EXISTE** · campos de scoring histórico NUNCA CAPTURADOS | 4-6h para snapshot básico · campos de ML = MESES o imposibles retroactivamente |

---

## Endpoint 1 — GET /api/inventory/repuestos

### A) Estado actual

**Existe parcialmente** bajo ruta diferente.

- **Ruta real en SISMO:** `GET /api/inventario/repuestos` (prefijo `inventario`, no `inventory`)
- **Response wrapper actual:** `{"success": true, "data": [...], "count": N}`
- **ALERTA CRÍTICA:** El endpoint retorna lista vacía actualmente. Comentario literal en `backend/services/alegra_items.py` línea 57:
  > *"Currently Alegra has no repuestos — returns empty until they're added."*
  
  Roddos aún no tiene repuestos cargados en Alegra. El endpoint existe pero no tiene datos.

**Campos que ARGOS espera vs lo que SISMO retorna:**

| Campo ARGOS | Campo SISMO | ¿Existe? |
|---|---|---|
| `sku` | `codigo` (= Alegra `reference`) | ⚠️ Sí, pero nombre diferente |
| `nombre` | `nombre` | ✅ |
| `categoria` (jerárquico `repuestos.frenos.pastillas`) | `categoria` (nombre plano de Alegra, ej: "Repuestos") | ⚠️ Existe pero NO es jerárquico |
| `stock` (int) | `stock_actual` (int) | ⚠️ Mismo dato, nombre diferente |
| `costo` (float) | NO retornado (existe en Alegra como `inventory.unitCost`) | ⚠️ Disponible pero no expuesto |
| `precio` (float) | `precio` | ✅ |
| `dias_inventario` (int) | **NO EXISTE** | ❌ Requiere implementación |
| `compatible_motos` (array) | **NO EXISTE** | ❌ Requiere implementación |
| Paginación `page/limit` | **NO implementada** | ❌ Sin paginación |
| Filtro `categoria=` | **NO implementado** | ❌ |
| Filtro `compatible_moto=` | **NO implementado** | ❌ |
| Filtro `en_stock=true` | **NO implementado** | ❌ |

### B) Data subyacente

**Colección/fuente:** Alegra Items API (`GET /items`). No hay colección MongoDB para repuestos.

Campos de Alegra disponibles para construir la respuesta:
- `reference` → `sku` ✅
- `name` → `nombre` ✅
- `inventory.availableQuantity` → `stock` ✅
- `inventory.unitCost` → `costo` ✅ (disponible, no expuesto actualmente)
- `price[0].price` → `precio` ✅
- `itemCategory.name` → `categoria` (plana, no jerárquica) ⚠️

Campos que Alegra NO tiene:
- **`dias_inventario`:** Requeriría trackear la fecha en que cada repuesto entró al stock. Alegra no guarda eso en un campo consultable directamente. Necesitaría un campo en MongoDB o una colección de "movimientos de inventario".
- **`compatible_motos`:** Alegra no tiene un campo de compatibilidad. Requiere un mapping manual (MongoDB) que hoy no existe.

### C) Esfuerzo estimado

| Alcance | Esfuerzo |
|---|---|
| Adaptar ruta + schema (renombrar campos, agregar `costo`) | 2h |
| Agregar filtros por categoría, en_stock y paginación | 2-4h |
| Implementar `dias_inventario` | 3-5 días (diseño + tracking desde cero) |
| Implementar `compatible_motos` | 1-2 días (definir donde se almacena + API para mantenerlo) |
| **Total mínimo viable (sin los dos últimos)** | **4-6h** |

### D) Dependencias y bloqueos

1. **Repuestos no existen en Alegra** — antes de construir el endpoint, Roddos necesita cargar el catálogo de repuestos en Alegra. Sin datos, el endpoint retorna vacío indefinidamente.
2. `compatible_motos` requiere decidir el modelo de datos: ¿campo custom en Alegra? ¿Colección MongoDB `repuesto_compatibilidades`? Sin esa decisión, el campo no puede implementarse.
3. `dias_inventario` requiere definir qué se mide: ¿días desde que entró al stock? ¿días de rotación promedio? La definición afecta la implementación.

---

## Endpoint 2 — GET /api/inventory/motos

### A) Estado actual

**Existe parcialmente** bajo ruta diferente con schema diferente.

- **Ruta real en SISMO:** `GET /api/inventario/motos`
- **Response wrapper actual:** `{"success": true, "data": [...], "count": N}`
- El endpoint **sí tiene datos reales** (26 loanbooks activos, motos físicamente registradas).

**Campos que ARGOS espera vs lo que SISMO retorna:**

| Campo ARGOS | Campo SISMO | ¿Existe? |
|---|---|---|
| `modelo` (str) | `nombre` (= nombre del item en Alegra) | ⚠️ Mismo dato, nombre diferente |
| `marca` (str) | **NO como campo separado** | ⚠️ Parseable del nombre (ej: "TVS Raider 125" → "TVS") |
| `anio` (int) | **NO como campo separado** | ⚠️ Parseable del nombre en algunos casos |
| `color` (str) | `color` (solo en motos con VIN registrado) | ⚠️ Parcial — motos sin VIN no tienen color |
| `stock` (int) | `stock` | ✅ |
| `pvp` (float) | `precio` | ✅ |
| `cuotas.9` (cuota semanal a 9 meses) | **NO EXISTE como campo** | ⚠️ Calculable (ver nota abajo) |
| `cuotas.12` (cuota semanal a 12 meses) | **NO EXISTE como campo** | ⚠️ Calculable |
| `cuotas.18` (cuota semanal a 18 meses) | **NO EXISTE como campo** | ⚠️ Calculable |
| `total` (int) | `count` | ⚠️ Mismo dato, nombre diferente |

**ALERTA DE DISEÑO — Semanas vs Meses:**

SISMO maneja los planes de crédito en **semanas**, no en meses. El catálogo de planes (`catalogo_planes` en MongoDB) tiene:

| Plan | Semanas | Equivalente aproximado | Cuota semanal Raider 125 |
|---|---|---|---|
| P39S | 39 semanas | ~9 meses | $210,000/sem |
| P52S | 52 semanas | ~12 meses | $179,900/sem |
| P78S | 78 semanas | ~18 meses | $149,900/sem |

El mapeo `{9: 210000, 12: 179900, 18: 149900}` es calculable leyendo `catalogo_planes` y el modelo de la moto. Pero la conversión semanas→meses es aproximada (39 sem ≠ exactamente 9 meses calendario).

**ALERTA DE DISEÑO — Mezcla de granularidad:**

El endpoint actual mezcla dos fuentes:
1. Motos con VIN registrado individualmente en MongoDB (`inventario_motos`)
2. Stock de Alegra SKU para motos sin VIN

ARGOS aparentemente quiere una vista agregada por modelo (1 item por modelo), no por VIN individual. El endpoint actual retorna múltiples filas para el mismo modelo.

### B) Data subyacente

**Fuentes:**
- Alegra Items (`items` con `itemCategory.id` en {1, 2} = motos nuevas/usadas)
- MongoDB `inventario_motos` (VINs registrados individualmente)
- MongoDB `catalogo_planes` (cuotas por plan y modelo)

**Campos calculables:**
- `marca`: parseable con regex del `nombre` Alegra (ej: `"TVS Raider 125"` → `"TVS"`)
- `anio`: NO siempre está en el nombre — TVS Raider 125 no tiene año en el nombre
- `cuotas.{9|12|18}`: cruzando `catalogo_planes` con el modelo de la moto

### C) Esfuerzo estimado

| Alcance | Esfuerzo |
|---|---|
| Adaptar ruta + schema (renombrar campos, agregar `marca` parseable) | 2-3h |
| Agregar `cuotas.{9|12|18}` cruzando con catalogo_planes | 2-3h |
| Resolver `anio` (parseo o campo manual) | 1h + decisión |
| **Total** | **4-6h** |

### D) Dependencias

1. **Definir exactamente qué quiere ARGOS:** ¿Un item por modelo (agregado) o un item por VIN? El endpoint actual mezcla ambos.
2. **Confirmar el mapeo semanas→meses** con el equipo — P39S = 9 meses es una aproximación.
3. **`anio`** no es consistentemente parseable del nombre del modelo en Alegra. Si ARGOS lo necesita exacto, Roddos debe agregar el año a los items de Alegra o a una colección en MongoDB.

---

## Endpoint 3 — GET /api/sales/daily

### A) Estado actual

**NO EXISTE.** No hay ningún endpoint de ventas diarias en SISMO V2.

El endpoint más cercano es `GET /api/dashboard/stats` que retorna ventas **mensuales** (no diarias) y no tiene el schema que ARGOS necesita.

### B) Data subyacente

**¿Dónde viven las ventas?**

**Ventas de motos:**
- En Alegra como `invoices` — el `dashboard.py` ya las consulta con `GET /invoices`
- En `roddos_events` (MongoDB) con `event_type = "factura.venta.creada"` — contiene `vin`, `cliente_nombre`, `cliente_cedula`, `valor_factura`, `plan_codigo`
- En MongoDB `loanbook` collection (créditos creados a partir de ventas)

**Ventas de repuestos:**
- En Alegra como `invoices` (si existen) — pero actualmente SISMO no trackea ventas de repuestos por separado
- **ALERTA:** Dado que los repuestos no están en Alegra todavía (ver Endpoint 1), `ventas_repuestos` estaría vacío

**Campos del schema de ARGOS:**

| Campo | Disponible en SISMO | Fuente |
|---|---|---|
| `date` | ✅ | Query param, Alegra invoice date |
| `total_amount` | ✅ calculable | Suma de invoices del día |
| `ventas_motos.modelo` | ✅ | Alegra invoice items |
| `ventas_motos.customer_id` | ✅ | `cliente.cedula` en loanbook / Alegra contact |
| `ventas_motos.monto` | ✅ | Alegra invoice `total` |
| `ventas_motos.financiado` | ⚠️ calculable | `true` si existe loanbook para ese VIN; `false` si fue contado |
| `ventas_repuestos.sku` | ⚠️ Parcial | Alegra invoice line items |
| `ventas_repuestos.customer_id` | ⚠️ Parcial | Puede ser anónimo en ventas de mostrador |
| `ventas_repuestos.monto` | ✅ | Alegra invoice line item amount |
| `ventas_repuestos.cantidad` | ✅ | Alegra invoice line item quantity |
| `ventas_repuestos.financiado` | ✅ (`false` siempre) | Repuestos no se financian |

**ALERTA CONOCIDA — Filtro de fechas en Alegra:**

El `dashboard.py` tiene código de debug activo precisamente porque Alegra puede ignorar los parámetros `start-date`/`end-date` silenciosamente (comentario en línea 68-69):
> *"Alegra ignora silenciosamente start-date/end-date en algunos planes."*

Esto significa que filtrar invoices por fecha exacta requiere validación adicional en Python-side, con riesgo de over-fetch si Alegra retorna muchos registros.

### C) Esfuerzo estimado

| Componente | Esfuerzo |
|---|---|
| Endpoint base + query param `?date=` | 1h |
| Consultar Alegra invoices por fecha + clasificar motos vs repuestos | 3-4h |
| Determinar `financiado` cruzando con loanbook | 2h |
| Parsear `customer_id` de invoices | 1h |
| Tests + manejo de edge cases (Alegra ignora fechas, sin ventas del día) | 2h |
| **Total** | **8-12h** |

### D) Dependencias y bloqueos

1. **Problema del filtro de fechas en Alegra:** debe resolverse primero (hay debug code activo en dashboard.py). Sin saber qué campo de fecha usa Alegra y si el filtro funciona, el endpoint no puede ser confiable.
2. **Repuestos no existen en Alegra** — `ventas_repuestos` estará vacío hasta que se carguen.
3. **Ventas de mostrador anónimas:** si Roddos vende repuestos sin registrar cliente, `customer_id` no está disponible. ARGOS debe estar preparado para recibir `null` en ese campo.
4. **Latencia:** consultar Alegra en tiempo real para cada request puede ser lento. Se puede mitigar con un job diario que precalcule y cachee en MongoDB.

---

## Endpoint 4 — GET /api/loanbook/snapshot

### A) Estado actual

**NO EXISTE** como endpoint de snapshot.

Endpoints de loanbook actuales en SISMO:
- `GET /api/loanbook` — lista paginada, schema diferente, sin campos de scoring
- `GET /api/loanbook/{id}` — detalle individual
- `GET /api/loanbook/stats` — agregados del portfolio (sin detalle por crédito)

Ninguno retorna el schema que ARGOS necesita.

### B) Data subyacente — análisis campo por campo

**Colección MongoDB:** `loanbook`

| Campo ARGOS | Campo en SISMO | ¿Existe? | Notas |
|---|---|---|---|
| `customer_id` | `cliente.cedula` | ✅ | Nombre diferente |
| `credito_id` | `loanbook_id` | ✅ | Formato "LB-2026-0001" |
| `producto` (`rdx_leasing \| rodante`) | `tipo_producto` ("moto", "comparendo", "licencia") | ⚠️ | **Terminología diferente** — requiere mapping |
| `fecha_originacion` | `fechas.factura` o `created_at` | ✅ | Disponible |
| `monto_original` | `valor_total` = `num_cuotas × cuota_monto` | ✅ | Calculable |
| `plazo_meses` | **NO guardado directamente** | ⚠️ | Derivable de `num_cuotas` + `modalidad` (semanal: ÷4.33) |
| `cuotas_totales` | `num_cuotas` / `cuotas_total` | ✅ | |
| `cuotas_pagadas` | `cuotas_pagadas` | ✅ | |
| `cuotas_en_mora` | **NO guardado** | ⚠️ | Calculable en tiempo real contando cuotas vencidas no pagadas |
| `dpd_actual` | **NO guardado** | ⚠️ | Calculable vía `calcular_dpd()` en `loanbook_model.py` |
| `dpd_maximo_historico` | **NO EXISTE** | ❌ | **NUNCA TRACKEADO** — requiere campo nuevo + lógica en waterfall |
| `ptp_cumplido_ratio` | **NO EXISTE** | ❌ | **SISMO no tiene módulo PTP** |
| `no_contesto_ratio` | **NO EXISTE** | ❌ | **SISMO no tiene módulo de gestión de cobro** |
| `score_comportamental` | **NO EXISTE en loanbook V2** | ❌ | Solo en `loanbook_legacy` (cartera importada) con `score_total` histórico |
| `default_90d` (variable objetivo XGBoost) | **NO EXISTE** | ❌ | **NUNCA TRACKEADO** |
| `bucket_actual` | `estado` ("activo", "mora", "mora_grave") | ⚠️ | Taxonomía diferente pero mapeabile |
| `score_externo_originacion` | **NO EXISTE** | ❌ | **SISMO no integra con burós de crédito** |
| `capacidad_pago_originacion` | **NO EXISTE** | ❌ | **No hay intake form estructurado en originación** |
| `estabilidad_laboral_originacion` | **NO EXISTE** | ❌ | **No registrado** |
| `validacion_biometrica_originacion` | **NO EXISTE** | ❌ | **No implementado** |

**Resumen: 8 de 19 campos existen (algunos con nombre diferente). 7 campos no existen y nunca han sido capturados.**

### C) Esfuerzo estimado

| Alcance | Esfuerzo |
|---|---|
| Snapshot básico con campos existentes | 4-6h |
| Agregar `dpd_maximo_historico` (campo nuevo + actualización en cada pago) | 2-3 días |
| Módulo PTP + `ptp_cumplido_ratio` | 3-4 semanas (requiere UI de gestión de cobro) |
| Módulo gestión de cobro + `no_contesto_ratio` | 3-4 semanas |
| Integración buró de crédito + `score_externo_originacion` | 2-3 meses |
| **`capacidad_pago`, `estabilidad_laboral`, `validacion_biometrica`** | **Retroactivamente imposible para créditos existentes** |

### D) Dependencias y bloqueos críticos

1. **Datos de originación son retroactivamente imposibles de recuperar.** Los créditos activos (26 en cartera) fueron originados sin capturar `score_externo`, `capacidad_pago`, `estabilidad_laboral`, ni `validacion_biometrica`. Esos datos no existen y no pueden reconstruirse. El modelo XGBoost de ARGOS tendrá estos campos como `null` para toda la cartera histórica.

2. **`ptp_cumplido_ratio` y `no_contesto_ratio` requieren un módulo de gestión de cobros** (registrar llamadas de cobro, promesas de pago, resultados). Esto es Phase 8 en SISMO, actualmente bloqueada (DT-8 en deuda técnica). Sin ese módulo, los ratios son incalculables.

3. **`dpd_maximo_historico` requiere empezar a trackearlo hoy.** Si se agrega el campo ahora y se actualiza en cada pago vía `waterfall`, se tendrá data útil en 2-3 meses. Los créditos existentes arrancarían con `null`.

4. **`default_90d` (variable objetivo del XGBoost)** — para que el modelo entrene necesita créditos que hayan llegado a 90+ DPD Y se hayan recuperado O no. Con 26 créditos activos y DPD máximo actual probablemente bajo, el dataset de entrenamiento es muy pequeño. ARGOS debe considerar si el modelo puede entrenarse con `loanbook_legacy` (cartera importada de aliados).

5. **Terminología `rdx_leasing | rodante`:** SISMO usa `tipo_producto: "moto"` para todo. ¿A qué corresponde `rdx_leasing` y `rodante` en la terminología de Roddos? Necesita clarificación antes de implementar el mapping.

---

## Observaciones de Diseño para ARGOS

Estos puntos no tienen solución clara — se registran para que el equipo los resuelva antes del desarrollo.

### OD-1: Plazos en semanas vs meses
SISMO mide plazos en semanas (`num_cuotas` para plan semanal). ARGOS pide `plazo_meses`. El mapeo aproximado:
- P39S (39 sem) ≈ 9 meses → error de hasta 3.5 semanas vs calendario exacto
- P52S (52 sem) ≈ 12 meses → error de hasta 4.3 semanas
- P78S (78 sem) ≈ 18 meses → error de hasta 4.3 semanas

Para el Score Engine esto puede ser aceptable. Para reportería ejecutiva, puede ser confuso.

### OD-2: Repuestos no existen en Alegra
Endpoints 1 y 3 (`ventas_repuestos`) dependen de que los repuestos estén cargados en Alegra. Hoy no lo están. ARGOS debe arrancar con `items: []` y `ventas_repuestos: []` en ambos endpoints hasta que Roddos cargue el catálogo.

### OD-3: Dataset de entrenamiento demasiado pequeño para XGBoost
26 créditos activos es un dataset insuficiente para entrenar un modelo de credit scoring confiable. ARGOS debería considerar:
- Incluir los ~100+ créditos de `loanbook_legacy` (aliados) como datos históricos, aunque con campos de originación ausentes.
- Usar modelos más simples (regresión logística, scorecard) hasta tener suficiente data.
- Definir `default_90d` con claridad — ¿90 DPD consecutivos? ¿histórico? ¿incluyendo créditos reestructurados?

### OD-4: Autenticación y rate limiting para ARGOS
Los endpoints actuales usan JWT de SISMO (`get_current_user`). ARGOS necesita:
- Un token de larga duración (API key) o un usuario de servicio, no un JWT de 30 minutos
- Rate limiting para el snapshot semanal (puede ser pesado si la cartera crece)
- Considerar si los endpoints de ARGOS deben ser públicos (sin auth) en la red interna o con auth separada

### OD-5: Frecuencia de llamadas vs datos en tiempo real
ARGOS llama `/api/loanbook/snapshot` semanalmente (lunes 03:00). Con Motor AsyncIO la query completa de loanbook es rápida (< 1s para 26 créditos), pero `dpd_actual` se calcula en tiempo real por cada crédito. Para carteras grandes (>500 créditos), considerar precalcular y cachear el snapshot.

---

## Colecciones MongoDB relevantes (resumen)

| Colección | Uso | Relevante para |
|---|---|---|
| `loanbook` | Créditos activos V2 | Endpoint 4 |
| `loanbook_legacy` | Cartera importada de aliados | Contexto histórico para XGBoost |
| `inventario_motos` | VINs individuales registrados | Endpoint 2 |
| `apartados` | Reservas de motos | Endpoint 2 (stock disponible) |
| `catalogo_planes` | Planes P39S/P52S/P78S con cuotas por modelo | Endpoint 2 (cuotas por plazo) |
| `roddos_events` | Bus de eventos (factura.venta.creada, etc.) | Endpoint 3 (ventas alternativa a Alegra) |
| `backlog_movimientos` | Movimientos bancarios pendientes | No directamente relevante para ARGOS |

---

## Próximos pasos recomendados (prioridad)

1. **Clarificar terminología** con el equipo ARGOS: `rdx_leasing | rodante` → ¿mapea a `moto` + ¿qué más?
2. **Resolver el problema de fechas de Alegra** (debug activo en dashboard.py) — bloqueante para Endpoint 3
3. **Empezar a trackear `dpd_maximo_historico`** en MongoDB desde hoy — cuanto antes, mejor
4. **Cargar repuestos en Alegra** — bloqueante para Endpoints 1 y 3 (`ventas_repuestos`)
5. **Definir autenticación** para endpoints de ARGOS (API key vs JWT de servicio)
6. **Validar con ARGOS** qué campos del snapshot son requeridos vs opcionales para el primer modelo — probablemente se puede arrancar sin los 9 campos de scoring no trackeados

---

*Este documento es solo diagnóstico. No se modificó ningún archivo de código.*
