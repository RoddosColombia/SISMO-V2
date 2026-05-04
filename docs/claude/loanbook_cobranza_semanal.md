# Cobranza Semanal — Superapp operativa para Liz e Iván

**Ruta:** `/cartera/cobranza-semanal`
**Endpoint backend:** `GET /api/loanbook/cobranza-semanal`
**Estado al 4 de mayo de 2026:** desplegado, motor canónico v1.

## Propósito

Página única que reemplaza el flujo manual del equipo de cobranza. Cada
mañana, Liz e Iván abren esta página y ven exactamente:

1. **Cuánto deben recaudar esta semana** (objetivo)
2. **Cuánto llevan recaudado hoy y los últimos 7 días**
3. **% de avance vs el objetivo**
4. **Lista chequeable** de los clientes que deben pagar entre hoy y +7 días
5. **Lista de morosos** ordenada por DPD (mayor a menor) para llamadas urgentes

Cada item se puede marcar como pagado con un click → abre modal con
monto/método/fecha/referencia → llama `PUT /pago` (motor canónico) → la
lista se refresca optimísticamente.

## Endpoint backend

`GET /api/loanbook/cobranza-semanal` retorna:

```json
{
  "fecha_corte":         "2026-05-04",
  "ventana_dias":        7,
  "ventana_desde":       "2026-05-04",
  "ventana_hasta":       "2026-05-11",
  "semana_objetivo":     7560000,
  "recaudado_hoy":       450000,
  "recaudado_semana":    3200000,
  "porcentaje":          42.3,
  "clientes_por_pagar":  28,
  "clientes_en_mora":    4,
  "checklist": [
    {
      "loanbook_id":      "LB-2026-0008",
      "cliente_nombre":   "Kreyser Cabrices",
      "cliente_telefono": "+57300...",
      "cuota_numero":     8,
      "es_cuota_inicial": false,
      "monto":            210000,
      "monto_capital":    150000,
      "monto_interes":    60000,
      "fecha_vencimiento": "2026-05-05",
      "vencida":          false,
      "dias_diff":        1,
      "dpd":              0,
      "estado":           "al_dia",
      "saldo_pendiente":  6300000,
      "modelo":           "TVS Raider 125"
    },
    ...
  ],
  "en_mora": [...]
}
```

### Reglas canónicas del endpoint

- Excluye estados terminales (`saldado`, `castigado`).
- Excluye `pendiente_entrega` del cobro semanal (la moto aún no se entregó,
  no hay cuota cobrar).
- **Cuota 0** (cuota inicial) entra al checklist sólo si está pendiente.
  Política RODDOS V2.1: la CI se cobra antes de la entrega. El endpoint
  marca `es_cuota_inicial=true` para que el frontend muestre etiqueta especial.
- **Vencida**: una cuota se marca vencida si `fecha < today_bogota()`. La
  fila aparece con borde rojo y prefijo "Atrasada".
- **DPD canónico** del motor (excluye cuota 0 del cálculo).

## Acción de pago (PUT canónico)

Cuando el operador marca el checkbox y confirma el modal:

- Si la cuota es regular (numero ≥ 1):
  ```
  PUT /api/loanbook/{id}/pago
  {
    "monto_pago":   <número>,
    "metodo_pago":  "transferencia" | "wava" | "efectivo" | "otro",
    "fecha_pago":   "yyyy-MM-dd",
    "referencia":   "<texto>",
    "cuota_numero": <número>
  }
  ```

- Si la cuota es inicial (numero = 0):
  ```
  PUT /api/loanbook/{id}/pago/inicial
  {
    "monto_pago":   <número>,
    "metodo_pago":  "transferencia" | "wava" | "efectivo" | "otro",
    "fecha_pago":   "yyyy-MM-dd",
    "referencia":   "<texto>"
  }
  ```

Ambos endpoints usan `motor.aplicar_pago` y emiten eventos al bus
(`pago.cuota.canonico` o `pago.cuota.inicial.canonico`) para que el
Contador genere journals en Alegra automáticamente.

## Tests

`backend/tests/test_cobranza_semanal.py` cubre:

- `test_checklist_solo_incluye_cuotas_en_ventana_7d`
- `test_en_mora_solo_dpd_positivo`
- `test_saldados_y_castigados_se_excluyen`
- `test_recaudado_hoy_suma_solo_pagos_de_hoy`
- `test_semana_objetivo_suma_montos_proximas_cuotas`
- `test_cuota_inicial_pendiente_aparece_en_checklist`

## Pendientes futuros

- Subida de comprobantes (foto/PDF) asociado al pago — pendiente B6.4.
- Integración con Mercately para que al detectar comprobante WhatsApp
  marque el pago automáticamente (Bloque 7).
- Botón "Recordatorio WhatsApp" en cada item para que el equipo envíe
  template de cobro pre-cargado.
