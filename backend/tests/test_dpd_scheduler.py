"""
test_dpd_scheduler.py — Tests del scheduler DPD del módulo Loanbook.

Valida:
  - _calcular_dpd: lógica pura de cálculo de días de atraso
  - procesar_un_loanbook: lógica con DB mockeada
  - calcular_dpd_todos: integración con DB mockeada

Tests unitarios — sin MongoDB real.
Los tests de procesar_un_loanbook y calcular_dpd_todos usan mongomock / AsyncMock.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.loanbook.dpd_scheduler import (
    _a_fecha,
    _calcular_dpd,
    _segundos_hasta_proximas_6am,
)
from services.loanbook.estados_service import clasificar_estado, clasificar_sub_bucket


# ─────────────────────── BLOQUE 1 — _a_fecha ─────────────────────────────────

class TestAFecha:
    def test_date_pasa_directo(self):
        d = date(2026, 4, 22)
        assert _a_fecha(d) == d

    def test_datetime_extrae_date(self):
        dt = datetime(2026, 4, 22, 15, 30)
        assert _a_fecha(dt) == date(2026, 4, 22)

    def test_string_iso(self):
        assert _a_fecha("2026-04-22") == date(2026, 4, 22)

    def test_string_con_tiempo(self):
        """ISO con hora — solo toma los primeros 10 chars."""
        assert _a_fecha("2026-04-22T06:00:00") == date(2026, 4, 22)


# ─────────────────────── BLOQUE 2 — _calcular_dpd ────────────────────────────

class TestCalcularDPD:
    """Lógica pura de cálculo de DPD — sin I/O."""

    HOY = date(2026, 4, 22)

    def test_sin_cuotas_retorna_cero(self):
        assert _calcular_dpd([], self.HOY) == 0

    def test_todas_pagadas_retorna_cero(self):
        cuotas = [
            {"estado": "pagada", "fecha": "2026-04-01"},
            {"estado": "pagada", "fecha": "2026-04-08"},
        ]
        assert _calcular_dpd(cuotas, self.HOY) == 0

    def test_cuota_futura_no_cuenta(self):
        """Cuota con fecha > hoy no genera DPD."""
        cuotas = [{"estado": "pendiente", "fecha": "2026-04-30"}]
        assert _calcular_dpd(cuotas, self.HOY) == 0

    def test_cuota_vencida_exactamente_hoy_no_cuenta(self):
        """Fecha == hoy → no vencida aún (< hoy es la condición)."""
        cuotas = [{"estado": "pendiente", "fecha": "2026-04-22"}]
        assert _calcular_dpd(cuotas, self.HOY) == 0

    def test_una_cuota_vencida_10_dias(self):
        """Cuota vencida hace 10 días → DPD = 10."""
        cuotas = [{"estado": "pendiente", "fecha": "2026-04-12"}]
        assert _calcular_dpd(cuotas, self.HOY) == 10

    def test_cuota_vencida_1_dia(self):
        cuotas = [{"estado": "pendiente", "fecha": "2026-04-21"}]
        assert _calcular_dpd(cuotas, self.HOY) == 1

    def test_multiples_vencidas_toma_la_mas_antigua(self):
        """Con varias cuotas vencidas, el DPD es desde la más antigua."""
        cuotas = [
            {"estado": "pendiente", "fecha": "2026-04-01"},   # 21 días
            {"estado": "pendiente", "fecha": "2026-04-15"},   # 7 días
            {"estado": "pendiente", "fecha": "2026-04-20"},   # 2 días
        ]
        assert _calcular_dpd(cuotas, self.HOY) == 21

    def test_mezcla_pagada_y_vencida(self):
        """Solo las pendientes/vencidas cuentan."""
        cuotas = [
            {"estado": "pagada",   "fecha": "2026-03-15"},
            {"estado": "pendiente","fecha": "2026-04-01"},   # 21 días
            {"estado": "pendiente","fecha": "2026-04-22"},   # hoy, no cuenta
        ]
        assert _calcular_dpd(cuotas, self.HOY) == 21

    def test_estado_vencida_cuenta(self):
        """Cuotas con estado='vencida' también generan DPD."""
        cuotas = [{"estado": "vencida", "fecha": "2026-04-08"}]
        assert _calcular_dpd(cuotas, self.HOY) == 14

    def test_estado_parcial_cuenta(self):
        """Cuotas con estado='parcial' también generan DPD."""
        cuotas = [{"estado": "parcial", "fecha": "2026-04-15"}]
        assert _calcular_dpd(cuotas, self.HOY) == 7

    def test_campo_fecha_programada_alternativo(self):
        """El scheduler puede tener el campo como fecha_programada."""
        cuotas = [{"estado": "pendiente", "fecha_programada": "2026-04-12"}]
        assert _calcular_dpd(cuotas, self.HOY) == 10

    def test_sin_campo_fecha_ignora_cuota(self):
        """Cuota sin fecha ni fecha_programada no genera DPD."""
        cuotas = [{"estado": "pendiente"}]
        assert _calcular_dpd(cuotas, self.HOY) == 0


# ─────────────────────── BLOQUE 3 — Integración con clasificadores ────────────

class TestIntegracionClasificadores:
    """Verifica que DPD → estado → sub_bucket sea consistente."""

    HOY = date(2026, 4, 22)

    def _lb_con_cuota_vencida(self, dias_atras: int, saldo: float = 1_000_000):
        """Crea un loanbook simple con una cuota vencida N días atrás."""
        fecha_vencida = self.HOY - timedelta(days=dias_atras)
        return {
            "cuotas": [{"estado": "pendiente", "fecha": fecha_vencida.isoformat()}],
            "saldo_capital": saldo,
            "plan_codigo": "P52S",
        }

    def test_flujo_completo_grace(self):
        lb = self._lb_con_cuota_vencida(5)
        cuotas = lb["cuotas"]
        dpd = _calcular_dpd(cuotas, self.HOY)
        estado = clasificar_estado(dpd, lb["saldo_capital"], lb["plan_codigo"])
        sub_bucket = clasificar_sub_bucket(dpd)
        assert dpd == 5
        assert estado == "Early Delinquency"
        assert sub_bucket == "Grace"

    def test_flujo_completo_severe(self):
        lb = self._lb_con_cuota_vencida(35)
        cuotas = lb["cuotas"]
        dpd = _calcular_dpd(cuotas, self.HOY)
        estado = clasificar_estado(dpd, lb["saldo_capital"], lb["plan_codigo"])
        sub_bucket = clasificar_sub_bucket(dpd)
        assert dpd == 35
        assert estado == "Late Delinquency"
        assert sub_bucket == "Severe"

    def test_flujo_saldo_cero_pagado(self):
        """Cuando saldo = 0, el estado es Pagado sin importar DPD."""
        lb = self._lb_con_cuota_vencida(20, saldo=0.0)
        cuotas = lb["cuotas"]
        dpd = _calcular_dpd(cuotas, self.HOY)
        estado = clasificar_estado(dpd, 0.0, lb["plan_codigo"])
        assert estado == "Pagado"


# ─────────────────────── BLOQUE 4 — _segundos_hasta_proximas_6am ─────────────

class TestSegundosHasta6am:
    """Verifica que el cálculo de tiempo hasta 06:00 AM es razonable."""

    def test_retorna_positivo(self):
        """Siempre debe retornar > 0."""
        segundos = _segundos_hasta_proximas_6am()
        assert segundos > 0

    def test_retorna_menos_de_un_dia(self):
        """Nunca debe ser más de 24h."""
        segundos = _segundos_hasta_proximas_6am()
        assert segundos <= 86_400


# ─────────────────────── BLOQUE 5 — procesar_un_loanbook (mock DB) ───────────

@pytest.mark.asyncio
class TestProcesarUnLoanbook:
    """Tests de procesar_un_loanbook con MongoDB mockeado."""

    def _make_db(self):
        """Crea un mock de AsyncIOMotorDatabase."""
        db = MagicMock()
        db.loanbook.update_one = AsyncMock(return_value=None)
        db.loanbook_modificaciones.insert_one = AsyncMock(return_value=None)
        db.roddos_events.insert_one = AsyncMock(return_value=None)
        return db

    async def test_sin_cuotas_vencidas_estado_current(self):
        """Loanbook sin cuotas vencidas → DPD=0 → Current."""
        from services.loanbook.dpd_scheduler import procesar_un_loanbook
        from bson import ObjectId

        hoy = date(2026, 4, 22)
        lb = {
            "_id": ObjectId(),
            "loanbook_id": "LB-2026-0001",
            "estado": "Current",
            "saldo_capital": 1_000_000,
            "plan_codigo": "P52S",
            "cuotas": [
                {"estado": "pendiente", "fecha": "2026-04-29"},  # futura
            ],
        }
        db = self._make_db()
        resultado = await procesar_un_loanbook(db, lb, hoy)

        assert resultado["dpd_nuevo"] == 0
        assert resultado["estado_nuevo"] == "Current"
        assert resultado["cambio"] is False
        db.loanbook.update_one.assert_called_once()

    async def test_cuota_vencida_14_dias_mid_delinquency(self):
        """14 días de atraso → Mid Delinquency, cambio de estado registrado."""
        from services.loanbook.dpd_scheduler import procesar_un_loanbook
        from bson import ObjectId

        hoy = date(2026, 4, 22)
        lb = {
            "_id": ObjectId(),
            "loanbook_id": "LB-2026-0002",
            "estado": "Early Delinquency",
            "saldo_capital": 800_000,
            "plan_codigo": "P52S",
            "cuotas": [
                {"estado": "vencida", "fecha": "2026-04-08"},  # 14 días
            ],
        }
        db = self._make_db()
        resultado = await procesar_un_loanbook(db, lb, hoy)

        assert resultado["dpd_nuevo"] == 14
        assert resultado["estado_nuevo"] == "Mid Delinquency"
        assert resultado["cambio"] is True
        # Debe registrar en loanbook_modificaciones
        db.loanbook_modificaciones.insert_one.assert_called()

    async def test_saldo_cero_marca_pagado(self):
        """Saldo = 0 → Pagado, incluso si hay cuota vencida."""
        from services.loanbook.dpd_scheduler import procesar_un_loanbook
        from bson import ObjectId

        hoy = date(2026, 4, 22)
        lb = {
            "_id": ObjectId(),
            "loanbook_id": "LB-2026-0003",
            "estado": "Current",
            "saldo_capital": 0.0,
            "plan_codigo": "P52S",
            "cuotas": [],
        }
        db = self._make_db()
        resultado = await procesar_un_loanbook(db, lb, hoy)

        assert resultado["estado_nuevo"] == "Pagado"
        assert resultado["cambio"] is True

    async def test_transicion_invalida_no_cambia_estado(self):
        """Transición inválida detectada por scheduler → no modifica estado."""
        from services.loanbook.dpd_scheduler import procesar_un_loanbook
        from bson import ObjectId

        hoy = date(2026, 4, 22)
        # DPD=60 → Charge-Off, pero estado_actual="Aprobado" → transición inválida
        lb = {
            "_id": ObjectId(),
            "loanbook_id": "LB-2026-0004",
            "estado": "Aprobado",
            "saldo_capital": 1_000_000,
            "plan_codigo": "P52S",
            "cuotas": [
                {"estado": "vencida", "fecha": "2026-02-21"},  # ~60 días
            ],
        }
        db = self._make_db()
        resultado = await procesar_un_loanbook(db, lb, hoy)

        # Estado no debe cambiar
        assert resultado["estado_nuevo"] == "Aprobado"
        assert resultado["cambio"] is False
        assert "error" in resultado
        # Debe registrar la transición inválida
        db.loanbook_modificaciones.insert_one.assert_called()
