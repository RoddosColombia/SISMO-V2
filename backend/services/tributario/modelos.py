"""
services/tributario/modelos.py — Schemas para el motor tributario.

Colecciones MongoDB (ROG-4b dueños):
- obligaciones_tributarias  → Contador (write), CFO/UI (read)
- tributario_estado_actual  → DataKeeper (write), CFO (read), UI (read)
- tributario_recomendaciones → CFO (write), UI (read)
"""
from __future__ import annotations
from typing import Literal, TypedDict


# Estado de una obligación tributaria
EstadoObligacion = Literal["pendiente", "calculada", "presentada", "pagada", "vencida"]


class ObligacionDoc(TypedDict, total=False):
    """Doc canónico en obligaciones_tributarias.

    Cada obligación es un periodo (ej IVA-2026-C2). Se actualiza varias veces:
    1. pendiente → cuando solo está en calendario
    2. calculada → Contador corre liquidación
    3. presentada → operador marca "ya presenté formulario en DIAN"
    4. pagada → operador marca "ya pagué"
    """
    obligacion_id: str           # ej "iva-2026-c1"
    tipo: str                    # ver TipoObligacion en calendario_dian
    nombre: str                  # ej "IVA 2026-C1"
    periodo: str                 # ej "2026-C1"
    periodo_inicio: str          # ISO date
    periodo_fin: str             # ISO date
    fecha_vencimiento: str       # ISO date
    formulario_dian: str
    autoridad: str               # "DIAN" | "SHD-Bogotá"
    estado: EstadoObligacion

    # Datos de cálculo (los pone Contador)
    base_gravable: float         # ej IVA generado total cuatrimestre
    impuesto_a_pagar: float      # neto despues de descuentos
    impuesto_descontable: float
    saldo_a_favor: float
    detalle_calculo: dict        # detalle por fila

    # Datos de pago (los pone operador)
    fecha_presentacion: str
    fecha_pago: str
    numero_recibo_dian: str
    monto_pagado: float

    # Metadata
    calculado_at: str
    calculado_por: str
    actualizado_at: str


class TributarioEstadoActual(TypedDict, total=False):
    """Doc único en tributario_estado_actual (singleton key="actual"). Lo escribe DataKeeper.

    Snapshot consolidado del estado tributario para el CFO y la UI.
    Se refresca diariamente 6AM Bogotá.
    """
    _id: str  # "actual"
    fecha_snapshot: str

    # Próximas 30 días
    obligaciones_proximas: list[dict]
    obligaciones_proximas_total_cop: int

    # Periodo actual en curso (acumulados desde inicio periodo)
    iva_periodo_actual: dict      # generado, descontable, neto
    retefuente_periodo_actual: dict  # acumulado del mes
    reica_periodo_actual: dict       # acumulado del bimestre

    # Histórico 12 meses
    historico_pagado_12m: list[dict]
    total_pagado_12m_cop: int

    # Carga tributaria efectiva
    ingresos_12m_cop: int
    impuestos_12m_cop: int
    tasa_efectiva_pct: float


class RecomendacionCFO(TypedDict, total=False):
    """Doc en tributario_recomendaciones — CFO escribe."""
    recomendacion_id: str
    tipo: Literal[
        "iva_optimizacion",      # gastos no descontados
        "timing_gastos",         # adelantar gastos antes cierre
        "depreciacion",          # acelerar depreciación activos fijos
        "inventario",            # método valuación
        "alerta_vencimiento",    # cerca de fecha límite
        "alerta_caja",           # caja insuficiente
        "regimen",               # cambio de régimen tributario
    ]
    severidad: Literal["info", "warning", "critical"]
    titulo: str
    descripcion: str
    impacto_estimado_cop: int    # ahorro o riesgo en COP
    accion_sugerida: str
    fecha_limite: str            # ISO date para tomar acción
    estado: Literal["abierta", "ejecutada", "rechazada", "expirada"]
    creado_at: str
    actualizado_at: str
