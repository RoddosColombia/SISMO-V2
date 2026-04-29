"""
services/cobranza/sub_buckets.py — Sub-buckets semanales Phase 7 RODDOS.

El diferenciador clave de RODDOS — cobros semanales WhatsApp los miércoles —
se traduce en sub-buckets DPD semanales que dan alertas tempranas 3-4× más
granulares que el estándar mensual.

Logica pura sin I/O. Testeable sin mocks.
"""
from __future__ import annotations
from typing import Literal

# Sub-buckets Phase 7
SubBucket = Literal[
    "Current",       # 0 DPD — al dia
    "Grace",         # 1-7 — 1 semana sin pago
    "Warning",       # 8-14 — 2 semanas sin pago
    "Alert",         # 15-21 — 3 semanas
    "Critical",      # 22-30 — 4 semanas
    "Severe",        # 31-60 — 5-8 semanas
    "PreDefault",    # 61-89 — 9-12 semanas
    "Default",       # 90+ — 13+ semanas
    "ChargeOff",     # 120+ — castigado contablemente
]

BUCKETS_ORDEN: list[SubBucket] = [
    "Current", "Grace", "Warning", "Alert", "Critical",
    "Severe", "PreDefault", "Default", "ChargeOff",
]


def asignar_sub_bucket(dpd: int) -> SubBucket:
    """Asigna sub-bucket según DPD del loanbook."""
    if dpd <= 0:
        return "Current"
    if dpd <= 7:
        return "Grace"
    if dpd <= 14:
        return "Warning"
    if dpd <= 21:
        return "Alert"
    if dpd <= 30:
        return "Critical"
    if dpd <= 60:
        return "Severe"
    if dpd <= 89:
        return "PreDefault"
    if dpd < 120:
        return "Default"
    return "ChargeOff"


# Acción RADAR esperada por bucket
ACCION_POR_BUCKET: dict[SubBucket, str] = {
    "Current":     "Solo recordatorio martes -1d (T1)",
    "Grace":       "WhatsApp jueves (T3) + llamada viernes",
    "Warning":     "Llamada diaria + WhatsApp diario (Ley 2300: max 1/dia)",
    "Alert":       "Escalación a admin + oferta acuerdo de pago",
    "Critical":    "Notificar Andres/Ivan + verificacion GPS",
    "Severe":      "Fase prejudicial — comunicacion formal escrita",
    "PreDefault":  "Evaluar recuperacion voluntaria vs forzada",
    "Default":     "Protocolo recuperacion — Motos del Tropico",
    "ChargeOff":   "Castigado contablemente — recuperacion judicial",
}

# Color UI por bucket (hex sin #)
COLOR_POR_BUCKET: dict[SubBucket, str] = {
    "Current":     "10b981",  # green-500
    "Grace":       "fbbf24",  # amber-400
    "Warning":     "f97316",  # orange-500
    "Alert":       "ef4444",  # red-500
    "Critical":    "dc2626",  # red-600
    "Severe":      "991b1b",  # red-800
    "PreDefault":  "7f1d1d",  # red-900
    "Default":     "1f2937",  # gray-800
    "ChargeOff":   "000000",  # black
}

# Severidad numerica para ordenar/ponderar
SEVERIDAD: dict[SubBucket, int] = {
    "Current": 0, "Grace": 1, "Warning": 2, "Alert": 3,
    "Critical": 4, "Severe": 5, "PreDefault": 6,
    "Default": 7, "ChargeOff": 8,
}

# Recuperabilidad esperada (% historico industria microfinanza colombiana)
RECUPERABILIDAD_ESPERADA: dict[SubBucket, float] = {
    "Current":     1.0,
    "Grace":       0.95,
    "Warning":     0.80,
    "Alert":       0.60,
    "Critical":    0.40,
    "Severe":      0.20,
    "PreDefault":  0.10,
    "Default":     0.05,
    "ChargeOff":   0.02,
}


# Template Mercately a enviar segun bucket (env vars en Render)
import os
TEMPLATE_POR_BUCKET: dict[SubBucket, str] = {
    "Grace":       os.getenv("MERCATELY_TEMPLATE_T3_MORA_CORTA_ID", ""),
    "Warning":     os.getenv("MERCATELY_TEMPLATE_T3_MORA_CORTA_ID", ""),
    "Alert":       os.getenv("MERCATELY_TEMPLATE_T4_MORA_MEDIA_ID", ""),
    "Critical":    os.getenv("MERCATELY_TEMPLATE_T4_MORA_MEDIA_ID", ""),
    "Severe":      os.getenv("MERCATELY_TEMPLATE_T5_ULTIMO_AVISO_ID", ""),
    "PreDefault":  os.getenv("MERCATELY_TEMPLATE_T5_ULTIMO_AVISO_ID", ""),
    "Default":     os.getenv("MERCATELY_TEMPLATE_T5_ULTIMO_AVISO_ID", ""),
}


def prioridad_score(dpd: int, saldo_pendiente: float) -> float:
    """Score de prioridad: DPD × log10(saldo). Mayor = mas urgente.

    Combina urgencia (DPD) con exposición (saldo). Un cliente
    con DPD=20 y saldo $10M es más prioritario que DPD=2 y saldo $1M.
    """
    import math
    return float(dpd) * math.log10(max(saldo_pendiente, 1) + 1)
