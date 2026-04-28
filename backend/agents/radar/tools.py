"""
Agente RADAR — Tools de cobranza WhatsApp + gestion remota.

5 tools que el LLM puede invocar desde el chat para:
- Generar cola de cobranza priorizada por DPD x score
- Registrar gestion telefonica/WhatsApp
- Registrar promesa de pago (PTP)
- Enviar WhatsApp (template T1-T5)
- Consultar estado de cliente para decision de cobranza

R-MERCATELY: GET /customers/{phone} SIEMPRE antes de POST.
LEY 2300/2023: max 1 contacto por dia, L-V 7AM-7PM, Sab 8AM-3PM.
NUNCA visitas en campo — cobranza 100% remota.

Sprint S2 (Ejecucion 2) — RADAR + Mercately bidireccional.
"""

RADAR_TOOLS: list[dict] = [
    {
        "name": "generar_cola_cobranza",
        "description": (
            "Genera la cola de cobranza priorizada por DPD x score historico. "
            "Read-only. Usa loanbook (DPD, monto vencido) + crm_clientes (score, "
            "gestiones recientes). Excluye clientes contactados hoy (Ley 2300). "
            "Retorna lista ordenada con: cedula, nombre, dpd, monto_mora, "
            "score, telefono, ultima_gestion, template_sugerido (T1-T5)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dpd_min": {"type": "integer", "description": "DPD minimo para incluir (default 0 = todos en mora)"},
                "limite":  {"type": "integer", "description": "Max items en cola (default 50)"},
                "modalidad_cobro": {
                    "type": "string",
                    "enum": ["miercoles", "martes_recordatorio", "jueves_mora", "ad_hoc"],
                    "description": "Tipo de jornada de cobro. Default 'miercoles' (cobro semanal)."
                },
            },
        },
    },
    {
        "name": "registrar_gestion",
        "description": (
            "Registra una gestion de cobranza (llamada, WhatsApp manual, nota). "
            "Append a crm_clientes.gestiones[] con tipo, resultado, observacion. "
            "Tipos validos: 'llamada_contesta', 'llamada_no_contesta', "
            "'whatsapp_manual', 'mensaje_voz', 'cliente_inubicable', 'nota'."
        ),
        "input_schema": {
            "type": "object",
            "required": ["cedula", "tipo", "resultado"],
            "properties": {
                "cedula":      {"type": "string"},
                "tipo":        {"type": "string", "enum": [
                    "llamada_contesta", "llamada_no_contesta", "whatsapp_manual",
                    "mensaje_voz", "cliente_inubicable", "nota"
                ]},
                "resultado":   {"type": "string", "description": "Resumen: 'va a pagar', 'no responde', 'pidio plazo', etc."},
                "observacion": {"type": "string", "description": "Detalle adicional (max 500 chars)"},
                "vin":         {"type": "string", "description": "VIN del credito (opcional, asocia a un loanbook especifico)"},
            },
        },
    },
    {
        "name": "registrar_promesa_pago",
        "description": (
            "Registra una promesa de pago (PTP) que el cliente hizo. "
            "Crea documento en crm_clientes.promesas_pago[] con fecha y monto. "
            "Si la fecha es < hoy, error. Genera evento crm.ptp.creada para que "
            "el scheduler agende seguimiento al dia siguiente de la fecha pactada."
        ),
        "input_schema": {
            "type": "object",
            "required": ["cedula", "fecha_pactada", "monto_pactado"],
            "properties": {
                "cedula":         {"type": "string"},
                "fecha_pactada":  {"type": "string", "description": "yyyy-MM-dd (debe ser >= hoy)"},
                "monto_pactado":  {"type": "number", "description": "COP que el cliente promete pagar"},
                "vin":            {"type": "string"},
                "canal":          {"type": "string", "enum": ["whatsapp", "telefono", "presencial"], "description": "Canal donde se hizo la promesa"},
                "nota":           {"type": "string"},
            },
        },
    },
    {
        "name": "enviar_whatsapp_template",
        "description": (
            "Envia mensaje WhatsApp via template Mercately. Templates aprobados "
            "T1-T5 segun nivel de friccion: T1=recordatorio amable (-2d), "
            "T2=recordatorio cobro hoy, T3=mora <3d, T4=mora 7-15d, "
            "T5=ultimo aviso pre-juridico (>30d). "
            "R-MERCATELY: verifica customer antes de enviar (idempotencia). "
            "Ley 2300: max 1 envio por cliente por dia."
        ),
        "input_schema": {
            "type": "object",
            "required": ["cedula", "template"],
            "properties": {
                "cedula":   {"type": "string"},
                "template": {
                    "type": "string",
                    "enum": ["T1", "T2", "T3", "T4", "T5"],
                    "description": "Codigo del template aprobado en Mercately"
                },
                "vin":      {"type": "string", "description": "Si aplica, especifica el credito"},
                "params_extra": {
                    "type": "object",
                    "description": "Parametros opcionales del template (monto, fecha, etc.)"
                },
            },
        },
    },
    {
        "name": "consultar_estado_cliente",
        "description": (
            "Consulta estado completo de un cliente para decidir cobranza: "
            "loanbook (DPD, cuotas pendientes, monto mora), CRM (gestiones recientes, "
            "promesas de pago, score, tags), e info Mercately (ultima respuesta, "
            "ventana 24h activa). Read-only."
        ),
        "input_schema": {
            "type": "object",
            "required": ["cedula"],
            "properties": {
                "cedula": {"type": "string"},
                "vin":    {"type": "string", "description": "Opcional, filtra por credito especifico"},
            },
        },
    },
]
