# SISMO V2 — Módulo Loanbook · Documento Maestro

**Versión 1.1** · 22 abril 2026
**RODDOS S.A.S. · Bogotá D.C.**
Constitución técnica del módulo, contrato con Claude Code y checklist de verificación final.

**Cambios v1 → v1.1:** DPD Opción A (rangos acortados) · Waterfall ANZI primero · Tickets RODANTE confirmados · Mora $2K/día sin cap.

**Autor:** SISMO · **Aprobado por:** Andrés Sanjuan (CEO) · 22-abr-2026

---

## 1. Identidad del módulo y alcance

El módulo Loanbook es el nodo de SISMO V2 responsable del ciclo de vida completo de cada crédito de RODDOS S.A.S. — desde que la moto o el servicio se factura hasta que el cliente queda a paz y salvo. NO es un CRM, NO es un ERP, NO es un motor de originación. Es un sistema de loan servicing calibrado a cobros semanales vía WhatsApp los miércoles.

### 1.1 Lo que el Loanbook SÍ hace

| Responsabilidad | Descripción |
|---|---|
| Servicing | Mantiene el estado operativo de cada crédito: cronograma, pagos aplicados, saldo pendiente |
| Collections | Calcula DPD diario, asigna sub-buckets semanales, escala acciones de cobranza |
| Loan Tape | Genera snapshots del portafolio exportables para reporting, análisis y eventual securitización |
| Gestión ciclo de vida | Administra transiciones de estado — Aprobado → Current → Delinquent → Default/Pagado/Modificado |
| Acuerdos de pago | Recalcula cronogramas bajo reestructuración (Forbearance / Repayment Plan / Loan Modification) |
| Cierre | Emite paz y salvo + notifica al registro vehicular (RDX) + archiva documentos |

### 1.2 Lo que el Loanbook NO hace

| Prohibición | Quién lo hace |
|---|---|
| Originación (scoring, KYC, aprobación) | Sistema externo a SISMO |
| POST a Alegra (journals, invoices) | Agente Contador únicamente (ROG-4) |
| Escribir en `cartera_pagos` | Agente Contador |
| Escribir en `crm_clientes`, `gestiones_cobranza` | Agente RADAR |
| Enviar WhatsApp al cliente directamente | RADAR vía Mercately |
| Geolocalización de clientes para cobro | Nunca — cobranza 100% remota |

> **REGLA P4 INAMOVIBLE** — Los permisos están en CÓDIGO (`validate_write_permission`), no en narrativa del prompt. El LLM no puede razonar alrededor de una restricción en código.

---

## 2. Catálogo maestro de productos

RODDOS opera dos productos de crédito con subproductos diferenciados. Esta es la tabla definitiva — fuente de verdad absoluta.

### 2.1 Productos y subproductos

| Producto | Subtipo | Ticket típico | Colateral físico | Inventario |
|---|---|---|---|---|
| RDX | Moto nueva/usada TVS | $4M – $12M | Moto (VIN, motor, placa) | `inventario_motos` |
| RODANTE | Repuestos | $50K – $500K | — | `inventario_repuestos` (nuevo) |
| RODANTE | SOAT | **$200K – $600K** | — (documento póliza) | N/A — pago a aseguradora |
| RODANTE | Comparendos | Variable | — | N/A — pago a Tránsito |
| RODANTE | Licencia conducción | **$200K – $1.400.000** | — | N/A — pago a centro enseñanza |

### 2.2 Catálogo de planes — Tabla PLAN_CUOTAS definitiva

Fuente única de verdad. Claude Code debe leerla de la colección MongoDB `catalogo_planes` — NUNCA hardcodearla.

| Plan | Duración | RDX | RODANTE | Semanal | Quincenal | Mensual |
|---|---|:---:|:---:|:---:|:---:|:---:|
| P1S | Contado (pago único) | ✓ | ✓ | 0 (sin cronograma) | N/A | N/A |
| P2S | 2 semanas | — | ✓ | 2 | N/A | N/A |
| P3S | 3 semanas | — | ✓ | 3 | N/A | N/A |
| P4S | 4 semanas | — | ✓ | 4 | N/A | N/A |
| P6S | 6 semanas | — | ✓ | 6 | N/A | N/A |
| P12S | 12 semanas | — | ✓ | 12 | N/A | N/A |
| P15S | 15 semanas | — | ✓ | 15 | N/A | N/A |
| P39S | 39 semanas / 9 meses | ✓ | — | 39 | 20 | 9 |
| P52S | 52 semanas / 12 meses | ✓ | — | 52 | 26 | 12 |
| P78S | 78 semanas / 18 meses | ✓ | — | 78 | 39 | 18 |

> **REGLA INAMOVIBLE** — Planes quincenales y mensuales aplican SOLO desde P39S. RODANTE opera únicamente en modalidad semanal (P1S a P15S). El multiplicador ×1.0/×2.2/×4.4 en el precio de la cuota aplica solo a RDX con P39S o superior.

### 2.3 Multiplicador del precio de la cuota (solo RDX P39S+)

| Modalidad | Multiplicador | Ejemplo cuota base $179.900 |
|---|:---:|---|
| Semanal | ×1.0 | $179.900 semanal |
| Quincenal | ×2.2 | $395.780 quincenal |
| Mensual | ×4.4 | $791.560 mensual |

*Este multiplicador refleja el costo financiero adicional de pagar con menor frecuencia — el capital queda expuesto más tiempo.*

### 2.4 Caso especial: P1S (Contado)

**Comportamiento:** Aprobado → Pagado directo, sin cronograma.

| Campo | Valor para P1S contado |
|---|---|
| `num_cuotas` | 0 (cero cuotas programadas) |
| `cronograma_generado` | `false` |
| `cuotas[]` | `[]` (array vacío) |
| `estado` | Aprobado → Pagado al recibir el pago |
| `dpd` | N/A (nunca se calcula) |
| `mora_acumulada` | N/A (no aplica) |
| `sub_bucket_semanal` | N/A |
| `fecha_vencimiento` | Igual a `fecha_factura` |

*Al registrar el pago de un P1S: se crea journal en Alegra, se marca loanbook como Pagado, se emite paz y salvo. No pasa por Current ni por ningún bucket de delinquency.*

---

## 3. Máquina de estados del crédito

> **v1.1** — Rangos DPD acortados vs estándar industria porque RODDOS opera con cobros semanales y plazos cortos (P2S-P15S para RODANTE). Detección 3-4× más temprana. Charge-Off más agresivo (~7 semanas en lugar de ~17).

### 3.1 Los 9 estados oficiales

Aplican a ambos productos (RDX y RODANTE) — la única diferencia es que P1S contado salta directamente de Aprobado a Pagado sin pasar por los estados intermedios.

| Estado | Color | Badge UI | DPD | Acción del sistema |
|---|---|---|:---:|---|
| **Aprobado** | 🟦 Azul | Sin Entregar | N/A | Facturado, pendiente de entrega física. Sin cuotas aún. |
| **Current** | 🟢 Verde | Al Día | 0 | Todas las cuotas pagadas a tiempo. Recordatorio martes. |
| **Early Delinquency** | 🟡 Amarillo | Atraso Leve | 1–7 | 1er jueves sin pago. WhatsApp automático + llamada. |
| **Mid Delinquency** | 🟠 Naranja | Atraso Moderado | 8–14 | 2da semana sin pago. Gestión activa intensiva. |
| **Late Delinquency** | 🔴 Rojo | Atraso Grave | **15–45** | 3–6 semanas. Escalación. Oferta reestructuración. |
| **Default** | 🔴 Rojo oscuro | Default | **46–49** | Protocolo recuperación. GPS + proceso legal. |
| **Charge-Off** | ⚫ Negro | Castigado | **50+** | Crédito castigado contablemente. Recuperación judicial. |
| **Modificado** | 🟣 Púrpura | Reestructurado | Variable | Acuerdo de pago activo. Cronograma recalculado. |
| **Pagado** | ⚪ Gris | Pagado | N/A | Crédito cerrado. Paz y salvo emitido. |

### 3.2 Sub-buckets semanales (diferencial RODDOS)

Los sub-buckets permiten alertas tempranas 3-4× más granulares que el estándar mensual. Cada sub-bucket cae dentro de un estado específico.

| Sub-bucket | DPD | Semanas perdidas | Estado | Acción RADAR |
|---|:---:|---|---|---|
| Grace | 1–7 | 1 semana | Early Delinq | WhatsApp jueves + llamada viernes |
| Warning | 8–14 | 2 semanas | Mid Delinq | Llamada diaria + WhatsApp diario (Ley 2300: máx 1/día) |
| Alert | 15–21 | 3 semanas | Late Delinq | Escalación a admin. Oferta acuerdo de pago. |
| Critical | 22–30 | 4 semanas | Late Delinq | Protocolo formal. Verificación GPS activo. |
| **Severe** | **31–45** | 5–6 semanas | Late Delinq | Fase prejudicial. Comunicación formal escrita. |
| **Pre-default** | **46–49** | ~7 semanas | Default | Evaluación recuperación voluntaria vs forzada. |
| **Default** | **50+** | 7+ semanas | Charge-Off | Protocolo recuperación. GPS + Motos del Trópico. |

> **Cómputo del DPD** — La mora empieza el JUEVES (día siguiente al miércoles de vencimiento). DPD se cuenta desde ese jueves en días calendario. **$2.000 COP por día de mora acumulable sin cap.** Aplica por cada día completo posterior al miércoles de la cuota vencida.

### 3.3 Transiciones de estado permitidas

| Desde | Hacia | Condición / Trigger |
|---|---|---|
| — (nuevo) | Aprobado | Factura creada en Alegra (evento `factura.venta.creada`) |
| Aprobado | Current | Registrar entrega + primera cuota aún no vence |
| Aprobado | Pagado | Solo en P1S contado: pago recibido |
| Current | Early Delinquency | DPD pasa de 0 a 1 (jueves sin pago) |
| Early Delinquency | Current | Cure: cliente paga y normaliza |
| Early Delinquency | Mid Delinquency | DPD pasa de 7 a 8 |
| Mid Delinquency | Late Delinquency | DPD pasa de 14 a 15 |
| **Late Delinquency** | **Default** | **DPD pasa de 45 a 46** |
| **Default** | **Charge-Off** | **DPD pasa de 49 a 50** |
| Cualquier activo | Modificado | Registro de acuerdo de pago (human gate) |
| Current, Early/Mid/Late Delinq | Pagado | Saldo llega a $0 |
| Modificado | Current | Cliente cumple primer pago del acuerdo |
| Modificado | Late Delinquency | Cliente incumple acuerdo |

---

## 4. Waterfall de pagos

El waterfall define el orden estricto en que se aplica cada pago recibido. Sin un waterfall claro, la contabilidad mezcla conceptos y el CFO no puede distinguir ingreso financiero de reducción de cartera.

### 4.1 Waterfall DEFINITIVO — Opción A (ANZI primero)

*Aprobado por Andrés el 22 de abril de 2026. Prioridad oficial y única del sistema.*

| Prioridad | Concepto | Justificación |
|:---:|---|---|
| **1º** | ANZI 2% del pago (comisión garantizada al avalista) | Obligación contractual con ANZI. Se extrae primero del monto total. |
| 2º | Intereses de mora acumulados | Recupera el costo del atraso. Penaliza la mora. |
| 3º | Cuotas vencidas (capital + interés separado) | Normaliza la cuenta. Reduce DPD. |
| 4º | Cuota corriente (capital + interés separado) | Pago regular del período actual. |
| 5º | Payoff fees (si liquida anticipado) | Fees por liquidación anticipada (si aplica). |
| 6º | Abono a capital anticipado | Si sobra dinero después de cubrir todo lo anterior. |

> **Ejemplo numérico** — Cliente paga $200.000 con mora acumulada $30.000, cuota corriente $179.900. ANZI = 2% × $200K = $4.000. Restan $196K. Mora $30K → quedan $166K. Cuota $179.900 → se cubre parcial $166K (queda pendiente $13.900 + mora nueva al día siguiente).

### 4.2 Separación contable obligatoria

Cada pago debe descomponerse en estas líneas que van a Alegra como journal separado:

| Concepto del pago | Débito | Crédito | Efecto en P&L |
|---|---|---|---|
| Interés de mora | Banco | Ingreso por mora (4815XX) | + ingreso no operacional |
| Interés regular cuota | Banco | Ingreso financiero cartera (4160XX) | + ingreso operacional |
| Capital de la cuota | Banco | CXC Cliente (1305XX) | No afecta P&L — reduce balance |
| Abono anticipado | Banco | CXC Cliente (1305XX) | No afecta P&L — reduce balance |
| ANZI 2% | Banco | Pasivo con ANZI (2335XX) | No afecta P&L — aumenta pasivo |

> **Regla contable** — El Agente Loanbook calcula la distribución del pago según el waterfall oficial (Opción A). El Agente Contador recibe la distribución por el bus de eventos y crea el journal en Alegra con las líneas correctas. Nunca al revés — el Loanbook NO escribe en Alegra.

---

## 5. Loan Tape definitivo — Campos obligatorios

El loan tape es el snapshot completo del portafolio. Cada fila = un crédito. Cada columna = un atributo auditable. Se genera on-demand + semanal (lunes 06:00 AM) para reporting.

### 5.1 Campos base (aplican a RDX y RODANTE)

| # | Campo | Tipo | Ejemplo |
|:---:|---|---|---|
| 1 | `loanbook_codigo` | string | LB-2026-0012 |
| 2 | `producto` | enum | RDX \| RODANTE |
| 3 | `subtipo_rodante` | enum (nullable) | repuestos \| soat \| comparendo \| licencia |
| 4 | `cliente_nombre` | string | Chenier Quintero |
| 5 | `cliente_cedula` | string | 1283367 |
| 6 | `cliente_telefono` | string | +573001234567 |
| 7 | `cliente_ciudad` | string | Bogotá |
| 8 | `plan_codigo` | string | P52S |
| 9 | `modalidad_pago` | enum | contado \| semanal \| quincenal \| mensual |
| 10 | `fecha_factura` | date | 2026-03-10 |
| 11 | `fecha_entrega` | date (nullable) | 2026-03-17 |
| 12 | `fecha_vencimiento` | date (nullable) | 2027-09-08 |
| 13 | `monto_original` | number | 11692200 |
| 14 | `cuota_inicial` | number | 500000 |
| 15 | `cuota_periodica` | number | 179900 |
| 16 | `tasa_ea` | number | 0.39 |
| 17 | `total_cuotas` | number | 78 |
| 18 | `cuotas_pagadas` | number | 12 |
| 19 | `cuotas_vencidas` | number | 2 |
| 20 | `saldo_capital` | number | 9500000 |
| 21 | `saldo_intereses` | number | 180000 |
| 22 | `mora_acumulada_cop` | number (sin cap) | 28000 ($2K × 14 días) |
| 23 | `dpd` | number | 14 |
| 24 | `estado` | enum (9 oficiales) | Mid Delinquency |
| 25 | `sub_bucket_semanal` | enum (nullable) | Warning |
| 26 | `score_riesgo` | enum (nullable) | B |
| 27 | `factura_alegra_id` | string | INV-2026-0089 |
| 28 | `fecha_ultimo_pago` | date (nullable) | 2026-04-15 |
| 29 | `vendedor` | string (nullable) | Iván Echeverri |
| 30 | `whatsapp_status` | enum | read \| delivered \| failed |
| 31 | `fecha_snapshot` | datetime | 2026-04-22T06:00:00Z |

### 5.2 Campos condicionales por producto

#### 5.2.1 Cuando producto = RDX (moto)

| # | Campo | Ejemplo |
|---|---|---|
| 32-RDX | `moto_vin` | 9FL25AF31VDB95058 |
| 33-RDX | `moto_modelo` | TVS Raider 125 |
| 34-RDX | `moto_motor` | BF3AT18C2356 |
| 35-RDX | `moto_placa` | ABC12D |
| 36-RDX | `moto_año` | 2026 |
| 37-RDX | `moto_cilindraje` | 125 |
| 38-RDX | `moto_valor_origen` | 11692200 |
| 39-RDX | `ltv` | 0.94 (loan_to_value) |

#### 5.2.2 Cuando producto = RODANTE y subtipo = repuestos

| # | Campo | Ejemplo |
|---|---|---|
| 32-REP | `referencia_sku` | TVS-KIT-001 |
| 33-REP | `cantidad` | 2 |
| 34-REP | `valor_unitario` | 125000 |
| 35-REP | `descripcion_repuesto` | Kit embrague TVS Raider |
| 36-REP | `inventario_origen_id` | INV-REP-2026-0042 |

#### 5.2.3 Cuando producto = RODANTE y subtipo = soat

| # | Campo | Ejemplo |
|---|---|---|
| 32-SOAT | `poliza_numero` | SV-456789 |
| 33-SOAT | `aseguradora` | Sura |
| 34-SOAT | `cilindraje_moto` | 125 |
| 35-SOAT | `vigencia_desde` | 2026-04-22 |
| 36-SOAT | `vigencia_hasta` | 2027-04-22 |
| 37-SOAT | `valor_soat` | 450000 (rango $200K–$600K) |
| 38-SOAT | `placa_cubierta` | ABC12D |

#### 5.2.4 Cuando producto = RODANTE y subtipo = comparendo

| # | Campo | Ejemplo |
|---|---|---|
| 32-COMP | `comparendo_numero` | CMP-B-987654 |
| 33-COMP | `entidad_emisora` | Tránsito Bogotá |
| 34-COMP | `fecha_infraccion` | 2026-02-15 |
| 35-COMP | `valor_comparendo` | 780000 |
| 36-COMP | `codigo_infraccion` | D02 (invadir carril exclusivo) |

#### 5.2.5 Cuando producto = RODANTE y subtipo = licencia

| # | Campo | Ejemplo |
|---|---|---|
| 32-LIC | `categoria_licencia` | A2 (moto ≤125cc) |
| 33-LIC | `centro_ensenanza_nombre` | Escuela de Conducción XYZ |
| 34-LIC | `centro_ensenanza_nit` | 900123456-7 |
| 35-LIC | `fecha_inicio_curso` | 2026-05-01 |
| 36-LIC | `valor_curso` | 320000 (rango $200K–$1.4M) |

**Total campos del Loan Tape:** 31 base + 4 a 8 condicionales según subtipo = hasta 39 campos por crédito.

---

## 6. Schema MongoDB completo

### 6.1 Colección `loanbook` (existente — ampliar)

Los campos condicionales por subtipo viven dentro del subdocumento `metadata_producto`.

Ejemplo de documento para RDX (moto):

```json
{
  "_id": ObjectId("..."),
  "loanbook_codigo": "LB-2026-0012",
  "producto": "RDX",
  "subtipo_rodante": null,
  "cliente": { "nombre": "Chenier Quintero", "cedula": "1283367", "telefono": "+573001234567", "ciudad": "Bogotá" },
  "plan_codigo": "P52S",
  "modalidad_pago": "semanal",
  "fecha_factura": ISODate("2026-03-10"),
  "fecha_entrega": ISODate("2026-03-17"),
  "fecha_vencimiento": ISODate("2027-03-11"),
  "monto_original": 10814800,
  "cuota_inicial": 1460000,
  "cuota_periodica": 179900,
  "tasa_ea": 0.39,
  "total_cuotas": 52,
  "cuotas": [ /* array de 52 objetos cuota */ ],
  "estado": "Current",
  "sub_bucket_semanal": null,
  "dpd": 0,
  "mora_acumulada_cop": 0,
  "saldo_capital": 8275400,
  "saldo_intereses": 0,
  "score_riesgo": "A+",
  "factura_alegra_id": "INV-2026-0045",
  "fecha_ultimo_pago": ISODate("2026-04-15"),
  "vendedor": "Iván Echeverri",
  "whatsapp_status": "delivered",
  "metadata_producto": {
    "moto_vin": "9FL25AF31VDB95058",
    "moto_modelo": "TVS Raider 125",
    "moto_motor": "BF3AT18C2356",
    "moto_placa": "ABC12D",
    "moto_año": 2026,
    "moto_cilindraje": 125,
    "moto_valor_origen": 10814800,
    "ltv": 0.94
  },
  "acuerdo_activo_id": null,
  "created_at": ISODate("2026-03-10"),
  "updated_at": ISODate("2026-04-22")
}
```

### 6.2 Subdocumento `cuota` (elementos del array `cuotas[]`)

Cada cuota separa capital, interés y fees. Crítico para la separación contable.

| Campo | Tipo | Descripción |
|---|---|---|
| `numero` | int | Número consecutivo 1..N |
| `fecha_programada` | date | Miércoles de vencimiento |
| `monto_total` | number | Capital + interés de esta cuota |
| `monto_capital` | number | Parte que reduce saldo |
| `monto_interes` | number | Parte ingreso financiero |
| `monto_fees` | number | Fees adicionales (si aplica) |
| `estado` | enum | pendiente \| pagada \| vencida \| parcial |
| `fecha_pago` | date (nullable) | Cuándo se registró el pago |
| `monto_pagado` | number | Lo efectivamente pagado |
| `metodo_pago` | enum (nullable) | transferencia \| efectivo \| nequi \| daviplata \| pse |
| `referencia` | string (nullable) | Referencia bancaria |
| `banco` | string (nullable) | Bancolombia \| BBVA \| Davivienda \| Banco Bogotá |
| `mora_acumulada` | number | Mora $2K/día sin cap al momento del cobro |
| `mora_pagada` | number | Mora efectivamente cobrada |
| `anzi_pagado` | number | Comisión ANZI 2% de este pago (prioridad 1) |
| `saldo_despues` | number | Saldo capital después de aplicar |

### 6.3 Colecciones nuevas a crear

| Colección | Propósito | Build |
|---|---|:---:|
| `catalogo_planes` | Los 10 planes con num_cuotas y multiplicadores por modalidad. Fuente única de verdad. NUNCA hardcodear. | **B0** |
| `catalogo_rodante` | Metadata de los 4 subtipos: campos requeridos por cada uno, validaciones, ejemplos | **B0** |
| `inventario_repuestos` | Inventario de repuestos para RODANTE subtipo=repuestos. SKU, cantidad disponible, costo, precio venta | B1 |
| `loanbook_acuerdos` | Acuerdos de pago activos con cronograma modificado. Trigger estado Modificado | B1 |
| `loanbook_cierres` | Registro de créditos saldados. Contiene paz y salvo digital, fecha cierre, modo (natural o liquidación anticipada) | B1 |
| `loanbook_modificaciones` | Audit log — cada cambio en el loanbook con quién, cuándo y por qué | B1 |

### 6.4 Documentos exactos a insertar en `catalogo_planes` (B0)

```js
// 10 documentos
{ "plan_codigo": "P1S",  "descripcion": "Contado (pago único)",      "aplica_a": ["RDX","RODANTE"], "cuotas_por_modalidad": {"semanal": 0},  "multiplicador_precio": {"semanal": 1.0}, "activo": true }
{ "plan_codigo": "P2S",  "descripcion": "2 semanas",                 "aplica_a": ["RODANTE"],       "cuotas_por_modalidad": {"semanal": 2},  "multiplicador_precio": {"semanal": 1.0}, "activo": true }
{ "plan_codigo": "P3S",  "descripcion": "3 semanas",                 "aplica_a": ["RODANTE"],       "cuotas_por_modalidad": {"semanal": 3},  "multiplicador_precio": {"semanal": 1.0}, "activo": true }
{ "plan_codigo": "P4S",  "descripcion": "4 semanas",                 "aplica_a": ["RODANTE"],       "cuotas_por_modalidad": {"semanal": 4},  "multiplicador_precio": {"semanal": 1.0}, "activo": true }
{ "plan_codigo": "P6S",  "descripcion": "6 semanas",                 "aplica_a": ["RODANTE"],       "cuotas_por_modalidad": {"semanal": 6},  "multiplicador_precio": {"semanal": 1.0}, "activo": true }
{ "plan_codigo": "P12S", "descripcion": "12 semanas",                "aplica_a": ["RODANTE"],       "cuotas_por_modalidad": {"semanal": 12}, "multiplicador_precio": {"semanal": 1.0}, "activo": true }
{ "plan_codigo": "P15S", "descripcion": "15 semanas",                "aplica_a": ["RODANTE"],       "cuotas_por_modalidad": {"semanal": 15}, "multiplicador_precio": {"semanal": 1.0}, "activo": true }
{ "plan_codigo": "P39S", "descripcion": "39 semanas / 9 meses",      "aplica_a": ["RDX"],           "cuotas_por_modalidad": {"semanal": 39, "quincenal": 20, "mensual": 9},  "multiplicador_precio": {"semanal": 1.0, "quincenal": 2.2, "mensual": 4.4}, "activo": true }
{ "plan_codigo": "P52S", "descripcion": "52 semanas / 12 meses",     "aplica_a": ["RDX"],           "cuotas_por_modalidad": {"semanal": 52, "quincenal": 26, "mensual": 12}, "multiplicador_precio": {"semanal": 1.0, "quincenal": 2.2, "mensual": 4.4}, "activo": true }
{ "plan_codigo": "P78S", "descripcion": "78 semanas / 18 meses",     "aplica_a": ["RDX"],           "cuotas_por_modalidad": {"semanal": 78, "quincenal": 39, "mensual": 18}, "multiplicador_precio": {"semanal": 1.0, "quincenal": 2.2, "mensual": 4.4}, "activo": true }
```

### 6.5 Documentos exactos a insertar en `catalogo_rodante` (B0)

```js
// 4 documentos — uno por subtipo
{
  "subtipo": "repuestos",
  "descripcion": "Microcrédito para repuestos de moto",
  "ticket_min": 50000, "ticket_max": 500000,
  "planes_validos": ["P1S","P2S","P3S","P4S","P6S","P12S","P15S"],
  "required_fields": ["referencia_sku","cantidad","valor_unitario","descripcion_repuesto","inventario_origen_id"],
  "inventario": "inventario_repuestos",
  "activo": true
}
{
  "subtipo": "soat",
  "descripcion": "Financiación SOAT — RODDOS paga aseguradora, financia al cliente",
  "ticket_min": 200000, "ticket_max": 600000,
  "planes_validos": ["P1S","P2S","P3S","P4S","P6S","P12S","P15S"],
  "required_fields": ["poliza_numero","aseguradora","cilindraje_moto","vigencia_desde","vigencia_hasta","valor_soat","placa_cubierta"],
  "inventario": null,
  "activo": true
}
{
  "subtipo": "comparendo",
  "descripcion": "Financiación pago comparendos — RODDOS paga Tránsito, financia al cliente",
  "ticket_min": 100000, "ticket_max": 5000000,
  "planes_validos": ["P1S","P2S","P3S","P4S","P6S","P12S","P15S"],
  "required_fields": ["comparendo_numero","entidad_emisora","fecha_infraccion","valor_comparendo","codigo_infraccion"],
  "inventario": null,
  "activo": true
}
{
  "subtipo": "licencia",
  "descripcion": "Financiación licencia de conducción — RODDOS paga centro, financia al cliente",
  "ticket_min": 200000, "ticket_max": 1400000,
  "planes_validos": ["P1S","P2S","P3S","P4S","P6S","P12S","P15S"],
  "required_fields": ["categoria_licencia","centro_ensenanza_nombre","centro_ensenanza_nit","fecha_inicio_curso","valor_curso"],
  "inventario": null,
  "activo": true
}
```

### 6.6 Patrón de acceso a MongoDB (NOTA para Claude Code)

El `catalogo_service.py` que se crea en B0 debe usar **el patrón de acceso a MongoDB que ya existe en el repo SISMO-V2**, no un patrón inventado. Inspeccionar cómo otros servicios existentes (ej. `accounting_engine.py`, `bank_reconciliation.py`) acceden a la DB y replicar el mismo enfoque. El ejemplo en el prompt B0 (`from backend.database import db`) es ilustrativo — si el repo usa `Depends(get_db)` vía Motor, o un singleton distinto, adaptar.

---

## 7. Tools del Agente Loanbook (Anthropic Tool Use)

El Agente Loanbook expone 11 tools. Todas deben estar registradas en el router Tool Use del chat conversacional — no basta con tener el endpoint REST.

| # | Tool | Categoría | Input principal | Output |
|:---:|---|---|---|---|
| 1 | `consultar_loanbook` | Consulta | loanbook_codigo o nombre_cliente | Estado completo del crédito |
| 2 | `listar_loanbooks` | Consulta | filtros: producto, estado, plan, modalidad, dpd_min/max | Lista paginada con saldos y DPD |
| 3 | `registrar_entrega` | Escritura | codigo, fecha_entrega, modalidad, plan | Cronograma generado + evento bus |
| 4 | `registrar_pago` | Escritura | codigo, monto, banco, referencia, fecha_pago | Distribución waterfall + evento bus |
| 5 | `calcular_liquidacion` | Consulta | codigo, fecha_liquidacion | Saldo exacto con descuento por liquidación anticipada |
| 6 | `registrar_acuerdo_pago` | Escritura | codigo, nueva_cuota, nuevo_plazo, motivo | Cronograma recalculado + estado Modificado |
| 7 | `cerrar_credito` | Escritura | codigo | Paz y salvo + evento credito.saldado |
| 8 | `diagnosticar_loanbooks` | Consulta | ninguno | Anomalías: VIN null, saldos rotos, cuotas fantasma |
| 9 | `calcular_dpd_todos` | Scheduler | automático 06:00 AM | DPD + estado + sub_bucket actualizado |
| 10 | `generar_loan_tape` | Reporte | fecha_corte, formato (xlsx\|json\|csv) | Snapshot del portafolio completo |
| 11 | `consultar_mora` | Consulta | filtro por bucket o global | Métricas de mora exclusivas |

> **ROG-1 + validación fecha_pago** — Todo tool que escriba debe usar `request_with_verify()` al delegar al Contador. Todo tool que maneje `fecha_pago` debe rechazar fecha > hoy con HTTP 422.

---

## 8. Los 5 módulos core del Agente Loanbook

| Módulo | Responsabilidad | Tools que expone |
|---|---|---|
| 1. Motor de Origination | Captura datos del deudor y la moto/servicio; valida combinación producto×plan×modalidad; genera el cronograma de amortización según Regla del Miércoles. | `registrar_entrega` |
| 2. Motor de Servicing | Procesa pagos según waterfall (ANZI primero); genera recibos; mantiene ledger inmutable con posibilidad retroactiva. | `registrar_pago`, `calcular_liquidacion` |
| 3. Motor de Collections | Escalamiento por sub-buckets semanales (rangos v1.1); tracking de PTP; gestión de acuerdos; alertas WhatsApp vía RADAR. | `registrar_acuerdo_pago`, `consultar_mora` |
| 4. Generador de Loan Tape | Snapshots on-demand + programados (lunes 06:00 AM); exportación multi-formato; 37+ campos con condicionales por producto. | `generar_loan_tape`, `consultar_loanbook`, `listar_loanbooks`, `diagnosticar_loanbooks` |
| 5. Dashboard Analytics | Vintage curves por cohorte; roll rate matrices; delinquency trend lines; concentration analysis. (Phase 8) | `consultar_mora` (agregadas) |

---

## 9. Métricas del dashboard (Phase 8)

*Umbrales v1.1 ajustados a DPD acortados.*

| Métrica | Fórmula | Frecuencia | Umbral alerta |
|---|---|---|---|
| TOP (Total Outstanding Principal) | Σ saldo_capital activos | Diaria | — |
| WAC (Weighted Avg Coupon) | Σ(tasa_i × saldo_i) / Σ saldo_i | Semanal | — |
| WAM (Weighted Avg Maturity) | Σ(semanas_restantes × saldo) / Σ saldo | Semanal | — |
| **Delinquency Rate 15+** | Σ saldo Late+ / Σ saldo × 100 | Diaria | **> 10%** |
| **Delinquency Rate 46+** | Σ saldo Default+ / Σ saldo × 100 | Diaria | **> 3%** |
| Roll Rate Current → Early Delinq | Saldo migra / Saldo origen × 100 | Semanal | > 6% |
| Roll Rate Mid → Late | idem | Semanal | > 30% |
| Net Charge-Off Rate (NCO) | (Charge-offs − Recoveries) / Avg Outstanding | Mensual | — |
| Collection Rate | Cobrado / Debido × 100 | Semanal | < 95% |
| Cure Rate | Regresos a Current / Total delinq × 100 | Semanal | < 60% |
| PTP Rate + PTP Kept Rate | Promesas/Contactos · Cumplidas/Promesas | Semanal | — |
| WhatsApp Metrics | Delivery · Read · Response · WA-to-Payment Conv | Diaria | — |

### 9.1 Métricas específicas de mora (umbrales v1.1)

| Indicador | Fórmula | Umbral |
|---|---|---|
| Días de mora promedio cartera | Σ DPD activos / N | > 5 días |
| % Cartera en mora (1+ DPD) | Saldo 1+ DPD / Saldo total × 100 | > 15% |
| Valor en mora (COP) | Σ saldo con DPD > 0 | > $15M |
| Intereses de mora pendientes | Σ (DPD × $2.000) por loanbook en mora | > $500K |
| Tasa mora temprana (Early 1-7) | N en bucket / Total × 100 | > 20% |
| **Tasa mora grave (Late 15+)** | N en Late+/Default+/CO / Total × 100 | **> 10%** |
| **Tasa pre-default (46-49)** | N en Default / Total × 100 | **> 3%** |

---

## 10. Estructura del Excel `loanbook_roddos`

Nombre del archivo: `loanbook_roddos_YYYY-MM-DD.xlsx` (NO `portafolio_roddos`).

| Hoja | Contenido | Filas esperadas |
|:---:|---|---|
| 1. Loan Tape RDX | Un crédito por fila. Columnas base + condicionales moto. Celdas rojas en diferencias. | ~N de créditos RDX |
| 2. Loan Tape RODANTE | Un crédito por fila. Columnas base + condicionales del subtipo. | ~N de créditos RODANTE |
| 3. Cronograma de cuotas | Una cuota por fila. Separa capital/interés/fees. Color coding por estado. | Σ total_cuotas |
| 4. KPIs de Mora | Indicadores del corte. Valores + umbrales v1.1 + estado semáforo. | ~8 indicadores |
| 5. Matriz Roll Rate | Heatmap 5×5 de migración entre buckets. Color intensity = % migración. | 5×5 |

### 10.1 Columnas Hoja 1 — Loan Tape RDX (bloques)

| Bloque | Columnas |
|---|---|
| Identificación | `loanbook_codigo · producto · cliente_nombre · cliente_cedula · cliente_telefono · cliente_ciudad` |
| Términos | `plan_codigo · modalidad_pago · fecha_factura · fecha_entrega · fecha_vencimiento` |
| Moto (colateral) | `moto_vin · moto_modelo · moto_motor · moto_placa · moto_año · moto_cilindraje · moto_valor_origen · ltv` |
| Montos | `monto_original · cuota_inicial · cuota_periodica · tasa_ea` |
| Desempeño | `total_cuotas · cuotas_pagadas · cuotas_vencidas · saldo_capital · saldo_intereses · mora_acumulada_cop · dpd` |
| Estado | `estado · sub_bucket_semanal · score_riesgo` |
| Enlaces | `factura_alegra_id · fecha_ultimo_pago · vendedor · whatsapp_status · fecha_snapshot` |

### 10.2 Columnas Hoja 2 — Loan Tape RODANTE

| Subtipo | Columnas específicas |
|---|---|
| repuestos | `referencia_sku · cantidad · valor_unitario · descripcion_repuesto · inventario_origen_id` |
| soat | `poliza_numero · aseguradora · cilindraje_moto · vigencia_desde · vigencia_hasta · valor_soat · placa_cubierta` |
| comparendo | `comparendo_numero · entidad_emisora · fecha_infraccion · valor_comparendo · codigo_infraccion` |
| licencia | `categoria_licencia · centro_ensenanza_nombre · centro_ensenanza_nit · fecha_inicio_curso · valor_curso` |

### 10.3 Columnas Hoja 3 — Cronograma

| Columna | Descripción |
|---|---|
| `loanbook_codigo` | Identificador del crédito |
| `cliente_nombre` | Nombre del deudor |
| `numero_cuota` | 1..N |
| `fecha_programada` | Miércoles de vencimiento |
| `monto_total` | Capital + interés |
| `monto_capital` | Componente principal |
| `monto_interes` | Componente interés |
| `monto_fees` | Fees adicionales |
| `estado` | pendiente · pagada · vencida · parcial |
| `fecha_pago` | Cuándo se pagó (nullable) |
| `monto_pagado` | Lo efectivamente recibido |
| `metodo_pago` | transferencia · efectivo · nequi · etc |
| `banco` | Bancolombia · BBVA · Davivienda · etc |
| `referencia` | Referencia bancaria |
| `mora_acumulada` | Mora $2K/día sin cap al momento del cobro |
| `mora_pagada` | Mora efectivamente cobrada |
| `anzi_pagado` | Comisión ANZI 2% (prioridad 1 del waterfall) |
| `saldo_despues` | Saldo capital tras aplicar |
| `es_corrupta` | ✓ No / ✗ Sí |
| `motivo_corrupcion` | Descripción si aplica |

---

## 11. Plan de ejecución — 6 Builds

Total estimado: 14 horas. Orden no negociable: B0 → B1 → B3 → (B2 ∥ B4) → B5. El Build 0 es bloqueante de todo lo demás.

### 11.1 BUILD B0 — Catálogos maestros en MongoDB

**Tiempo:** 1.5h · **Dependencias:** Ninguna · **Bloquea:** B1, B2, B3, B4, B5

| Entregable | Criterio de éxito |
|---|---|
| Colección `catalogo_planes` poblada | 10 documentos exactos según cap 6.4 |
| Colección `catalogo_rodante` poblada | 4 documentos exactos según cap 6.5 |
| `backend/services/loanbook/reglas_negocio.py` refactorizado | Lee de MongoDB — sin PLAN_CUOTAS hardcoded |
| `scripts/poblar_catalogos.py` | Idempotente — upsert por plan_codigo / subtipo |
| Tests 12+ GREEN | Validan cada plan × modalidad y cada subtipo |

### 11.2 BUILD B1 — Schema dual + colecciones nuevas

**Tiempo:** 2.5h · **Dependencias:** B0

| Entregable | Criterio de éxito |
|---|---|
| Schema `loanbook` expandido | `metadata_producto` + `saldo_intereses` + `score_riesgo` + `whatsapp_status` + `sub_bucket_semanal` + `fecha_vencimiento` |
| Colección `inventario_repuestos` | Índice único por SKU |
| Colección `loanbook_acuerdos` | Con cronograma_nuevo embebido |
| Colección `loanbook_cierres` | Con paz_y_salvo_url |
| Colección `loanbook_modificaciones` | Audit log con user_id y timestamp |
| Validator Pydantic dual RDX/RODANTE | Rechaza combinación inválida (ej: RODANTE+P78S) |
| Migración de los 28 loanbooks existentes | producto=RDX + metadata_producto relleno |
| Tests 25+ GREEN | Schema dual y combinaciones válidas/inválidas |

### 11.3 BUILD B2 — Máquina de estados + sub-buckets (v1.1)

**Tiempo:** 2.5h · **Dependencias:** B1

| Entregable | Criterio de éxito |
|---|---|
| `clasificar_estado(dpd, saldo, tipo_producto)` | Retorna uno de los 9 estados — rangos v1.1 |
| `clasificar_sub_bucket(dpd)` | Retorna uno de los 7 sub-buckets — rangos v1.1 |
| scheduler `calcular_dpd_todos()` | Actualiza estado + sub_bucket + mora_acumulada sin cap |
| Badge component en React | Pill-shaped con los 9 colores oficiales |
| Tabla de transiciones validada | Intento inválido → HTTP 422 |
| Caso especial P1S | Aprobado → Pagado directo al registrar pago |
| Tests 20+ GREEN | Cubren las 13 transiciones del cap 3.3 |

### 11.4 BUILD B3 — Loan Tape Excel con 5 hojas

**Tiempo:** 3h · **Dependencias:** B0, B1

| Entregable | Criterio de éxito |
|---|---|
| Nombre: `loanbook_roddos_YYYY-MM-DD.xlsx` | NO `portafolio_roddos` |
| Hoja 1 Loan Tape RDX | 28+ columnas según cap 10.1 |
| Hoja 2 Loan Tape RODANTE | Columnas base + condicionales subtipo |
| Hoja 3 Cronograma | 20 columnas con capital/interés/fees separados |
| Hoja 4 KPIs de Mora | 8 indicadores con umbrales v1.1 |
| Hoja 5 Matriz Roll Rate | 5×5 |
| Celdas rojas en diferencias | Valor DB ≠ tabla fija |
| Tests 10+ GREEN | Estructura y nombre |

### 11.5 BUILD B4 — Amortización + waterfall ANZI + P1S contado

**Tiempo:** 2.5h · **Dependencias:** B0, B1

| Entregable | Criterio de éxito |
|---|---|
| Generador de cronograma | Cada cuota separa monto_capital + monto_interes (amortización francesa) |
| Waterfall Opción A | 1.ANZI → 2.Mora → 3.Vencidas → 4.Corriente → 5.Payoff fees → 6.Capital anticipado |
| Caso P1S contado | Sin cronograma, estado Aprobado → Pagado al pago |
| Payoff calculator | `calcular_liquidacion` con descuento anticipado |
| Evento `pago.cuota.registrado` | Incluye desglose anzi/mora/interes/capital |
| Handler Contador actualizado | Crea 5 líneas separadas según cap 4.2 |
| UI Payoff breakdown (bar chart) | Capital · Interés · Fees · ANZI |
| Tests 25+ GREEN | Todas las combinaciones producto×plan×modalidad + waterfall |

### 11.6 BUILD B5 — 11 Tools + chat conversacional

**Tiempo:** 2.5h · **Dependencias:** B0-B4

| Entregable | Criterio de éxito |
|---|---|
| 11 tools registradas en Tool Use | JSON schemas completos según cap 7 |
| Router con confidence threshold 0.70 | Si dudoso → pregunta antes de despachar |
| System prompt diferenciado Loanbook | Sin reglas tributarias ni plan de cuentas Alegra |
| Chat end-to-end | 'Cobré $179.900 a Chenier Bancolombia' → waterfall → evento → journal Alegra → WhatsApp |
| WRITE_PERMISSIONS en código | Loanbook no puede escribir en cartera_pagos ni POST Alegra |
| Tests 30+ GREEN | 11 tools + router + permisos |

---

## 12. Checklist de verificación final

Al cerrar los 6 builds, se ejecuta este checklist. No se declara completitud hasta que TODAS las líneas estén en verde.

### 12.1 Bloque 1 — Catálogos y schema

| # | Item | Criterio |
|:---:|---|---|
| C-01 | `catalogo_planes` tiene 10 documentos | `db.catalogo_planes.count() === 10` |
| C-02 | `catalogo_rodante` tiene 4 documentos | `db.catalogo_rodante.count() === 4` |
| C-03 | `reglas_negocio.py` lee de MongoDB | grep: sin `PLAN_CUOTAS` hardcoded |
| C-04 | Colección `inventario_repuestos` existe | `db.inventario_repuestos.findOne()` no null |
| C-05 | Colección `loanbook_acuerdos` existe | idem |
| C-06 | Colección `loanbook_cierres` existe | idem |
| C-07 | Colección `loanbook_modificaciones` existe | idem |
| C-08 | Schema `loanbook` expandido | `findOne` tiene `metadata_producto` y `saldo_intereses` |
| C-09 | Los 28 loanbooks existentes migrados | `producto=RDX` + `metadata_producto` no null |

### 12.2 Bloque 2 — Productos y planes

| # | Item | Criterio |
|:---:|---|---|
| P-01 | RDX P1S funciona como contado | `num_cuotas=0`, estado Pagado al pago |
| P-02 | RDX P39S semanal = 39 cuotas | length=39 |
| P-03 | RDX P39S quincenal = 20 cuotas | length=20 |
| P-04 | RDX P39S mensual = 9 cuotas | length=9 |
| P-05 | RDX P52S × 3 modalidades | 52/26/12 |
| P-06 | RDX P78S × 3 modalidades | 78/39/18 |
| P-07 | RODANTE P1S (4 subtipos) | contado sin cronograma |
| P-08 | RODANTE P2S-P15S semanales | 2/3/4/6/12/15 cuotas |
| P-09 | RODANTE NO acepta quincenal/mensual | POST modalidad=quincenal → HTTP 422 |
| P-10 | RODANTE NO acepta P39S+ | POST plan=P78S → HTTP 422 |
| P-11 | Multiplicador aplica RDX | ×1.0 · ×2.2 · ×4.4 |
| P-12 | Multiplicador NO aplica RODANTE | Siempre ×1.0 |

### 12.3 Bloque 3 — Estados y sub-buckets (rangos v1.1)

| # | Item | Criterio |
|:---:|---|---|
| E-01 | 9 estados implementados | Enum coincide con cap 3.1 |
| E-02 | 7 sub-buckets implementados | Enum coincide con cap 3.2 |
| **E-03** | `clasificar_estado(dpd=40)` retorna Late Delinq | Rango 15-45 |
| **E-04** | `clasificar_estado(dpd=47)` retorna Default | Rango 46-49 |
| **E-05** | `clasificar_estado(dpd=60)` retorna Charge-Off | Rango 50+ |
| E-06 | Badge UI con los 9 colores oficiales | Visual inspection |
| E-07 | Scheduler 06:00 AM actualiza DPD | Todos los loanbooks al día |
| E-08 | Mora $2K/día sin cap acumula | 10 días → $20.000 |
| E-09 | Pago cura el estado automáticamente | DPD=5 paga → Current |
| E-10 | Saldo=0 → estado Pagado | Último pago cierra |
| E-11 | P1S salta estados intermedios | Aprobado → Pagado directo |

### 12.4 Bloque 4 — Waterfall ANZI y contabilidad

| # | Item | Criterio |
|:---:|---|---|
| **W-01** | Waterfall Opción A activo | ANZI 2% aplicado PRIMERO del monto total |
| W-02 | Pago se descompone en capital+interés+fees | Cada cuota tiene los 3 montos |
| W-03 | Evento `pago.cuota.registrado` con desglose | monto_mora, monto_interes, monto_capital, anzi |
| W-04 | Journal Alegra con 5 líneas separadas | Según cap 4.2 |
| W-05 | Ingreso mora → 4815XX | Correcto |
| W-06 | Ingreso financiero → 4160XX | Correcto |
| W-07 | Capital → CXC 1305XX | Correcto |
| W-08 | ANZI → pasivo 2335XX | Correcto |
| W-09 | Loanbook NO hace POST a Alegra | Audit: cero requests desde el módulo |
| W-10 | Liquidación anticipada funciona | Saldo + descuento pre-vencimiento |

### 12.5 Bloque 5 — Excel loan tape

| # | Item | Criterio |
|:---:|---|---|
| X-01 | Nombre `loanbook_roddos_YYYY-MM-DD.xlsx` | Descarga confirma el nombre |
| X-02 | Hoja 1 Loan Tape RDX con 28+ columnas | Recuento |
| X-03 | Hoja 2 Loan Tape RODANTE con condicionales subtipo | idem |
| X-04 | Hoja 3 Cronograma con capital/interés/fees separados | idem |
| X-05 | Hoja 4 KPIs con umbrales v1.1 | 8 indicadores |
| X-06 | Hoja 5 Matriz Roll Rate | 5×5 |
| X-07 | Celdas rojas en diferencias | Visual |
| X-08 | `tipo_producto` = RDX o RODANTE | No 'moto' ni 'comparendo' |
| X-09 | `subtipo_rodante` en 4 casos | repuestos/soat/comparendo/licencia |
| X-10 | LTV calculado para RDX | loan_amount / moto_valor_origen |

### 12.6 Bloque 6 — Agente y tools

| # | Item | Criterio |
|:---:|---|---|
| T-01 | 11 tools registradas en Tool Use | `tool_registry.list() === 11` |
| T-02 | `consultar_loanbook` por chat | '¿Cómo va el crédito de Chenier?' |
| T-03 | `registrar_pago` por chat | 'Cobré $179.900 a Chenier Bancolombia' |
| T-04 | Router threshold 0.70 | Dudoso → pregunta |
| T-05 | System prompt sin contexto Contador | No plan de cuentas Alegra |
| T-06 | WRITE_PERMISSIONS en código | Loanbook no escribe cartera_pagos |
| T-07 | `fecha_pago > hoy` → HTTP 422 | Todos los endpoints |
| T-08 | Bus único puente | Loanbook no llama Contador directo |

### 12.7 Smoke Test end-to-end

| # | Acción | Verificación |
|:---:|---|---|
| 1 | Vender RDX TVS Apache P52S semanal a Juan | Factura Alegra + loanbook pendiente_entrega + moto Vendida |
| 2 | Registrar entrega | Cronograma 52 cuotas + estado Current |
| 3 | Cobrar $200K (cuota $179.900 + mora $10K) | Waterfall ANZI $4K → mora $10K → cuota $179.900 → sobran $6.1K capital anticipado. Journal 5 líneas. |
| 4 | Scheduler 06:00 AM | DPD actualizado todos los loanbooks |
| 5 | Pasan 40 días sin pago | Transita a Late Delinquency (DPD=40 está en rango 15-45) |
| 6 | Pasan 47 días sin pago | Transita a Default (DPD=47 está en rango 46-49) |
| 7 | Pasan 51 días sin pago | Transita a Charge-Off (DPD=51 está en ≥50) |
| 8 | Dame loan tape | `loanbook_roddos_YYYY-MM-DD.xlsx` con 5 hojas |
| 9 | Vender SOAT contado $450K a María | RODANTE subtipo=soat + P1S → Pagado directo |

---

## 13. Reglas inamovibles del módulo Loanbook

Estas reglas NO son negociables. Violarlas rompe la arquitectura. Cualquier PR que las viole debe ser rechazado en review.

| # | Regla | Por qué existe |
|:---:|---|---|
| R-01 | Alegra es la única fuente de verdad contable (ROG-4) | Evita que MongoDB se convierta en ERP paralelo |
| R-02 | `request_with_verify()` en TODA escritura Alegra (ROG-1) | El juez es Alegra HTTP 200, no el agente |
| R-03 | Loanbook NO hace POST a Alegra bajo ninguna condición | ROG-4 puro — solo el Contador escribe |
| R-04 | Todo desarrollo desde SISMO UI (ROG-3) | PowerShell solo cuando es estrictamente necesario |
| R-05 | Sin atajos, sin deuda técnica (ROG-2) | Cada build deja el sistema mejor que antes |
| R-06 | `PLAN_CUOTAS` leído de `catalogo_planes` en MongoDB | NUNCA hardcoded en Python |
| R-07 | `fecha_pago > hoy` → HTTP 422 | No se acepta pago futuro |
| R-08 | `BackgroundTasks` + `job_id` para lotes > 10 registros | Evita timeout silencioso |
| R-09 | Anti-duplicados en 3 capas | hash + MongoDB + GET Alegra post-POST |
| R-10 | Cobranza 100% remota — nunca geolocalización | Modelo de negocio RODDOS |
| R-11 | Auteco NIT 860024781 = autoretenedor | Nunca ReteFuente en facturas Auteco |
| R-12 | Gasto socio = CXC socios | Andrés CC 80075452 · Iván CC 80086601 |
| R-13 | Loanbook NUNCA llama directamente al Contador | Solo vía bus de eventos |
| R-14 | `WRITE_PERMISSIONS` en código (no en prompt) | El LLM no puede razonar alrededor |
| R-15 | Máx 4-5 agentes en cadena secuencial | DeepMind: errores 17.2× |
| R-16 | System prompt diferenciado + threshold 0.7 | Evita mezcla de identidades |
| R-17 | Tests GREEN antes de merge a main | Ninguna regresión silenciosa |
| R-18 | Tabla fija `PLAN_CUOTAS` = NO fórmula, NO `round()` | P39S quincenal = 20, no `round(39/2.2)` |
| R-19 | Cuota debe separar capital + interés + fees | P&L limpio |
| R-20 | Cambio de estado publica evento al bus | CFO invalida caché, RADAR reacciona |
| **R-21** | **Waterfall Opción A: ANZI primero, luego mora, luego cuotas** | Decisión Andrés 22-abr-2026 |
| **R-22** | **Mora $2.000/día SIN CAP** | Política RODDOS confirmada |
| **R-23** | **RODANTE solo semanal (P1S-P15S)** | Planes cortos no admiten quincenal/mensual |

---

## 14. Cierre y aprobación

Este documento es el contrato con Claude Code para la reconstrucción del módulo Loanbook. v1.1 remueve TODAS las decisiones pendientes que quedaron abiertas en v1.

### 14.1 Decisiones cerradas en v1.1

| Decisión | v1 (pendiente) | v1.1 (cerrado) |
|---|---|---|
| Rangos DPD | 3 huecos | Opción A: 15-45 / 46-49 / 50+ |
| Sub-buckets | Desalineados | Alineados con estados (Grace-Pre_default-Default) |
| Waterfall | A o B | Opción A — ANZI primero |
| Tickets RODANTE | Valores tentativos | SOAT $200K-$600K · Licencia $200K-$1.4M |
| Mora | $2K/día con o sin cap | $2K/día SIN cap |
| Dashboard Analytics módulo 5 | Sí / No en este sprint | No — queda Phase 8 |

### 14.2 Firma

**Aprobado por:** Andrés Sanjuan · CEO
**Fecha:** 22 de abril de 2026

**Ejecutor:** Claude Code — Sprint Rescate Loanbook
**Entrega estimada:** 14 horas totales distribuidas en 6 builds atómicos
