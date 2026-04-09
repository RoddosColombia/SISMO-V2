"""
Contador tool definitions for Anthropic Tool Use API.

All tools for the Agente Contador — 12 tools covering:
  - Core accounting: crear_causacion, registrar_gasto
  - Sales: crear_factura_venta
  - Collections: registrar_pago_cuota
  - Payroll: registrar_nomina
  - Partners: registrar_cxc_socio
  - Non-operating income: registrar_ingreso_no_operacional
  - Bank reconciliation: causar_movimiento_bancario
  - Read-only queries: consultar_saldo_cxc, consultar_plan_cuentas,
                       consultar_journals, consultar_facturas, consultar_cartera

Only Contador receives these tools — CFO, RADAR, Loanbook get empty lists (D-05).
NEVER reference /journal-entries — use /journals.
"""

CONTADOR_TOOLS: list[dict] = [
    {
        "name": "crear_causacion",
        "description": (
            "Crea un asiento contable de partida doble (causación) en Alegra para registrar "
            "un gasto, ingreso o cualquier movimiento contable. Siempre usar /journals — "
            "NUNCA usa endpoints que no sean /journals para asientos. "
            "Requiere entries con débitos = créditos."
        ),
        "input_schema": {
            "type": "object",
            "required": ["entries", "date", "observations"],
            "properties": {
                "entries": {
                    "type": "array",
                    "description": "Líneas del asiento. Suma débitos == suma créditos.",
                    "items": {
                        "type": "object",
                        "required": ["id", "debit", "credit"],
                        "properties": {
                            "id": {"type": "integer", "description": "ID Alegra de la cuenta"},
                            "debit": {"type": "number", "description": "Valor débito COP (0 si es crédito)"},
                            "credit": {"type": "number", "description": "Valor crédito COP (0 si es débito)"},
                        },
                    },
                },
                "date": {"type": "string", "description": "Fecha yyyy-MM-dd (NUNCA con timezone)"},
                "observations": {"type": "string", "description": "Descripción del asiento"},
            },
        },
    },
    {
        "name": "registrar_gasto",
        "description": (
            "Registra un gasto en lenguaje natural. El agente clasifica, calcula retenciones "
            "(ReteFuente + ReteICA) y llama crear_causacion. Usar cuando el usuario describe "
            "un pago o gasto. Auteco NIT 860024781 es autoretenedor — NUNCA aplicar ReteFuente."
        ),
        "input_schema": {
            "type": "object",
            "required": ["descripcion", "monto", "banco"],
            "properties": {
                "descripcion": {"type": "string", "description": "Descripción del gasto (ej: 'arriendo bodega enero')"},
                "monto": {"type": "number", "description": "Monto total del gasto en COP"},
                "banco": {"type": "string", "description": "Banco desde donde se pagó (Bancolombia, BBVA, Davivienda, etc.)"},
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd (opcional, default: hoy)"},
                "proveedor_nit": {"type": "string", "description": "NIT del proveedor si es conocido (ej: '860024781' para Auteco)"},
                "tipo_persona": {
                    "type": "string",
                    "enum": ["natural", "juridica"],
                    "description": "Natural o jurídica para honorarios (determina tasa ReteFuente)",
                },
            },
        },
    },
    {
        "name": "registrar_pago_cuota",
        "description": (
            "Registra un pago de cuota de cartera. Ejecuta DOS operaciones: "
            "POST /payments contra la factura de venta + POST /journals de ingreso financiero. "
            "La cuota solo se marca pagada si AMBAS operaciones son verificadas."
        ),
        "input_schema": {
            "type": "object",
            "required": ["loanbook_id", "monto", "banco", "numero_cuota"],
            "properties": {
                "loanbook_id": {"type": "string", "description": "ID del loanbook (ej: 'LB-0042')"},
                "monto": {"type": "number", "description": "Monto del pago en COP"},
                "banco": {"type": "string", "description": "Banco donde se recibió el pago"},
                "numero_cuota": {"type": "integer", "description": "Número de cuota"},
                "metodo_pago": {"type": "string", "description": "Nequi, transferencia, efectivo, etc."},
            },
        },
    },
    {
        "name": "registrar_nomina",
        "description": (
            "Registra la nómina mensual por empleado como journals individuales en Alegra. "
            "Cuenta Sueldos 510506 (ID 5462) + Seguridad Social (ID 5471). "
            "Anti-duplicados por mes + empleado."
        ),
        "input_schema": {
            "type": "object",
            "required": ["mes", "anio", "empleados"],
            "properties": {
                "mes": {"type": "integer", "description": "Mes (1-12)"},
                "anio": {"type": "integer", "description": "Año (ej: 2026)"},
                "empleados": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["nombre", "salario"],
                        "properties": {
                            "nombre": {"type": "string"},
                            "salario": {"type": "number", "description": "Salario en COP"},
                            "seguridad_social": {"type": "number", "description": "Aporte seguridad social COP (opcional)"},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "registrar_cxc_socio",
        "description": (
            "Registra un retiro o gasto personal de un socio como CXC (Cuentas por Cobrar a socios). "
            "NUNCA como gasto operativo. Socios: Andrés CC 80075452, Iván CC 80086601."
        ),
        "input_schema": {
            "type": "object",
            "required": ["socio_cedula", "monto", "banco", "descripcion"],
            "properties": {
                "socio_cedula": {"type": "string", "description": "CC del socio: 80075452 (Andrés) o 80086601 (Iván)"},
                "monto": {"type": "number", "description": "Monto en COP"},
                "banco": {"type": "string", "description": "Banco de origen del retiro"},
                "descripcion": {"type": "string", "description": "Descripción del retiro o gasto"},
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd (opcional)"},
            },
        },
    },
    {
        "name": "registrar_ingreso_no_operacional",
        "description": (
            "Registra un ingreso que no es venta de motos ni cuota de cartera: "
            "intereses bancarios, venta de motos recuperadas, otros ingresos. "
            "Cuenta desde plan_ingresos_roddos en MongoDB."
        ),
        "input_schema": {
            "type": "object",
            "required": ["tipo", "monto", "banco", "descripcion"],
            "properties": {
                "tipo": {
                    "type": "string",
                    "enum": ["intereses_bancarios", "venta_motos_recuperadas", "otros"],
                    "description": "Tipo de ingreso no operacional",
                },
                "monto": {"type": "number"},
                "banco": {"type": "string"},
                "descripcion": {"type": "string"},
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd (opcional)"},
            },
        },
    },
    {
        "name": "crear_factura_venta",
        "description": (
            "Crea una factura de venta de moto en Alegra (POST /invoices). "
            "VIN y motor son OBLIGATORIOS — sin ellos no factura. "
            "Formato obligatorio del ítem: '[Modelo] [Color] - VIN: [x] / Motor: [x]'. "
            "Valida que la moto esté en estado 'disponible' antes de facturar."
        ),
        "input_schema": {
            "type": "object",
            "required": ["cliente_nombre", "cliente_cedula", "moto_vin", "plan"],
            "properties": {
                "cliente_nombre": {"type": "string"},
                "cliente_cedula": {"type": "string"},
                "moto_vin": {"type": "string", "description": "VIN (chasis) de la moto — obligatorio"},
                "plan": {"type": "string", "enum": ["P39S", "P52S", "P78S"]},
                "cuota_inicial": {"type": "number", "description": "Cuota inicial en COP"},
                "modo_pago": {"type": "string", "enum": ["semanal", "quincenal", "mensual"]},
            },
        },
    },
    {
        "name": "causar_movimiento_bancario",
        "description": (
            "Clasifica y causa un movimiento bancario individual descrito por el usuario. "
            "Propone el asiento antes de ejecutar. Equivalente a conciliación individual por chat."
        ),
        "input_schema": {
            "type": "object",
            "required": ["descripcion", "monto", "banco"],
            "properties": {
                "descripcion": {"type": "string", "description": "Descripción original del movimiento bancario"},
                "monto": {"type": "number"},
                "banco": {"type": "string"},
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd"},
                "tipo": {"type": "string", "enum": ["debito", "credito"]},
            },
        },
    },
    {
        "name": "consultar_saldo_cxc",
        "description": "Consulta el saldo pendiente de CXC de un socio. Responde '¿Cuánto debe Andrés?'.",
        "input_schema": {
            "type": "object",
            "required": ["socio_cedula"],
            "properties": {
                "socio_cedula": {"type": "string", "description": "CC del socio"},
            },
        },
    },
    {
        "name": "consultar_plan_cuentas",
        "description": "Consulta el plan de cuentas de RODDOS desde MongoDB (plan_cuentas_roddos).",
        "input_schema": {
            "type": "object",
            "properties": {
                "categoria": {"type": "string", "description": "Filtrar por categoría (gastos, ingresos, bancos, etc.)"},
            },
        },
    },
    {
        "name": "consultar_journals",
        "description": "Consulta journals en Alegra por rango de fechas. Solo lectura.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha_desde": {"type": "string", "description": "yyyy-MM-dd"},
                "fecha_hasta": {"type": "string", "description": "yyyy-MM-dd"},
            },
        },
    },
    {
        "name": "consultar_facturas",
        "description": "Consulta facturas de venta en Alegra. Solo lectura.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha_inicio": {"type": "string"},
                "fecha_fin": {"type": "string"},
            },
        },
    },
    {
        "name": "consultar_cartera",
        "description": "Consulta el loanbook activo en MongoDB. Solo lectura.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filtro_estado": {"type": "string", "enum": ["activo", "pendiente_entrega", "saldado", "mora"]},
            },
        },
    },
]

AGENT_TOOLS: dict[str, list[dict]] = {
    'contador': CONTADOR_TOOLS,
    'cfo': [],      # No tools in Phase 1 (D-05)
    'radar': [],    # No tools in Phase 1
    'loanbook': [], # No tools in Phase 1
}


def get_tools_for_agent(agent_type: str) -> list[dict]:
    """
    Return Anthropic-format tool definitions for the given agent.
    Only Contador has tools in Phase 1 (D-05).
    """
    return AGENT_TOOLS.get(agent_type, [])
