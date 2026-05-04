# Motor Financiero del Loanbook — RODDOS V2.1

**Fuente única de verdad — código:** `backend/services/loanbook/motor.py`

**Fuente única de verdad — datos:** `loanbook_roddos_<fecha>.xlsx` que entregue Andrés.
- NUNCA usar valores en memoria ni cálculos previos para créditos, montos, cuotas iniciales, fechas, planes.
- Antes de cualquier cambio masivo: leer el Excel con openpyxl, hacer dry-run, mostrar diff Excel vs aplicar, esperar OK.
- Si el Excel no tiene un dato → preguntar a Andrés antes de actuar.
- Esta regla tiene prioridad sobre cualquier otra instrucción.

## Política de cuota inicial (RODDOS, confirmada 4-may-2026)

- **Norma:** todo crédito tiene `cuota_inicial > 0`. Se cobra ANTES de la entrega para
  poder facturar y matricular. La entrega ocurre 2-3 días después (cuando el organismo
  de tránsito entrega placas).
- **Excepción comercial:** algunos créditos (ej. ciertas Sport 100 recientes) se vendieron
  SIN cuota inicial para acelerar salida.
- **Cuota 0 en cronograma cuando CI > 0:** debe nacer como `estado="pagada"`,
  `monto_pagado=cuota_inicial`, `fecha_pago≈fecha_entrega`, `metodo_pago="cuota_inicial_pre_entrega"`.
- **Primera cuota regular:** miércoles de la semana siguiente a la entrega.

**Estado al 4 de mayo de 2026:** 43 tests verdes. Deployado en producción.

## API pública (4 funciones)

```python
crear_cronograma(
    fecha_primer_pago: date,
    num_cuotas: int,
    cuota_valor: int,
    modalidad: str,                    # "semanal" | "quincenal" | "mensual"
    capital_plan: int,
    cuota_estandar_plan: int,
    cuota_inicial: int = 0,            # NUEVO RODDOS V2.1
    fecha_cuota_inicial: date | None = None,
) -> list[dict]

aplicar_pago(
    loanbook: dict,
    monto: int,
    fecha_pago: date,
    cuota_numero: int | None = None,   # 0 = cuota inicial; None = primera pendiente
) -> dict   # {loanbook, distribucion}

derivar_estado(
    loanbook: dict,
    hoy: date | None = None,
) -> dict   # loanbook con saldo, dpd, estado, sub_bucket recalculados

auditar(
    loanbook: dict,
    hoy: date | None = None,
) -> dict   # {loanbook_id, ok, severidad, violaciones}
```

## Cuota inicial (cuota 0) — Política RODDOS V2.1

### Concepto

La **cuota inicial** es el monto pactado al originar el crédito que el cliente debe pagar antes de empezar el cronograma regular. En RODDOS opera como una "cuota 0" del cronograma:

- Se inserta al inicio del array `cuotas` con `numero = 0`
- Tiene flag `es_cuota_inicial = True`
- Su `fecha` puede ser igual o anterior a la primera cuota regular (típicamente la fecha de entrega de la moto)
- Suma al `valor_total` del crédito hasta que se cobra
- **Puede ser 0** cuando la operación comercial necesita acelerar la originación (estrategia de impulso a ventas)

### Reglas operativas

| Regla | Detalle |
|---|---|
| `valor_total` del crédito | `cuota_inicial + (cuota_periodica × num_cuotas)` |
| Cuota 0 — waterfall | **NO aplica.** Pago directo a capital. ANZI = 0, mora = 0, interés = 0. |
| Cuota 0 — DPD | **NO genera mora ni mueve estado a delinquency.** El crédito puede tener cuota 0 vencida sin que el cliente caiga en mora. |
| Cuota 0 — saldo | Suma al `saldo_pendiente` hasta que se paga. |
| Cuota 0 — saldado | Un crédito está saldado cuando TODAS sus cuotas (incluyendo la 0) están pagadas. |
| `cuota_inicial = 0` | Cronograma sin cuota 0. Comportamiento idéntico al sistema sin cuota inicial. |

### Ejemplo concreto — LB-2026-0034

```
Producto:        TVS Raider 125
Plan:            P39S semanal
Cuota_periodica: 210.000
Num_cuotas:      39
Cuota_inicial:   1.460.000     ← pactada al originar
Fecha_entrega:   2026-04-30
Fecha_cuota_0:   2026-04-30    ← misma fecha de entrega
Fecha_cuota_1:   2026-05-06    ← primer miércoles operativo

Cronograma generado:
  [0]  numero=0  fecha=2026-04-30  monto=1.460.000  capital=1.460.000  interes=0
       es_cuota_inicial=True
  [1]  numero=1  fecha=2026-05-06  monto=210.000    capital=200.154    interes=9.846
  [2]  numero=2  fecha=2026-05-13  monto=210.000    capital=200.154    interes=9.846
  ...
  [39] numero=39 fecha=2027-01-27  monto=210.000    capital=200.154    interes=9.846

valor_total = 1.460.000 + 39 × 210.000 = 9.650.000
```

### Endpoint para cobrar cuota 0

`PUT /api/loanbook/{id}/pago` con `cuota_numero = 0` aplica el pago directo a capital sin waterfall. (En Día 3 — implementación pendiente del refactor de routers).

## Waterfall §4.1 — Cuotas regulares (1..N)

Para CUALQUIER cuota distinta a la 0, el orden es estricto:

1. **ANZI 2%** del pago bruto → comisión avalista (`total_anzi_pagado`)
2. **Mora acumulada** de la cuota (`mora_acumulada` = dpd × $2.000)
3. **Interés** de la cuota (`monto_interes` del cronograma)
4. **Capital** de la cuota (`monto_capital` del cronograma)
5. **Abono anticipado** a capital de cuotas futuras (si sobra)

### Ejemplo de aplicación

```
Cliente paga $200.000 a cuota #5 (cuota=$179.900: cap $150K + int $29.9K).
Cuota tiene mora acumulada $30.000 al momento del pago.

Distribucion:
  ANZI       = 200.000 × 2%   = 4.000
  Mora       = min(196.000, 30.000) = 30.000
  Interes    = min(166.000, 29.900) = 29.900
  Capital    = min(136.100, 150.000) = 136.100
  Abono      = 0
  Total      = 200.000

Cuota #5 queda en estado "parcial" (faltan $13.900 de capital).
```

## Estados Opción B v1.1 (rangos DPD acortados)

| dpd | Estado canónico (Opción B) | Sub-bucket |
|---|---|---|
| 0 | `al_dia` | Current |
| 1-7 | `mora_leve` | Grace |
| 8-14 | `mora_media` | Warning |
| 15-21 | `mora_grave` | Alert |
| 22-30 | `mora_grave` | Critical |
| 31-45 | `mora_grave` | Severe |
| 46-49 | `default` | Pre-default |
| 50+ | `castigado` | Default |

Estados terminales (`saldado`, `castigado`, `reestructurado`) NO se sobrescriben automáticamente por DPD — son transiciones manuales o de estado especial.

## Invariantes del motor (probados con tests)

1. `monto_capital + monto_interes = monto` en cada cuota (tolerancia ±1 peso por redondeo).
2. `Σ monto_capital de cuotas regulares ≈ capital_plan` (la última cuota absorbe redondeo).
3. `valor_total = Σ monto de TODAS las cuotas` (incluye cuota 0 si existe).
4. `saldo_pendiente = valor_total − total_pagado`.
5. `saldo_pendiente >= 0` siempre.
6. `dpd >= 0` siempre.
7. Pago futuro (`fecha_pago > today_bogota()`) → `ValueError` (regla R-07).
8. Pago a LB en `pendiente_entrega` → rechazo.
9. Pago a LB en estado terminal (`saldado`, `castigado`) → rechazo.
10. `derivar_estado(derivar_estado(lb)) == derivar_estado(lb)` — idempotente.

## Tests del motor (37 verdes al 4-may-2026)

Ubicación: `backend/tests/test_motor.py`

- `TestCrearCronograma` (8 tests) — cronograma con/sin cuota_inicial, modalidades, P1S contado.
- `TestAplicarPago` (8 tests) — waterfall §4.1, fechas futuras rechazadas, estados terminales.
- `TestDerivarEstado` (9 tests) — saldo, DPD, sub_bucket, idempotencia, rangos v1.1.
- `TestAuditar` (3 tests) — detección de divergencias verde/amarilla/roja.
- `TestInvariantes` (4 tests) — capital+interés=monto, saldo no negativo, etc.
- `TestCuotaInicial` (5 tests, RODDOS V2.1) — cuota 0, sin waterfall, valor_total con cuota inicial, DPD ignora cuota 0.

## Lo que el motor NO hace

- **No persiste en MongoDB.** Es 100% pura. El caller debe persistir el resultado.
- **No publica eventos al bus.** Eso lo hacen los routers/handlers.
- **No genera journals en Alegra.** Solo emite el `distribucion` con desglose ANZI/mora/interés/capital — el Contador es quien hace el journal con esos campos (otro chat).
- **No regenera cronograma de LBs existentes.** El cronograma es inmutable después de creado salvo migración explícita.

## LB-30 Luis Romero — caso de regeneración estructural (Bloque 3)

**Síntoma:** auditor lo marcaba como roja con divergencia estructural en `valor_total`
(BD=$9.464.000 vs motor=$7.098.000).

**Diagnóstico raíz:** el LB se creó con metadata top-level coherente con un plan
P52S (52 cuotas × 182.000 = 9.464.000 = monto_original ✓ matches Loan Tape RDX),
pero el `cuotas[]` array sólo tenía 39 entradas, sin desglose `monto_capital` ni
`monto_interes`. El plan_codigo en BD decía `P39S` por error de captura.

**Verificación contractual:** Andrés confirmó verbalmente — el plan correcto es **P52S**.
La fila Loan Tape RDX del Excel oficial es la fuente de verdad numérica.

**Solución:** endpoint `POST /api/loanbook-admin/regenerar-cronograma-lb`
generó cronograma canónico via `motor.crear_cronograma(...)` con:
```
fecha_primer_pago = 2026-04-29  (miércoles, según cronograma actual)
num_cuotas        = 52
cuota_periodica   = 182.000
modalidad         = semanal
capital_plan      = 5.750.000   (TVS Sport 100, canónico CLAUDE.md)
cuota_inicial     = 0
```

Resultado: 52 cuotas con desglose canónico (capital ~110.577 + interés ~71.423 c/u),
Σ capital = 5.750.000 ✓, valor_total = 9.464.000 ✓. Sin pagos previos a preservar
(`total_pagado=0` en BD).

El endpoint:
- Soporta `dry_run`
- Preserva `monto_pagado` por número de cuota si los hubiera (no aplicó aquí)
- Aborta si detecta pagos huérfanos (cuotas pagadas que no caben en el nuevo cronograma)
- NO recalcula derivados — eso lo hace `/motor/migrar` en una pasada posterior

## Endpoints canónicos (DAY3 B4)

| Endpoint | Función | Motor |
|---|---|---|
| `PUT /api/loanbook/{id}/entrega` | Activación crédito + cronograma | `motor.crear_cronograma` |
| `PUT /api/loanbook/{id}/pago` | Pago de cuota regular (waterfall §4.1) | `motor.aplicar_pago` |
| `PUT /api/loanbook/{id}/pago/inicial` | **Nuevo.** Pago cuota 0 (sin waterfall) | `motor.aplicar_pago` cuota_numero=0 |

Endpoints DEPRECATED pero funcionales:
- `POST /api/loanbook/{id}/registrar-pago` → migrar a `PUT /pago`
- `POST /api/loanbook/{id}/registrar-pago-inicial` → migrar a `PUT /pago/inicial`

Cuando un PUT /pago se ejecuta, el motor:
1. Valida `fecha_pago` no futura (ValueError R-07)
2. Aplica waterfall ANZI 2% → mora → interés → capital → abono anticipado
3. Si `cuota_numero=0` → bypass waterfall (cuota inicial RODDOS V2.1)
4. Recalcula derivados (saldo, dpd, estado, sub_bucket) automáticamente
5. Persiste loanbook completo en BD
6. Emite evento `pago.cuota.canonico` o `pago.cuota.inicial.canonico`

## Próximos pasos del refactor

- B5: Cadena Mercately → OCR → match → `motor.aplicar_pago` end-to-end.
- B6: Frontend ajustes mínimos (cuota 0 visible en detalle de LB).
- B2.8 (bug menor): excluir cuota 0 del conteo `cuotas_vencidas` en `derivar_estado`
  (hoy cuenta cuota 0 vencida aunque el DPD ya la ignora).

## Historial

- **2026-04-30** Día 0 — Investigación profunda y diseño del dominio aprobado.
- **2026-05-01** Día 1 — Motor canónico v1 con 32 tests. Endpoints admin/motor.
- **2026-05-02** Día 2 — Restauración desde Excel oficial. Cartera $384.9M.
- **2026-05-03** — Auditor con tolerancia 1%. 1 roja real (LB-30) pendiente.
- **2026-05-04** Día 3 B1 — Cuota inicial como cuota 0 (RODDOS V2.1). 37 tests verdes.
- **2026-05-04** Día 3 B2 — Patches `valor_total = monto + cuota_inicial` aplicados a 11 LBs (+$15.15M).
- **2026-05-04** Día 3 B2.7 — `/motor/migrar` recalcula derivados: 42 verdes / 0 amarillas / 1 roja.
- **2026-05-04** Día 3 B3 — LB-30 cronograma regenerado P52S. Cartera limpia.
- **2026-05-04** Día 3 B4 — PUT /pago, /entrega, /pago/inicial usan motor canónico. Endpoints viejos deprecated.
- **2026-05-04** Día 3 B4.5 — `motor.calcular_proxima_cuota` + UI roja si vencida. 6 tests.
- **2026-05-04** Día 3 B5 — `marcar-cuotas-iniciales-pagadas` aplicado a 34 LBs (Σ=$47.83M). Cartera 43 verdes / 0 rojas.
