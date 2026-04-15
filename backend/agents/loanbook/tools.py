"""
Agente Loanbook — 11 herramientas para gestion de creditos de motos.

4 write tools (require ExecutionCard confirmation):
  - registrar_apartado, registrar_pago_parcial, registrar_entrega, registrar_pago_cuota

7 read-only tools (execute immediately):
  - consultar_loanbook, listar_loanbooks, consultar_mora, calcular_liquidacion,
    consultar_inventario, consultar_cliente, resumen_cartera
"""

# ---------------------------------------------------------------------------
# READ-ONLY TOOLS (7)
# ---------------------------------------------------------------------------

_CONSULTAS: list[dict] = [
    {
        "name": "consultar_loanbook",
        "description": (
            "Busca un credito por VIN o nombre del cliente. "
            "Retorna detalle completo: estado, cuotas pagadas/pendientes, DPD, "
            "saldo capital, proxima cuota, cronograma."
        ),
        "input_schema": {
            "type": "object",
            "required": ["busqueda"],
            "properties": {
                "busqueda": {
                    "type": "string",
                    "description": "VIN de la moto o nombre del cliente (busqueda parcial)",
                },
            },
        },
    },
    {
        "name": "listar_loanbooks",
        "description": (
            "Lista todos los creditos activos con resumen. "
            "Opcionalmente filtra por estado (activo, al_dia, en_riesgo, mora, etc)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "estado": {
                    "type": "string",
                    "description": "Filtrar por estado: pendiente_entrega, activo, al_dia, en_riesgo, mora, mora_grave, saldado, castigado",
                },
            },
        },
    },
    {
        "name": "consultar_mora",
        "description": (
            "Consulta mora de un credito especifico (por VIN) o resumen general de mora "
            "de toda la cartera. Incluye DPD, monto mora acumulada, cuotas vencidas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vin": {
                    "type": "string",
                    "description": "VIN de la moto. Si se omite, retorna resumen de mora de toda la cartera.",
                },
            },
        },
    },
    {
        "name": "calcular_liquidacion",
        "description": (
            "Calcula el monto total para liquidar (pagar completamente) un credito hoy. "
            "Incluye: saldo capital + mora acumulada + cuotas vencidas. "
            "NO ejecuta — solo calcula y muestra."
        ),
        "input_schema": {
            "type": "object",
            "required": ["vin"],
            "properties": {
                "vin": {
                    "type": "string",
                    "description": "VIN de la moto cuyo credito se quiere liquidar",
                },
            },
        },
    },
    {
        "name": "consultar_inventario",
        "description": (
            "Consulta motos disponibles en inventario. "
            "Opcionalmente filtra por modelo. Solo muestra motos con estado 'disponible'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "modelo": {
                    "type": "string",
                    "description": "Filtrar por modelo de moto (ej: 'Sport 100', 'Raider 125')",
                },
            },
        },
    },
    {
        "name": "consultar_cliente",
        "description": (
            "Busca un cliente en el CRM por cedula o nombre. "
            "Retorna datos de contacto, loanbooks asociados, estado."
        ),
        "input_schema": {
            "type": "object",
            "required": ["busqueda"],
            "properties": {
                "busqueda": {
                    "type": "string",
                    "description": "Cedula o nombre del cliente (busqueda parcial)",
                },
            },
        },
    },
    {
        "name": "resumen_cartera",
        "description": (
            "Resumen ejecutivo de la cartera de creditos: total creditos, activos, "
            "cartera total en pesos, recaudo semanal esperado, creditos en mora, "
            "distribucion por estado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

# ---------------------------------------------------------------------------
# WRITE TOOLS (4) — require ExecutionCard confirmation
# ---------------------------------------------------------------------------

_ESCRITURA: list[dict] = [
    {
        "name": "registrar_apartado",
        "description": (
            "Aparta una moto para un cliente — crea el loanbook en estado pendiente_entrega "
            "y marca la moto como apartada. Verifica que la moto este disponible. "
            "Publica evento apartado.completo al bus."
        ),
        "input_schema": {
            "type": "object",
            "required": ["vin", "cliente", "plan_codigo", "modelo", "modalidad", "fecha_entrega"],
            "properties": {
                "vin": {"type": "string", "description": "VIN de la moto a apartar"},
                "cliente": {
                    "type": "object",
                    "description": "Datos del cliente",
                    "required": ["nombre", "cedula", "telefono"],
                    "properties": {
                        "nombre": {"type": "string"},
                        "cedula": {"type": "string"},
                        "telefono": {"type": "string", "description": "Formato 57 + 10 digitos"},
                    },
                },
                "plan_codigo": {"type": "string", "description": "Codigo del plan (ej: P52S)"},
                "modelo": {"type": "string", "description": "Modelo de moto (debe existir en el plan)"},
                "modalidad": {
                    "type": "string",
                    "enum": ["semanal", "quincenal", "mensual"],
                    "description": "Modalidad de pago",
                },
                "fecha_entrega": {"type": "string", "description": "Fecha entrega yyyy-MM-dd"},
                "fecha_primer_pago": {
                    "type": "string",
                    "description": "Fecha primer pago yyyy-MM-dd (obligatorio para quincenal/mensual, debe ser miercoles)",
                },
            },
        },
    },
    {
        "name": "registrar_pago_parcial",
        "description": (
            "Registra un pago parcial del apartado de una moto. "
            "Suma al total pagado del apartado."
        ),
        "input_schema": {
            "type": "object",
            "required": ["vin", "monto", "referencia"],
            "properties": {
                "vin": {"type": "string", "description": "VIN de la moto apartada"},
                "monto": {"type": "number", "description": "Monto del pago parcial en COP"},
                "referencia": {"type": "string", "description": "Referencia de la transaccion (recibo, transferencia)"},
            },
        },
    },
    {
        "name": "registrar_entrega",
        "description": (
            "Registra la entrega fisica de la moto. Activa el loanbook: "
            "calcula cronograma con Regla del Miercoles, transiciona pendiente_entrega → activo, "
            "marca moto como vendida. Publica evento entrega.realizada."
        ),
        "input_schema": {
            "type": "object",
            "required": ["vin", "fecha_entrega"],
            "properties": {
                "vin": {"type": "string", "description": "VIN de la moto a entregar"},
                "fecha_entrega": {"type": "string", "description": "Fecha de entrega real yyyy-MM-dd"},
                "fecha_primer_pago": {
                    "type": "string",
                    "description": "Fecha primer pago yyyy-MM-dd (solo quincenal/mensual, debe ser miercoles)",
                },
            },
        },
    },
    {
        "name": "registrar_pago_cuota",
        "description": (
            "Registra pago de cuota de un credito. Aplica waterfall: "
            "ANZI% → mora → vencidas → corriente → abono capital. "
            "Publica evento cuota.pagada al bus."
        ),
        "input_schema": {
            "type": "object",
            "required": ["vin", "monto", "fecha_pago", "banco"],
            "properties": {
                "vin": {"type": "string", "description": "VIN de la moto del credito"},
                "monto": {"type": "number", "description": "Monto del pago en COP"},
                "fecha_pago": {"type": "string", "description": "Fecha del pago yyyy-MM-dd"},
                "banco": {
                    "type": "string",
                    "description": "Banco donde se recibio el pago. ID Alegra: 5314=Bancolombia2029, 5315=Bancolombia2540, 5318=BBVA0210, 5319=BBVA0212, 5322=Davivienda482, 5321=BancoBogota, 5536=Global66",
                },
            },
        },
    },
]

LOANBOOK_TOOLS: list[dict] = _CONSULTAS + _ESCRITURA
