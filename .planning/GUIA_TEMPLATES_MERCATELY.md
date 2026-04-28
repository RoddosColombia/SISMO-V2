# Guía Templates Mercately — RODDOS S.A.S.

**Para:** persona encargada de configurar Mercately
**De:** equipo SISMO V2
**Fecha:** 28-abril-2026
**Objetivo:** crear y aprobar 5 templates de WhatsApp Business para automatización de cobranza + 3 templates internos para alertas al equipo

---

## ¿Para qué son?

SISMO V2 envía mensajes automáticos a clientes de RODDOS los **martes 9 AM** (recordatorio cuota mañana), **miércoles 8 AM** (cobro hoy) y **jueves 10 AM** (mora). Cada nivel de fricción usa un template diferente (T1–T5).

Adicionalmente, SISMO necesita 3 templates **internos** para mandar alertas al equipo (Andrés, Iván, Fabián) sobre eventos del backoffice.

WhatsApp Business solo permite envío fuera de la ventana de 24 h con templates **pre-aprobados**. Por eso necesitamos crearlos y enviarlos a aprobación antes de que el sistema pueda usarlos.

---

## Configuración general en Mercately

Para los 8 templates (5 cobranza + 3 internos):

| Campo | Valor |
|---|---|
| Idioma | **Español (Colombia)** — código `es_CO` |
| Categoría | **UTILITY** (transaccional). NO usar `MARKETING` — WhatsApp suele rechazar templates de cobranza como marketing |
| Tipo | **Texto plano** (sin botones, sin media, por ahora) |
| Caracteres máximos | 1024 por mensaje (incluye parámetros expandidos) |
| Variables | 3 fijas por template: `{{1}}`, `{{2}}`, `{{3}}` |

### Buenas prácticas de aprobación WhatsApp

1. NO usar lenguaje agresivo o amenazante ("vas a perder tu moto", "te demandaremos") — Meta rechaza.
2. NO usar emojis excesivos (1-2 máximo, ninguno en el primer envío).
3. NO usar todas las palabras en MAYÚSCULAS.
4. Mantener tono **profesional y cordial**, mencionar a RODDOS por nombre.
5. Respetar Ley 2300/2023 colombiana (la lógica de horarios la aplica SISMO automáticamente, pero el TEXTO no debe presionar).
6. Cada variable debe tener un **ejemplo válido** durante el registro (Mercately lo pide).

---

## Templates de cobranza al cliente (5)

### T1 — Recordatorio amable (-1 día)

**Cuándo se envía:** martes 9:00 AM Bogotá, a clientes con cuota miércoles.
**Variable de entorno SISMO:** `MERCATELY_TEMPLATE_T1_RECORDATORIO_ID`

**Texto:**
```
Hola {{1}}, te recordamos que mañana {{3}} se te vence la cuota de {{2}} de tu crédito con RODDOS. Puedes pagar por Bancolombia, BBVA o Davivienda. Cualquier inconveniente avísanos por aquí. ¡Gracias!
```

**Variables:**
- `{{1}}` = primer nombre del cliente. Ejemplo: `Juan`
- `{{2}}` = monto formato COP. Ejemplo: `$150.000`
- `{{3}}` = fecha en español formato día-mes corto. Ejemplo: `30 abr`

**Mensaje renderizado de ejemplo:**
> Hola Juan, te recordamos que mañana 30 abr se te vence la cuota de $150.000 de tu crédito con RODDOS. Puedes pagar por Bancolombia, BBVA o Davivienda. Cualquier inconveniente avísanos por aquí. ¡Gracias!

---

### T2 — Cobro día de pago

**Cuándo se envía:** miércoles 8:00 AM Bogotá, a clientes con cuota hoy.
**Variable de entorno SISMO:** `MERCATELY_TEMPLATE_T2_COBRO_HOY_ID`

**Texto:**
```
Buenos días {{1}}, hoy {{3}} es el día de pago de tu cuota de {{2}} con RODDOS. Bancolombia, BBVA, Davivienda, Nequi o Daviplata. Cuando pagues envíanos el comprobante por aquí, por favor. ¡Gracias!
```

**Variables:**
- `{{1}}` = primer nombre. Ejemplo: `Juan`
- `{{2}}` = monto. Ejemplo: `$150.000`
- `{{3}}` = fecha hoy. Ejemplo: `30 abr`

**Ejemplo:**
> Buenos días Juan, hoy 30 abr es el día de pago de tu cuota de $150.000 con RODDOS. Bancolombia, BBVA, Davivienda, Nequi o Daviplata. Cuando pagues envíanos el comprobante por aquí, por favor. ¡Gracias!

---

### T3 — Mora corta (1-6 días)

**Cuándo se envía:** jueves 10:00 AM Bogotá, a clientes con DPD entre 1 y 6 días.
**Variable de entorno SISMO:** `MERCATELY_TEMPLATE_T3_MORA_CORTA_ID`

**Texto:**
```
Hola {{1}}, tu cuota se venció hace {{2}} días. La mora acumulada es {{3}}. Si pagas hoy te ayudamos a ponerte al día sin afectar tu historial. Estamos atentos por aquí.
```

**Variables:**
- `{{1}}` = primer nombre. Ejemplo: `Juan`
- `{{2}}` = días en mora (DPD) como número. Ejemplo: `3`
- `{{3}}` = mora acumulada COP. Ejemplo: `$4.000`

**Ejemplo:**
> Hola Juan, tu cuota se venció hace 3 días. La mora acumulada es $4.000. Si pagas hoy te ayudamos a ponerte al día sin afectar tu historial. Estamos atentos por aquí.

---

### T4 — Mora media (7-29 días)

**Cuándo se envía:** jueves 10:00 AM Bogotá, a clientes con DPD entre 7 y 29 días.
**Variable de entorno SISMO:** `MERCATELY_TEMPLATE_T4_MORA_MEDIA_ID`

**Texto:**
```
{{1}}, tu crédito con RODDOS está en mora. Llevas {{2}} días vencido y la mora acumulada es {{3}}. Necesitamos llegar a un acuerdo de pago. Llámanos al 320-XXX-XXXX o respóndenos por aquí.
```

**Variables:**
- `{{1}}` = primer nombre. Ejemplo: `Juan`
- `{{2}}` = DPD. Ejemplo: `15`
- `{{3}}` = mora acumulada. Ejemplo: `$28.000`

**Ejemplo:**
> Juan, tu crédito con RODDOS está en mora. Llevas 15 días vencido y la mora acumulada es $28.000. Necesitamos llegar a un acuerdo de pago. Llámanos al 320-XXX-XXXX o respóndenos por aquí.

> **Nota:** reemplazar `320-XXX-XXXX` por el teléfono real de cobranza interna de RODDOS.

---

### T5 — Último aviso pre-jurídico (≥30 días)

**Cuándo se envía:** jueves 10:00 AM Bogotá, a clientes con DPD ≥ 30 días.
**Variable de entorno SISMO:** `MERCATELY_TEMPLATE_T5_ULTIMO_AVISO_ID`

**Texto:**
```
{{1}}, este es el último aviso amistoso antes de remitir tu caso a cobro jurídico. Llevas {{2}} días en mora y la deuda total con intereses es {{3}}. Aún puedes acordar un plan de pago contactándonos hoy. Te llamaremos en las próximas horas.
```

**Variables:**
- `{{1}}` = primer nombre. Ejemplo: `Juan`
- `{{2}}` = DPD. Ejemplo: `45`
- `{{3}}` = mora total. Ejemplo: `$90.000`

**Ejemplo:**
> Juan, este es el último aviso amistoso antes de remitir tu caso a cobro jurídico. Llevas 45 días en mora y la deuda total con intereses es $90.000. Aún puedes acordar un plan de pago contactándonos hoy. Te llamaremos en las próximas horas.

> **⚠️ Importante:** este template puede ser rechazado por WhatsApp si interpreta "cobro jurídico" como amenaza. Si lo rechazan, reemplazar la frase por: *"este es nuestro último intento de contactarte por este canal antes de iniciar gestiones formales"*.

---

## Templates internos para el equipo RODDOS (3)

Estos los usa SISMO para **alertarte a ti** (Andrés, Iván, Fabián) cuando algo importante pasa: gasto grande de socio, vencimiento tributario en 3 días, errores del sistema, etc.

Cada uno tiene **1 sola variable**: el mensaje que SISMO arma dinámicamente.

### T-INT-1 — Información operativa

**Variable de entorno SISMO:** `MERCATELY_TEMPLATE_INTERNO_INFO_ID`

**Texto:**
```
SISMO RODDOS — info: {{1}}
```

**Variables:**
- `{{1}}` = mensaje libre (max ~1000 caracteres). Ejemplo: `Pago recibido $1.200.000 de Juan Pérez VIN ABC123`

**Ejemplo:**
> SISMO RODDOS — info: Pago recibido $1.200.000 de Juan Pérez VIN ABC123

---

### T-INT-2 — Alerta (requiere atención)

**Variable de entorno SISMO:** `MERCATELY_TEMPLATE_INTERNO_ALERTA_ID`

**Texto:**
```
⚠️ SISMO RODDOS — alerta: {{1}}
```

**Variables:**
- `{{1}}` = motivo de la alerta. Ejemplo: `ReteFuente vence en 3 días, valor estimado $4.500.000`

**Ejemplo:**
> ⚠️ SISMO RODDOS — alerta: ReteFuente vence en 3 días, valor estimado $4.500.000

---

### T-INT-3 — Tarea pendiente

**Variable de entorno SISMO:** `MERCATELY_TEMPLATE_INTERNO_TASK_ID`

**Texto:**
```
✅ SISMO RODDOS — tarea: {{1}}
```

**Variables:**
- `{{1}}` = descripción de la tarea. Ejemplo: `Revisar factura Auteco FV-12345 con motor faltante en VIN MD2A4CY...`

**Ejemplo:**
> ✅ SISMO RODDOS — tarea: Revisar factura Auteco FV-12345 con motor faltante en VIN MD2A4CY...

---

## Webhook entrante — clientes que respondan WhatsApp

Cuando SISMO envíe un T1–T5 y el cliente responda, esa respuesta tiene que llegar de vuelta a SISMO para que aparezca en el CRM y RADAR pueda decidir el siguiente paso.

### Configurar en Mercately dashboard

1. Ir a **Configuración → Webhooks** (o **Integraciones → Webhooks**, según versión).
2. Agregar nuevo webhook:
   - **URL:** `https://sismo.roddos.com/api/webhooks/mercately/inbound`
   - **Método:** POST
   - **Eventos:** `incoming_message` (mensajes entrantes de clientes)
   - **Secret / Signing key:** generar una cadena aleatoria de 64 caracteres y guardarla en este lugar Y en Render como `MERCATELY_WEBHOOK_SECRET`. (Genera el valor en https://www.random.org/strings/ o con `openssl rand -hex 32`).
   - **Header de firma esperado:** `X-Mercately-Signature` (formato `sha256=<hex>`)
3. Guardar y probar enviando un mensaje desde tu propio número al chatbot RODDOS.

### Verificar que el endpoint está vivo

```
GET https://sismo.roddos.com/api/webhooks/mercately/health

Respuesta esperada:
{"ok":"true","service":"sismo.roddos.com","endpoint":"mercately-inbound-webhook"}
```

---

## Resumen de configuración

Después de aprobar los 8 templates en Mercately, copia los UUIDs (Mercately los llama `template_id` o `internal_id`) y entrégaselos al equipo SISMO para que los pongan en Render. Las variables de entorno son:

```bash
# Cobranza al cliente
MERCATELY_TEMPLATE_T1_RECORDATORIO_ID=<uuid del T1>
MERCATELY_TEMPLATE_T2_COBRO_HOY_ID=<uuid del T2>
MERCATELY_TEMPLATE_T3_MORA_CORTA_ID=<uuid del T3>
MERCATELY_TEMPLATE_T4_MORA_MEDIA_ID=<uuid del T4>
MERCATELY_TEMPLATE_T5_ULTIMO_AVISO_ID=<uuid del T5>

# Internos al equipo
MERCATELY_TEMPLATE_INTERNO_INFO_ID=<uuid del T-INT-1>
MERCATELY_TEMPLATE_INTERNO_ALERTA_ID=<uuid del T-INT-2>
MERCATELY_TEMPLATE_INTERNO_TASK_ID=<uuid del T-INT-3>

# Webhook
MERCATELY_WEBHOOK_SECRET=<cadena aleatoria 64 chars, igual que en Mercately dashboard>
```

---

## Tabla resumen — checklist para crear

| # | Código | Nombre Mercately sugerido | 3 vars | Categoría | Aprobación esperada |
|---|---|---|---|---|---|
| 1 | T1 | `roddos_recordatorio_cuota` | nombre, monto, fecha | UTILITY | 1-2 días |
| 2 | T2 | `roddos_cobro_hoy` | nombre, monto, fecha | UTILITY | 1-2 días |
| 3 | T3 | `roddos_mora_corta` | nombre, dpd, mora | UTILITY | 1-2 días |
| 4 | T4 | `roddos_mora_media` | nombre, dpd, mora | UTILITY | 2-3 días |
| 5 | T5 | `roddos_ultimo_aviso` | nombre, dpd, mora | UTILITY | 2-5 días (riesgo rechazo, ver nota) |
| 6 | T-INT-1 | `sismo_info_interno` | mensaje | UTILITY | 1 día |
| 7 | T-INT-2 | `sismo_alerta_interno` | mensaje | UTILITY | 1 día |
| 8 | T-INT-3 | `sismo_tarea_interno` | mensaje | UTILITY | 1 día |

---

## Si algún template es rechazado

WhatsApp puede rechazar especialmente T4 y T5 por considerarlos "presión cobranza". Si pasa:

1. **No insistir con el mismo texto** — Meta lo banea permanentemente.
2. Suavizar el lenguaje:
   - Quitar "cobro jurídico", "demanda", "reportar a centrales"
   - Reemplazar por "gestiones formales", "seguimiento adicional"
3. Volver a enviar como si fuera template nuevo.

Mientras tanto SISMO tiene **fallback automático** a los 2 templates legacy ya aprobados (`MERCATELY_TEMPLATE_COBRO_ID` y `MERCATELY_TEMPLATE_MORA_ID`), así que la operación no se detiene.

---

## Preguntas frecuentes

**¿Por qué 3 variables en T1-T5 si los textos son distintos?**
Para que SISMO pueda armar el payload con la misma estructura sin lógica condicional. T1/T2 → `(nombre, monto, fecha)`; T3/T4/T5 → `(nombre, dpd, mora)`. La posición es la misma, lo que cambia es el significado.

**¿Qué pasa con el horario? ¿WhatsApp envía a las 3 AM si SISMO falla?**
SISMO bloquea cualquier envío fuera de la ventana Ley 2300 (lun-vie 7AM-7PM, sáb 8AM-3PM, dom prohibido). Aunque el cron se dispare antes, no envía hasta que abra la ventana.

**¿Cuántos mensajes por cliente por día?**
**Máximo 1**, hardcoded en SISMO. Si el cliente ya recibió un T-X hoy, el sistema salta cualquier siguiente intento ese día (Ley 2300 cumple por código, no solo por política).

**¿Usamos el mismo número de WhatsApp para internos y clientes?**
Sí, mismo número Mercately. Los templates internos solo van a 3 teléfonos (Andrés, Iván, Fabián) y se distinguen del flujo de clientes solo por el destinatario.

**¿Qué hacemos si Mercately rechaza T5 después de varios intentos?**
Mantener solo T1-T4 y cuando un cliente llegue a DPD ≥30 días marcar manualmente el caso para gestión telefónica humana en lugar de WhatsApp. SISMO ya tiene la tool `registrar_gestion` para anotar la llamada.
