"""
Agente Contador — 34 herramientas (33 + 1 catálogo embebido).

7 categorías operativas + 1 catálogo de cuentas RODDOS embebido en el tool.

REGLA INAMOVIBLE: Alegra es la fuente canónica de toda información contable.
- Plan de cuentas: GET /categories de Alegra — NUNCA MongoDB
- Journals: GET /journals de Alegra
- Facturas: GET /invoices de Alegra
- Pagos: GET /payments de Alegra
- MongoDB SOLO para datos operativos: loanbooks, inventario motos, gestiones

Solo el Contador recibe tools. CFO/RADAR/Loanbook reciben listas vacías.
NUNCA usar /journal-entries (403) — siempre /journals.
NUNCA usar /accounts (403) — siempre /categories.
"""

# ---------------------------------------------------------------------------
# CATEGORÍA 1 — EGRESOS (7 tools)
# ---------------------------------------------------------------------------

_EGRESOS: list[dict] = [
    {
        "name": "crear_causacion",
        "description": (
            "Crea un asiento contable de partida doble (causación) en Alegra via POST /journals. "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra. "
            "Requiere entries con suma débitos == suma créditos. "
            "NUNCA usar /journal-entries (da 403). Fechas en formato yyyy-MM-dd estricto."
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
                            "id": {"type": "integer", "description": "ID Alegra de la cuenta (ver catalogo_cuentas_roddos)"},
                            "debit": {"type": "number", "description": "Valor débito COP (0 si es crédito)"},
                            "credit": {"type": "number", "description": "Valor crédito COP (0 si es débito)"},
                        },
                    },
                },
                "date": {"type": "string", "description": "Fecha yyyy-MM-dd — NUNCA ISO-8601 con timezone"},
                "observations": {"type": "string", "description": "Descripción del asiento contable"},
            },
        },
    },
    {
        "name": "registrar_gasto",
        "description": (
            "Registra un gasto en lenguaje natural. Clasifica automáticamente la cuenta, "
            "calcula ReteFuente + ReteICA según reglas colombianas 2026, propone el asiento "
            "completo al usuario antes de ejecutar. "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra. "
            "Retenciones: Arriendo 3.5%, Servicios 4%, Honorarios PN 10%, PJ 11%, "
            "Compras 2.5% (base >$1.344.573), ReteICA Bogotá 0.414%. "
            "Auteco NIT 860024781 = autoretenedor — NUNCA ReteFuente. "
            "Gastos de socios (Andrés CC 80075452, Iván CC 80086601) = CXC socios, NUNCA gasto operativo."
        ),
        "input_schema": {
            "type": "object",
            "required": ["descripcion", "monto", "banco"],
            "properties": {
                "descripcion": {"type": "string", "description": "Descripción del gasto (ej: 'arriendo bodega enero')"},
                "monto": {"type": "number", "description": "Monto total del gasto en COP"},
                "banco": {"type": "string", "description": "Banco desde donde se pagó (Bancolombia, BBVA, Davivienda, Banco de Bogotá, Global66)"},
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd (opcional, default: hoy)"},
                "proveedor_nit": {"type": "string", "description": "NIT del proveedor (ej: '860024781' para Auteco autoretenedor)"},
                "tipo_persona": {
                    "type": "string",
                    "enum": ["natural", "juridica"],
                    "description": "Natural o jurídica — determina tasa ReteFuente en honorarios (10% vs 11%)",
                },
            },
        },
    },
    {
        "name": "registrar_gasto_recurrente",
        "description": (
            "Registra un gasto fijo recurrente (arriendo, servicios públicos, telefonía, seguros). "
            "Pre-clasifica según el tipo de gasto recurrente. "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra."
        ),
        "input_schema": {
            "type": "object",
            "required": ["tipo_gasto", "monto", "banco", "periodo"],
            "properties": {
                "tipo_gasto": {
                    "type": "string",
                    "enum": ["arriendo", "servicios_publicos", "telefonia", "seguros", "mantenimiento"],
                    "description": "Tipo de gasto recurrente",
                },
                "monto": {"type": "number", "description": "Monto en COP"},
                "banco": {"type": "string"},
                "periodo": {"type": "string", "description": "Período del gasto (ej: 'enero 2026', 'Q1 2026')"},
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd (opcional)"},
                "proveedor_nit": {"type": "string", "description": "NIT del proveedor si aplica"},
            },
        },
    },
    {
        "name": "anular_causacion",
        "description": (
            "Anula (elimina) un journal incorrecto en Alegra via DELETE /journals/{id}. "
            "Ejecuta via request_with_verify() — DELETE → HTTP 200 → GET verificación (debe retornar 404) → confirma eliminación. "
            "Publica evento 'cleanup.journals.ejecutado' al bus después de anular."
        ),
        "input_schema": {
            "type": "object",
            "required": ["journal_id", "motivo"],
            "properties": {
                "journal_id": {"type": "integer", "description": "ID del journal en Alegra a anular"},
                "motivo": {"type": "string", "description": "Razón de la anulación para auditoría"},
            },
        },
    },
    {
        "name": "causar_movimiento_bancario",
        "description": (
            "Clasifica y causa un movimiento bancario individual descrito por el usuario en chat. "
            "Motor matricial clasifica → propone asiento con retenciones → usuario confirma → POST /journals. "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra."
        ),
        "input_schema": {
            "type": "object",
            "required": ["descripcion", "monto", "banco"],
            "properties": {
                "descripcion": {"type": "string", "description": "Descripción original del movimiento bancario"},
                "monto": {"type": "number", "description": "Monto en COP"},
                "banco": {"type": "string"},
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd"},
                "tipo": {"type": "string", "enum": ["debito", "credito"], "description": "Tipo de movimiento"},
            },
        },
    },
    {
        "name": "registrar_ajuste_contable",
        "description": (
            "Registra un ajuste contable entre cuentas (reclasificación, corrección de cuenta). "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra."
        ),
        "input_schema": {
            "type": "object",
            "required": ["cuenta_origen_id", "cuenta_destino_id", "monto", "motivo"],
            "properties": {
                "cuenta_origen_id": {"type": "integer", "description": "ID Alegra cuenta a debitar"},
                "cuenta_destino_id": {"type": "integer", "description": "ID Alegra cuenta a acreditar"},
                "monto": {"type": "number", "description": "Monto del ajuste en COP"},
                "motivo": {"type": "string", "description": "Razón del ajuste para auditoría"},
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd (opcional)"},
            },
        },
    },
    {
        "name": "registrar_depreciacion",
        "description": (
            "Registra depreciación de activos fijos como journal en Alegra. "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra."
        ),
        "input_schema": {
            "type": "object",
            "required": ["activo", "monto", "periodo"],
            "properties": {
                "activo": {"type": "string", "description": "Descripción del activo (ej: 'motos en exhibición')"},
                "monto": {"type": "number", "description": "Monto de depreciación del período en COP"},
                "periodo": {"type": "string", "description": "Período (ej: 'enero 2026')"},
                "tipo_activo": {
                    "type": "string",
                    "enum": ["equipo_computo", "muebles", "vehiculos", "edificaciones", "maquinaria"],
                    "description": "Tipo de activo — determina cuentas y vida útil fiscal Art. 137 ET",
                },
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd (opcional)"},
            },
        },
    },
]

# ---------------------------------------------------------------------------
# CATEGORÍA 2 — INGRESOS (4 tools)
# ---------------------------------------------------------------------------

_INGRESOS: list[dict] = [
    {
        "name": "registrar_pago_cuota",
        "description": (
            "Registra un pago de cuota de cartera. Ejecuta DOS operaciones obligatorias: "
            "1) POST /payments contra la factura de venta en Alegra, "
            "2) POST /journals de ingreso financiero para que el P&L refleje el recaudo. "
            "Ambas operaciones via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra. "
            "La cuota solo se marca pagada si AMBAS operaciones son verificadas. "
            "Sin el journal, el payment existe pero el P&L NO refleja el ingreso."
        ),
        "input_schema": {
            "type": "object",
            "required": ["loanbook_id", "monto", "banco", "numero_cuota"],
            "properties": {
                "loanbook_id": {"type": "string", "description": "ID del loanbook (ej: 'LB-0042')"},
                "monto": {"type": "number", "description": "Monto del pago en COP"},
                "banco": {"type": "string", "description": "Banco donde se recibió el pago"},
                "numero_cuota": {"type": "integer", "description": "Número de cuota pagada"},
                "metodo_pago": {"type": "string", "description": "Nequi, transferencia, efectivo, etc."},
            },
        },
    },
    {
        "name": "registrar_ingreso_no_operacional",
        "description": (
            "Registra un ingreso que no es venta de motos ni cuota de cartera: "
            "intereses bancarios, venta de motos recuperadas, otros ingresos no operacionales. "
            "Cuenta de ingreso obtenida de Alegra via GET /categories. "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra."
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
                "monto": {"type": "number", "description": "Monto en COP"},
                "banco": {"type": "string"},
                "descripcion": {"type": "string"},
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd (opcional)"},
            },
        },
    },
    {
        "name": "registrar_abono_cxc",
        "description": (
            "Registra un abono parcial a CXC de socios. Reduce el saldo pendiente del socio. "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra."
        ),
        "input_schema": {
            "type": "object",
            "required": ["socio_cedula", "monto", "banco"],
            "properties": {
                "socio_cedula": {"type": "string", "description": "CC del socio: 80075452 (Andrés) o 80086601 (Iván)"},
                "monto": {"type": "number", "description": "Monto del abono en COP"},
                "banco": {"type": "string", "description": "Banco de origen"},
                "descripcion": {"type": "string", "description": "Descripción del abono"},
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd (opcional)"},
            },
        },
    },
    {
        "name": "registrar_ingreso_operacional",
        "description": (
            "Registra un ingreso por venta directa (no financiamiento). "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra."
        ),
        "input_schema": {
            "type": "object",
            "required": ["descripcion", "monto", "banco"],
            "properties": {
                "descripcion": {"type": "string", "description": "Descripción de la venta o ingreso"},
                "monto": {"type": "number", "description": "Monto en COP"},
                "banco": {"type": "string"},
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd (opcional)"},
            },
        },
    },
]

# ---------------------------------------------------------------------------
# CATEGORÍA 3 — CONCILIACIÓN BANCARIA (5 tools)
# ---------------------------------------------------------------------------

_CONCILIACION: list[dict] = [
    {
        "name": "conciliar_extracto_bancario",
        "description": (
            "Sube un extracto bancario .xlsx (Bancolombia, BBVA, Davivienda), parsea por formato "
            "de headers del banco, clasifica cada movimiento con confianza 0-1, y causa en batch. "
            "Confianza >= 0.70 → causación automática. < 0.70 → WhatsApp + Backlog. "
            "BackgroundTasks + job_id obligatorio. Anti-duplicados 3 capas: hash extracto + hash movimiento + GET Alegra. "
            "Cada causación via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra."
        ),
        "input_schema": {
            "type": "object",
            "required": ["archivo_path", "banco"],
            "properties": {
                "archivo_path": {"type": "string", "description": "Ruta del archivo .xlsx (SIEMPRE xlsx, NUNCA CSV)"},
                "banco": {
                    "type": "string",
                    "enum": ["bancolombia", "bbva", "davivienda"],
                    "description": "Banco del extracto",
                },
            },
        },
    },
    {
        "name": "clasificar_movimiento",
        "description": (
            "Clasifica un movimiento bancario individual con confianza 0-1. "
            "Motor matricial analiza descripción y retorna: cuenta sugerida, confianza, retenciones si aplican."
        ),
        "input_schema": {
            "type": "object",
            "required": ["descripcion", "monto", "banco"],
            "properties": {
                "descripcion": {"type": "string"},
                "monto": {"type": "number"},
                "banco": {"type": "string"},
                "tipo": {"type": "string", "enum": ["debito", "credito"]},
            },
        },
    },
    {
        "name": "enviar_movimiento_backlog",
        "description": (
            "Envía un movimiento con confianza < 0.70 al módulo Backlog para causación manual posterior. "
            "Registra: fecha, banco, descripción, monto, razón de pendiente, intentos previos."
        ),
        "input_schema": {
            "type": "object",
            "required": ["movimiento_id", "razon"],
            "properties": {
                "movimiento_id": {"type": "string", "description": "ID del movimiento a enviar al backlog"},
                "razon": {"type": "string", "description": "Razón por la que no se pudo causar automáticamente"},
            },
        },
    },
    {
        "name": "causar_desde_backlog",
        "description": (
            "Causa un movimiento pendiente desde el módulo Backlog. "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra. "
            "Si éxito: movimiento sale del Backlog. Si falla: vuelve al Backlog con error actualizado."
        ),
        "input_schema": {
            "type": "object",
            "required": ["backlog_id", "cuenta_id"],
            "properties": {
                "backlog_id": {"type": "string", "description": "ID del movimiento en backlog_movimientos"},
                "cuenta_id": {"type": "integer", "description": "ID Alegra de la cuenta contable a usar"},
                "retenciones": {
                    "type": "object",
                    "description": "Retenciones opcionales a aplicar",
                    "properties": {
                        "retefuente": {"type": "number"},
                        "reteica": {"type": "number"},
                    },
                },
            },
        },
    },
    {
        "name": "consultar_movimientos_pendientes",
        "description": "Lista movimientos pendientes de causar (en backlog). Datos operativos de MongoDB.",
        "input_schema": {
            "type": "object",
            "properties": {
                "banco": {"type": "string", "description": "Filtrar por banco"},
                "fecha_desde": {"type": "string", "description": "yyyy-MM-dd"},
                "fecha_hasta": {"type": "string", "description": "yyyy-MM-dd"},
                "limite": {"type": "integer", "description": "Máximo de resultados (default: 50)"},
            },
        },
    },
]

# ---------------------------------------------------------------------------
# CATEGORÍA 4 — FACTURACIÓN E INVENTARIO (6 tools)
# ---------------------------------------------------------------------------

_FACTURACION: list[dict] = [
    {
        "name": "consultar_cuentas_inventario",
        "description": (
            "Retorna las cuentas contables REALES de RODDOS para registrar ítems en Alegra. "
            "Usar SIEMPRE antes de crear cualquier ítem (moto o repuesto) para incluir "
            "las cuentas correctas en el payload. Sin estas cuentas Alegra rechaza con code 1008. "
            "Uso: cuando el agente va a crear un ítem en Alegra y necesita saber qué cuentas poner. "
            "Retorna account, inventoryAccount y costsAccount según el tipo de ítem."
        ),
        "input_schema": {
            "type": "object",
            "required": ["tipo_item"],
            "properties": {
                "tipo_item": {
                    "type": "string",
                    "enum": ["motos", "repuestos"],
                    "description": "Tipo de ítem: 'motos' para TVS Raider/Sport, 'repuestos' para partes y accesorios",
                },
            },
        },
    },
    {
        "name": "crear_item_inventario",
        "description": (
            "Crea un ítem (moto o repuesto) en Alegra via POST /items para que pueda ser "
            "facturado, vendido o comprado. PREREQUISITO obligatorio antes de crear_factura_venta. "
            "Para motos: category_id=1 (nuevas) o 2 (usadas), reference=VIN (OBLIGATORIO). "
            "Para repuestos: category_id=5, reference=SKU del repuesto. "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra. "
            "Si el ítem ya existe (mismo reference), retorna el existente sin duplicar. "
            "Casos de uso: "
            "'Registrar moto TVS Raider 125 VIN ABC123' → category_id=1, reference=ABC123. "
            "'Registrar repuesto Filtro de aire TVS SKU REP-003' → category_id=5, reference=REP-003. "
            "'Crear inventario de 10 motos' → llamar 10 veces, una por moto. "
            "Después de crear motos, el usuario puede proceder con crear_factura_venta."
        ),
        "input_schema": {
            "type": "object",
            "required": ["nombre", "reference", "category_id", "precio_venta"],
            "properties": {
                "nombre": {
                    "type": "string",
                    "description": "Nombre del ítem (ej: 'TVS Raider 125 2026 - VIN ABC123', 'Filtro aire TVS Raider')",
                },
                "reference": {
                    "type": "string",
                    "description": "VIN para motos (OBLIGATORIO) o SKU para repuestos. Identificador único.",
                },
                "category_id": {
                    "type": "integer",
                    "enum": [1, 2, 5],
                    "description": "Categoría Alegra: 1=Motos nuevas, 2=Motos usadas, 5=Repuestos",
                },
                "precio_venta": {
                    "type": "number",
                    "description": "Precio de venta en COP (con IVA incluido para motos, sin IVA para repuestos)",
                },
                "precio_costo": {
                    "type": "number",
                    "description": "Precio de costo/compra en COP (opcional pero recomendado para margen)",
                },
                "descripcion": {
                    "type": "string",
                    "description": "Descripción adicional del ítem (opcional)",
                },
                "unidad": {
                    "type": "string",
                    "description": "Unidad de medida (default: 'unidad')",
                },
                "iva_pct": {
                    "type": "number",
                    "description": "Porcentaje de IVA (default: 0 para motos — IVA excluido en financiación; 19 para repuestos gravados)",
                },
                "inventariable": {
                    "type": "boolean",
                    "description": "Si Alegra debe llevar stock de este ítem (default: true)",
                },
            },
        },
    },
    {
        "name": "registrar_compra_motos",
        "description": (
            "Registra un lote de motos recién llegadas en Alegra: "
            "1) Crea un ítem individual por cada moto con su VIN como referencia (category_id=1, qty=1). "
            "2) Registra la factura de compra (bill) al proveedor en Alegra. "
            "3) Publica evento compra.motos.registrada para que el Datakeeper actualice MongoDB. "
            "PREREQUISITO obligatorio antes de crear_factura_venta. "
            "Sin ítem con VIN en Alegra = imposible facturar. "
            "Es idempotente: VINs ya existentes se omiten sin error. "
            "Usar cuando llega un lote de motos del proveedor (Auteco, TVS). "
            "Ejemplos: 'llegaron 10 Raider', 'registrar lote de motos factura FV-123'. "
            "El nombre del ítem en Alegra queda: 'TVS Raider 125 - VIN: ABC123 / Motor: XYZ789'. "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra."
        ),
        "input_schema": {
            "type": "object",
            "required": ["motos", "proveedor_nit", "numero_factura", "fecha"],
            "properties": {
                "motos": {
                    "type": "array",
                    "description": "Lista de motos del lote. Una por VIN.",
                    "items": {
                        "type": "object",
                        "required": ["vin", "motor", "modelo"],
                        "properties": {
                            "vin":    {"type": "string", "description": "Número de chasis (VIN). Identificador único de la moto."},
                            "motor": {"type": "string", "description": "Número de motor. OBLIGATORIO para factura DIAN."},
                            "modelo": {
                                "type": "string",
                                "enum": ["TVS Raider 125", "TVS Sport 100"],
                                "description": "Modelo de la moto.",
                            },
                            "color":        {"type": "string", "description": "Color de la moto (opcional)."},
                            "precio_costo": {"type": "number", "description": "Precio de costo de compra en COP (opcional, para margen)."},
                        },
                    },
                },
                "proveedor_nit":    {"type": "string", "description": "NIT del proveedor (ej: '901249413' para Auteco)."},
                "proveedor_nombre": {"type": "string", "description": "Nombre del proveedor (ej: 'Auteco Mobility S.A.S.')."},
                "numero_factura":   {"type": "string", "description": "Número de factura del proveedor."},
                "fecha":            {"type": "string", "description": "Fecha de la factura yyyy-MM-dd."},
                "precio_moto_raider": {"type": "number", "description": "Precio de compra Raider (costo, sin IVA). Opcional."},
                "precio_moto_sport":  {"type": "number", "description": "Precio de compra Sport (costo, sin IVA). Opcional."},
            },
        },
    },
    {
        "name": "crear_factura_venta_via_firecrawl",
        "description": (
            "Crea factura de venta de moto en Alegra via Firecrawl. "
            "Usar SIEMPRE para facturar motos. "
            "No depende de API REST — va directo a la UI de Alegra. "
            "Motor lo da el operador manualmente. "
            "Incluye SOAT $363.300 + Matrícula $296.700 + GPS $82.800 por defecto."
        ),
        "input_schema": {
            "type": "object",
            "required": ["cliente_nombre", "cliente_cedula", "moto_vin", "moto_motor", "moto_modelo", "plan", "modo_pago", "cuota_inicial"],
            "properties": {
                "cliente_nombre":    {"type": "string"},
                "cliente_cedula":    {"type": "string"},
                "cliente_telefono":  {"type": "string"},
                "cliente_direccion": {"type": "string"},
                "cliente_email":     {"type": "string"},
                "moto_vin":          {"type": "string"},
                "moto_motor":        {"type": "string", "description": "Número de motor — el operador lo proporciona"},
                "moto_modelo":       {"type": "string", "enum": ["TVS Raider 125", "TVS Sport 100"]},
                "moto_color":        {"type": "string"},
                "plan":              {"type": "string", "enum": ["P15S", "P26S", "P39S", "P52S", "P78S"]},
                "modo_pago":         {"type": "string", "enum": ["semanal", "quincenal", "mensual"]},
                "cuota_inicial":     {"type": "number"},
                "incluir_soat":      {"type": "boolean"},
                "incluir_matricula": {"type": "boolean"},
                "incluir_gps":       {"type": "boolean"},
            },
        },
    },
    {
        "name": "crear_factura_venta",
        "description": (
            "Crea una factura de venta de moto en Alegra via POST /invoices (status=open). "
            "VIN y motor son OBLIGATORIOS — sin ellos NO facturar. "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra. "
            "Soporta rubros adicionales SOAT, matrícula, GPS (cada uno con su cuenta de ingreso real en Alegra). "
            "Modo promoción: cuota_inicial=0 permitido cuando modo_promocion=true (e.g. 'Sport 100 sin cuota inicial'). "
            "Cascada por eventos (ROG-4): publica factura.venta.creada → listener crea loanbook pendiente_entrega → "
            "listener CRM upserts cliente. El Contador NUNCA escribe en loanbook o crm_clientes directamente."
        ),
        "input_schema": {
            "type": "object",
            "required": ["cliente_nombre", "cliente_cedula", "moto_vin", "plan"],
            "properties": {
                "cliente_nombre": {"type": "string", "description": "Nombre completo del cliente"},
                "cliente_cedula": {"type": "string", "description": "Cédula/identificación del cliente"},
                "cliente_telefono": {"type": "string", "description": "Teléfono del cliente (opcional)"},
                "cliente_direccion": {"type": "string", "description": "Dirección del cliente (opcional)"},
                "moto_vin": {"type": "string", "description": "VIN (chasis) — OBLIGATORIO. Se resuelve el ítem Alegra por reference/VIN"},
                "plan": {"type": "string", "enum": ["P15S", "P26S", "P39S", "P52S", "P78S"], "description": "Plan de crédito (semanas base)"},
                "cuota_inicial": {"type": "number", "description": "Cuota inicial en COP (puede ser 0 si modo_promocion=true)"},
                "cuota_valor": {"type": "number", "description": "Valor de la cuota periódica en COP"},
                "num_cuotas": {"type": "integer", "description": "Número de cuotas (def: deriva del plan + modalidad)"},
                "modo_pago": {"type": "string", "enum": ["semanal", "quincenal", "mensual"], "description": "Modalidad de pago"},
                "modo_promocion": {"type": "boolean", "description": "Si true, permite cuota_inicial=0 (ej: promo Sport 100)"},
                "precio_moto": {"type": "number", "description": "Precio de venta moto (IVA incluido). Si no se envía, Alegra usa el del ítem"},
                "rubros_adicionales": {
                    "type": "object",
                    "description": "Rubros facturados además de la moto. Cada uno se registra contra su cuenta Alegra real.",
                    "properties": {
                        "soat": {"type": "number", "description": "Valor SOAT en COP (exento IVA) — cuenta 5452"},
                        "matricula": {"type": "number", "description": "Valor matrícula en COP (exento IVA) — cuenta 5453"},
                        "gps": {"type": "number", "description": "Valor GPS en COP (IVA 19% incluido) — cuenta 5448"},
                    },
                },
            },
        },
    },
    {
        "name": "consultar_inventario",
        "description": "Consulta motos disponibles en inventario. Datos operativos de MongoDB (inventario_motos).",
        "input_schema": {
            "type": "object",
            "properties": {
                "estado": {
                    "type": "string",
                    "enum": ["disponible", "vendida", "entregada", "recuperada"],
                    "description": "Filtrar por estado",
                },
                "modelo": {"type": "string", "description": "Filtrar por modelo (ej: 'Raider 125')"},
            },
        },
    },
    {
        "name": "actualizar_estado_moto",
        "description": "Cambia el estado de una moto en inventario operativo (MongoDB inventario_motos).",
        "input_schema": {
            "type": "object",
            "required": ["vin", "nuevo_estado"],
            "properties": {
                "vin": {"type": "string", "description": "VIN de la moto"},
                "nuevo_estado": {
                    "type": "string",
                    "enum": ["disponible", "vendida", "entregada", "recuperada"],
                },
                "motivo": {"type": "string", "description": "Razón del cambio de estado"},
            },
        },
    },
    {
        "name": "consultar_bills",
        "description": "Consulta facturas de compra recibidas (cuentas por pagar) desde Alegra via GET /bills.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha_desde": {"type": "string", "description": "yyyy-MM-dd"},
                "fecha_hasta": {"type": "string", "description": "yyyy-MM-dd"},
                "proveedor": {"type": "string", "description": "Nombre o NIT del proveedor"},
            },
        },
    },
    {
        "name": "anular_factura",
        "description": (
            "Anula (void) una factura de venta en Alegra. "
            "Ejecuta POST /invoices/{id}/void con motivo. "
            "Publica evento factura.venta.anulada al bus."
        ),
        "input_schema": {
            "type": "object",
            "required": ["invoice_id"],
            "properties": {
                "invoice_id": {"type": "string", "description": "ID de la factura en Alegra a anular"},
                "motivo": {"type": "string", "description": "Razón de la anulación"},
            },
        },
    },
    {
        "name": "crear_nota_credito",
        "description": (
            "Crea una nota crédito asociada a una factura en Alegra via POST /credit-notes. "
            "Ejecuta via request_with_verify(). Publica evento nota_credito.creada."
        ),
        "input_schema": {
            "type": "object",
            "required": ["invoice_id", "motivo"],
            "properties": {
                "invoice_id": {"type": "string", "description": "ID de la factura original en Alegra"},
                "motivo": {"type": "string", "description": "Razón de la nota crédito"},
                "items": {
                    "type": "array",
                    "description": "Items de la nota crédito (parcial o total)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "price": {"type": "number"},
                            "quantity": {"type": "number"},
                        },
                    },
                },
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd (opcional, default: hoy)"},
            },
        },
    },
]

# ---------------------------------------------------------------------------
# CATEGORÍA 5 — CONSULTAS ALEGRA - SOLO LECTURA (8 tools)
# ---------------------------------------------------------------------------

_CONSULTAS_ALEGRA: list[dict] = [
    {
        "name": "consultar_plan_cuentas",
        "description": (
            "Consulta el plan de cuentas de RODDOS desde Alegra via GET /categories. "
            "NUNCA desde MongoDB. Alegra es la fuente canónica del plan de cuentas 233 NIIF. "
            "Para referencia rápida de IDs, usar catalogo_cuentas_roddos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "description": "Filtrar por tipo de cuenta (gastos, ingresos, bancos)"},
            },
        },
    },
    {
        "name": "consultar_journals",
        "description": "Consulta journals (comprobantes contables) en Alegra via GET /journals por rango de fechas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha_desde": {"type": "string", "description": "yyyy-MM-dd"},
                "fecha_hasta": {"type": "string", "description": "yyyy-MM-dd"},
                "limite": {"type": "integer", "description": "Máximo de resultados"},
            },
        },
    },
    {
        "name": "consultar_facturas",
        "description": "Consulta facturas de venta emitidas desde Alegra via GET /invoices.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha_desde": {"type": "string", "description": "yyyy-MM-dd"},
                "fecha_hasta": {"type": "string", "description": "yyyy-MM-dd"},
                "cliente": {"type": "string", "description": "Nombre o cédula del cliente"},
            },
        },
    },
    {
        "name": "consultar_pagos",
        "description": "Consulta pagos registrados en Alegra via GET /payments.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha_desde": {"type": "string", "description": "yyyy-MM-dd"},
                "fecha_hasta": {"type": "string", "description": "yyyy-MM-dd"},
            },
        },
    },
    {
        "name": "consultar_saldo_cxc",
        "description": (
            "Consulta el saldo pendiente de CXC de un socio. "
            "Responde preguntas como '¿Cuánto debe Andrés?' con monto exacto."
        ),
        "input_schema": {
            "type": "object",
            "required": ["socio_cedula"],
            "properties": {
                "socio_cedula": {"type": "string", "description": "CC del socio: 80075452 (Andrés) o 80086601 (Iván)"},
            },
        },
    },
    {
        "name": "consultar_balance_general",
        "description": (
            "Construye el Balance General leyendo directamente de Alegra "
            "(GET /categories + GET /journals). CXC socios va al activo corriente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha_corte": {"type": "string", "description": "Fecha de corte yyyy-MM-dd (default: hoy)"},
            },
        },
    },
    {
        "name": "consultar_estado_resultados",
        "description": (
            "Construye el P&L (Estado de Resultados) leyendo directamente de Alegra "
            "(GET /journals + GET /invoices + GET /payments + GET /categories). "
            "Separa devengado (Sección A) de caja real (Sección B). "
            "CXC socios NO afecta P&L — va al balance. IVA cuatrimestral (ene-abr/may-ago/sep-dic)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mes": {"type": "integer", "description": "Mes (1-12)"},
                "anio": {"type": "integer", "description": "Año (ej: 2026)"},
            },
        },
    },
    {
        "name": "consultar_proveedores",
        "description": "Consulta proveedores (terceros) desde Alegra via GET /contacts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "Buscar por nombre"},
                "nit": {"type": "string", "description": "Buscar por NIT"},
            },
        },
    },
]

# ---------------------------------------------------------------------------
# CATEGORÍA 6 — CARTERA (2 tools)
# ---------------------------------------------------------------------------

_CARTERA: list[dict] = [
    {
        "name": "resumen_cartera",
        "description": (
            "Consulta el resumen ejecutivo de cartera activa de RODDOS desde MongoDB. "
            "Retorna: cartera_total (saldo_capital + saldo_intereses de todos los loanbooks activos), "
            "total_creditos, creditos_al_dia, creditos_en_mora, recaudo_semanal_proyectado, dpd_promedio. "
            "Usar para preguntas como: '¿cuál es la cartera total?', '¿cuánto se debe?', "
            "'¿cuántos créditos hay activos?', 'resumen de cartera'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "consultar_cartera",
        "description": "Consulta loanbooks operativos desde MongoDB (dato operativo, no contable).",
        "input_schema": {
            "type": "object",
            "properties": {
                "filtro_estado": {
                    "type": "string",
                    "enum": ["activo", "pendiente_entrega", "saldado", "mora"],
                },
            },
        },
    },
    {
        "name": "consultar_recaudo_semanal",
        "description": (
            "Consulta el recaudo del miércoles actual (día de cobro semanal). "
            "Lee pagos de Alegra via GET /payments + datos operativos de loanbooks en MongoDB."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha": {"type": "string", "description": "yyyy-MM-dd del miércoles (default: miércoles actual)"},
            },
        },
    },
]

# ---------------------------------------------------------------------------
# CATEGORÍA 7 — NÓMINA E IMPUESTOS (3 tools)
# ---------------------------------------------------------------------------

_NOMINA_IMPUESTOS: list[dict] = [
    {
        "name": "registrar_nomina",
        "description": (
            "Registra la nómina mensual por empleado como journals individuales en Alegra. "
            "Cuenta Sueldos 510506 (ID 5462) + Seguridad Social (ID 5471). "
            "Anti-duplicados por mes + empleado: si ya se registró, bloquea y avisa. "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra."
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
                            "seguridad_social": {"type": "number", "description": "Aporte seguridad social COP"},
                        },
                    },
                },
                "incluir_sgsss": {
                    "type": "boolean",
                    "description": "Incluir seguridad social y parafiscales (default: true). Si false, solo causa salario basico.",
                },
            },
        },
    },
    {
        "name": "registrar_cxc_socio",
        "description": (
            "Registra un retiro o gasto personal de un socio como CXC (Cuentas por Cobrar). "
            "NUNCA como gasto operativo — distorsiona el P&L. "
            "Socios: Andrés Sanjuan CC 80075452, Iván Echeverri CC 80086601. "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación → retorna ID Alegra."
        ),
        "input_schema": {
            "type": "object",
            "required": ["socio_cedula", "monto", "banco", "descripcion"],
            "properties": {
                "socio_cedula": {"type": "string", "description": "CC del socio: 80075452 (Andrés) o 80086601 (Iván)"},
                "monto": {"type": "number", "description": "Monto en COP"},
                "banco": {"type": "string", "description": "Banco de origen del retiro"},
                "descripcion": {"type": "string", "description": "Descripción del retiro o gasto personal"},
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd (opcional)"},
            },
        },
    },
    {
        "name": "consultar_iva_cuatrimestral",
        "description": (
            "Consulta el IVA acumulado del período cuatrimestral actual desde Alegra. "
            "Períodos: ene-abr / may-ago / sep-dic — NUNCA bimestral. "
            "Lee journals de Alegra via GET /journals con filtro de cuentas IVA."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "periodo": {
                    "type": "string",
                    "enum": ["ene-abr", "may-ago", "sep-dic"],
                    "description": "Período cuatrimestral",
                },
                "anio": {"type": "integer", "description": "Año (ej: 2026)"},
            },
        },
    },
    {
        "name": "provisionar_prestaciones",
        "description": "Provisiona mensualmente prestaciones sociales (prima 8.33%, cesantías 8.33%, intereses cesantías 1%, vacaciones 4.17%). Crea journal por empleado con gasto (P&L) y provisión (Balance). Anti-dup por mes+empleado.",
        "input_schema": {
            "type": "object",
            "required": ["mes"],
            "properties": {
                "mes": {"type": "string", "description": "Período yyyy-MM (ej: '2026-04')"},
                "empleados": {
                    "type": "array",
                    "description": "Lista de empleados. Si no se envía, usa Alexa ($4.5M) y Liz ($2.2M)",
                    "items": {
                        "type": "object",
                        "required": ["nombre", "salario"],
                        "properties": {
                            "nombre": {"type": "string"},
                            "salario": {"type": "number"},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "consultar_calendario_tributario",
        "description": (
            "Muestra el calendario tributario de RODDOS con las próximas fechas de vencimiento "
            "y semáforo: VERDE (>30 días), AMARILLO (7-30 días), ROJO (<7 días), VENCIDO. "
            "Obligaciones: ReteFuente (mensual), IVA (cuatrimestral), ReteICA Bogotá (bimestral), "
            "ICA Bogotá (anual)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

# ---------------------------------------------------------------------------
# HERRAMIENTA #34 — CATÁLOGO DE CUENTAS RODDOS (tool especial embebido)
# ---------------------------------------------------------------------------

_CATALOGO: list[dict] = [
    {
        "name": "catalogo_cuentas_roddos",
        "description": (
            "Catálogo RODDOS con IDs REALES de Alegra (verificados 2026-04-10). "
            "Solo lectura — el catálogo está embebido para referencia inmediata.\n\n"
            "GASTOS (IDs Alegra reales):\n"
            "- 5462: Sueldos y salarios (510506)\n"
            "- 5475: Asesoría jurídica (511025) — Honorarios\n"
            "- 5476: Asesoría financiera (511030)\n"
            "- 5471: Aportes ARL (510568)\n"
            "- 5472: Aportes pensiones (510570)\n"
            "- 5473: Aportes cajas compensación (510572)\n"
            "- 5480: Arrendamientos (512010)\n"
            "- 5485: Acueducto/Servicios Públicos (513525)\n"
            "- 5486: Energía eléctrica (313530)\n"
            "- 5487: Teléfono/Internet (513535)\n"
            "- 5492: Construcciones y Edificaciones (514510)\n"
            "- 5497: Útiles papelería (519530)\n"
            "- 5499: Taxis y buses (519545)\n"
            "- 5507: Gastos bancarios (530505)\n"
            "- 5508: Comisiones bancarias (530515)\n"
            "- 5509: Gravamen 4x1000 (531520)\n"
            "- 5494: FALLBACK Deudores (51991001) — NUNCA 5493 (accumulative) ni 5495\n\n"
            "RETENCIONES POR PAGAR (IDs Alegra por tipo):\n"
            "- 5381: Ret honorarios 10% (23651501)\n"
            "- 5382: Ret honorarios 11% (23651502)\n"
            "- 5383: Ret servicios 4% (23652501)\n"
            "- 5386: Ret arriendo 3.5% (23653001)\n"
            "- 5388: Ret compras 2.5% (23654001)\n"
            "- 5392: RteIca 11,04 (23680501)\n"
            "- 5393: RteIca 9,66 (23680502)\n\n"
            "BANCOS (IDs Alegra para journal entries):\n"
            "- 5314: Bancolombia 2029 (11100501)\n"
            "- 5315: Bancolombia 2540 (11100502)\n"
            "- 5318: BBVA 0210 (11100505)\n"
            "- 5319: BBVA 0212 (11100506)\n"
            "- 5322: Davivienda 482 (11200502)\n"
            "- 5321: Banco de Bogota (11200501)\n"
            "- 5536: Global 66 (11100507)\n\n"
            "CXC / INGRESOS:\n"
            "- 5329: CXC Socios y accionistas (132505)\n"
            "- 5327: Créditos Directos Roddos CXC (13050502)\n"
            "- 5456: Créditos Directos Roddos Ingreso (41502001)\n"
            "- 5442: Ventas Motos (41350501)\n\n"
            "RETENCIONES 2026:\n"
            "- Arrendamiento: ReteFuente 3.5%\n"
            "- Servicios: ReteFuente 4%\n"
            "- Honorarios PN: ReteFuente 10%\n"
            "- Honorarios PJ: ReteFuente 11%\n"
            "- Compras: ReteFuente 2.5% (base > $1.344.573)\n"
            "- ReteICA Bogotá: 0.414%\n"
            "- IVA: cuatrimestral (ene-abr / may-ago / sep-dic) — NUNCA bimestral\n"
            "- Auteco NIT 860024781: autoretenedor — NUNCA ReteFuente\n\n"
            "FORMATO ENTRIES ALEGRA: {\"id\": \"5462\", \"debit\": 1000, \"credit\": 0}\n"
            "NUNCA usar {\"account\": {\"id\": X}} — Alegra espera id directo como string.\n\n"
            "SOCIOS (gastos personales = CXC 5329, NUNCA gasto operativo):\n"
            "- Andrés Sanjuan CC 80075452\n"
            "- Iván Echeverri CC 80086601"
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

# ---------------------------------------------------------------------------
# CATEGORÍA 8 — COMPRAS A PROVEEDORES (2 tools, Phase 8)
# ---------------------------------------------------------------------------

_COMPRAS: list[dict] = [
    {
        "name": "registrar_compra_proveedor",
        "description": (
            "Registra una factura de compra (bill) en Alegra via POST /bills. "
            "Ejecuta via request_with_verify() — POST → HTTP 200 → GET verificación. "
            "Para cada item: busca por referencia en Alegra (GET /items?reference=). "
            "Si no existe, lo crea como producto inventariable bajo categoría 'Repuestos' (id=5). "
            "Auteco NIT 860024781 o 901249413 = AUTORETENEDOR — NUNCA aplicar ReteFuente. "
            "Observations prefijado con [AC] Compra."
        ),
        "input_schema": {
            "type": "object",
            "required": ["numero_factura", "proveedor_nit", "items"],
            "properties": {
                "numero_factura": {"type": "string", "description": "Número de la factura del proveedor (ej: 'FV-12345')"},
                "proveedor_nombre": {"type": "string", "description": "Nombre del proveedor (ej: 'Auteco S.A.S.')"},
                "proveedor_nit": {"type": "string", "description": "NIT del proveedor (ej: '860024781')"},
                "fecha": {"type": "string", "description": "Fecha yyyy-MM-dd"},
                "items": {
                    "type": "array",
                    "description": "Items comprados. Se buscan/crean en Alegra.",
                    "items": {
                        "type": "object",
                        "required": ["nombre", "cantidad", "precio_unit"],
                        "properties": {
                            "nombre": {"type": "string", "description": "Nombre del ítem"},
                            "referencia": {"type": "string", "description": "Código/referencia del proveedor"},
                            "cantidad": {"type": "number", "description": "Cantidad comprada"},
                            "precio_unit": {"type": "number", "description": "Precio unitario en COP (sin IVA)"},
                            "iva_pct": {"type": "number", "description": "% IVA (default 19)"},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "consultar_inventario_alegra",
        "description": (
            "Consulta stock de ítems (repuestos, motos, etc.) directamente desde Alegra via GET /items. "
            "Retorna cantidad disponible, precio y costo. Útil para preguntas tipo '¿cuántos filtros de aire tenemos?'. "
            "Alegra es la fuente canónica — MongoDB es solo cache."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "Filtro por nombre (coincidencia parcial)"},
                "referencia": {"type": "string", "description": "Filtro por referencia exacta"},
                "categoria_id": {"type": "string", "description": "Filtro por categoría Alegra (1=Motos nuevas, 2=Motos usadas, 3=GPS, 4=Seguro, 5=Repuestos)"},
            },
        },
    },
]

# ---------------------------------------------------------------------------
# LISTA COMPLETA: 44 herramientas (43 previas + 1 consultar_cuentas_inventario)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CATEGORÍA 9 — TOOLS V2 vía Firecrawl Agent (2026-04-27)
# Reemplazo robusto de las tools que iban via API REST cuando Alegra bloquea
# bots, y de las tools que iban via scrape+interact de Firecrawl (rotas).
# Diagnóstico: .planning/DIAGNOSTICO_CONTADOR_FIRECRAWL.md
# ---------------------------------------------------------------------------

_AGENTE_V2: list[dict] = [
    {
        "name": "crear_factura_venta_alegra_agente",
        "description": (
            "USAR SIEMPRE para emitir una factura de venta de moto a crédito. "
            "Reemplaza a crear_factura_venta y a crear_factura_venta_via_firecrawl (ambas obsoletas/rotas). "
            "Esta tool ejecuta el agente IA de Firecrawl (Playwright + LLM) sobre la UI de Alegra "
            "y devuelve el ID NUMÉRICO real de la factura (extraído de la URL final). "
            "VIN y motor son obligatorios. SOAT, matrícula y GPS van incluidos por defecto. "
            "Forma de pago: CRÉDITO. Status: open (factura electrónica DIAN)."
        ),
        "input_schema": {
            "type": "object",
            "required": ["cliente_nombre", "cliente_cedula", "moto_vin", "moto_motor", "moto_modelo", "plan", "modo_pago"],
            "properties": {
                "cliente_nombre":    {"type": "string"},
                "cliente_cedula":    {"type": "string"},
                "cliente_telefono":  {"type": "string"},
                "cliente_direccion": {"type": "string"},
                "cliente_email":     {"type": "string"},
                "moto_vin":          {"type": "string", "description": "VIN/chasis OBLIGATORIO"},
                "moto_motor":        {"type": "string", "description": "Número de motor — el operador lo proporciona"},
                "moto_modelo":       {"type": "string", "enum": ["TVS Raider 125", "TVS Sport 100"]},
                "moto_color":        {"type": "string"},
                "plan":              {"type": "string", "enum": ["P15S", "P26S", "P39S", "P52S", "P78S"]},
                "modo_pago":         {"type": "string", "enum": ["semanal", "quincenal", "mensual"]},
                "cuota_inicial":     {"type": "number"},
                "incluir_soat":      {"type": "boolean", "description": "Default true"},
                "incluir_matricula": {"type": "boolean", "description": "Default true"},
                "incluir_gps":       {"type": "boolean", "description": "Default true"},
            },
        },
    },
    {
        "name": "registrar_compra_motos_agente",
        "description": (
            "USAR SIEMPRE para registrar la llegada de un lote de motos del proveedor. "
            "Reemplaza a registrar_compra_motos cuando Alegra bloquea POST /items via API. "
            "Esta tool usa el agente IA de Firecrawl: por cada moto crea un ítem inventariable "
            "individual (reference=VIN exacto, categoría Motos nuevas id 1, cuentas 41350501/14350101/61350501) "
            "y luego registra el bill al proveedor. Idempotente: VINs duplicados se omiten. "
            "Devuelve el ID NUMÉRICO real del bill en Alegra. "
            "Cuándo: 'llegaron N motos', 'subir lote Auteco', PDF Auteco de motos."
        ),
        "input_schema": {
            "type": "object",
            "required": ["motos", "proveedor_nit", "numero_factura", "fecha"],
            "properties": {
                "motos": {
                    "type": "array",
                    "description": "Lista de motos. Una por VIN.",
                    "items": {
                        "type": "object",
                        "required": ["vin", "motor", "modelo"],
                        "properties": {
                            "vin":    {"type": "string", "description": "VIN/chasis exacto, mayúsculas"},
                            "motor":  {"type": "string", "description": "Número de motor — OBLIGATORIO DIAN"},
                            "modelo": {"type": "string", "enum": ["TVS Raider 125", "TVS Sport 100"]},
                            "color":  {"type": "string"},
                            "precio_costo": {"type": "number", "description": "Costo unitario sin IVA en COP"},
                        },
                    },
                },
                "proveedor_nit":    {"type": "string", "description": "NIT proveedor (Auteco 901249413 o 860024781)"},
                "proveedor_nombre": {"type": "string"},
                "numero_factura":   {"type": "string"},
                "fecha":            {"type": "string", "description": "yyyy-MM-dd"},
            },
        },
    },
    {
        "name": "registrar_compra_repuestos_agente",
        "description": (
            "USAR SIEMPRE para registrar compras de repuestos a proveedor (Auteco u otros). "
            "Crítico: garantiza que los ítems queden en la BODEGA 'Repuestos' para que las "
            "cuentas contables 14350102 (inventario), 41350601 (ingreso) y 61350601 (costo) "
            "NO sean sobreescritas por la bodega default de motos. "
            "Si la bodega 'Repuestos' no existe, esta tool la crea automáticamente. "
            "Luego crea los ítems (reference=referencia del proveedor, categoría Repuestos id 5) "
            "y registra el bill. Idempotente por reference. "
            "Devuelve ID NUMÉRICO real del bill. Auteco NIT 860024781/901249413 = autoretenedor."
        ),
        "input_schema": {
            "type": "object",
            "required": ["items", "proveedor_nit", "numero_factura", "fecha"],
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["referencia", "nombre", "cantidad", "precio_unit"],
                        "properties": {
                            "referencia":  {"type": "string", "description": "SKU/referencia exacta del proveedor"},
                            "nombre":      {"type": "string"},
                            "cantidad":    {"type": "number"},
                            "precio_unit": {"type": "number", "description": "Precio unitario sin IVA en COP"},
                            "iva_pct":     {"type": "number", "description": "Default 19"},
                        },
                    },
                },
                "proveedor_nit":    {"type": "string"},
                "proveedor_nombre": {"type": "string"},
                "numero_factura":   {"type": "string"},
                "fecha":            {"type": "string", "description": "yyyy-MM-dd"},
            },
        },
    },
]


CONTADOR_TOOLS: list[dict] = (
    _EGRESOS
    + _INGRESOS
    + _CONCILIACION
    + _FACTURACION
    + _CONSULTAS_ALEGRA
    + _CARTERA
    + _NOMINA_IMPUESTOS
    + _COMPRAS
    + _CATALOGO
    + _AGENTE_V2  # Tools V2 robustas vía Firecrawl Agent (2026-04-27)
)

from agents.loanbook.tools import LOANBOOK_TOOLS

AGENT_TOOLS: dict[str, list[dict]] = {
    'contador': CONTADOR_TOOLS,
    'cfo': [],      # No tools — CFO solo lee de Alegra (GET)
    'radar': [],    # No tools — RADAR solo gestiona cobranza
    'loanbook': LOANBOOK_TOOLS,  # 11 tools — Sprint 7
}


def get_tools_for_agent(agent_type: str) -> list[dict]:
    """
    Return Anthropic-format tool definitions for the given agent.
    Only Contador has tools. CFO/RADAR/Loanbook return empty lists.
    """
    return AGENT_TOOLS.get(agent_type, [])
