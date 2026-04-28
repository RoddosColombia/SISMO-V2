"""Tests para agents/radar/handlers/dispatcher.py — Sprint S2."""
from __future__ import annotations
import os
from datetime import datetime, date, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.radar.handlers.dispatcher import (
    RadarToolDispatcher,
    is_read_only_tool,
    _within_ley_2300_window,
    _calcular_dpd,
    _sugerir_template,
)


def _mock_db():
    db = MagicMock()
    for col in ("loanbook", "crm_clientes", "roddos_events", "radar_alertas"):
        c = MagicMock()
        c.find_one = AsyncMock(return_value=None)
        c.insert_one = AsyncMock()
        c.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

        # Para .find() necesitamos un async iterator
        async def _async_iter(self):
            for item in []:
                yield item
        cursor = MagicMock()
        cursor.__aiter__ = _async_iter
        cursor.limit = MagicMock(return_value=cursor)
        c.find = MagicMock(return_value=cursor)
        setattr(db, col, c)
    return db


# ─────────────────────────────────────────────────────────────────────────────
# Helpers puros
# ─────────────────────────────────────────────────────────────────────────────

def test_is_read_only_tool():
    assert is_read_only_tool("generar_cola_cobranza") is True
    assert is_read_only_tool("consultar_estado_cliente") is True
    assert is_read_only_tool("registrar_gestion") is False
    assert is_read_only_tool("enviar_whatsapp_template") is False


def test_within_ley_2300_window_horarios():
    # Lunes 10AM (weekday=0, hour=10) — permitido
    assert _within_ley_2300_window(datetime(2026, 4, 27, 10, 0, tzinfo=timezone.utc))
    # Lunes 6:30AM — fuera
    assert not _within_ley_2300_window(datetime(2026, 4, 27, 6, 30, tzinfo=timezone.utc))
    # Lunes 7PM — fuera (se permite hasta 19:00 estricto)
    assert not _within_ley_2300_window(datetime(2026, 4, 27, 19, 0, tzinfo=timezone.utc))
    # Sabado 10AM (weekday=5, hour=10) — permitido
    assert _within_ley_2300_window(datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc))
    # Sabado 4PM — fuera (15:00 cierre)
    assert not _within_ley_2300_window(datetime(2026, 5, 2, 16, 0, tzinfo=timezone.utc))
    # Domingo cualquier hora — fuera
    assert not _within_ley_2300_window(datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc))


def test_calcular_dpd_max_de_cuotas_atrasadas():
    hoy = date(2026, 4, 28)
    cuotas = [
        {"estado": "pagada", "fecha": "2026-04-01"},
        {"estado": "pendiente", "fecha": "2026-04-15"},  # 13 dias dpd
        {"estado": "pendiente", "fecha": "2026-04-22"},  # 6 dias
        {"estado": "pendiente", "fecha": "2026-05-05"},  # futura, no cuenta
    ]
    assert _calcular_dpd(cuotas, hoy) == 13


def test_calcular_dpd_cero_si_todo_al_dia():
    cuotas = [
        {"estado": "pagada", "fecha": "2026-04-01"},
        {"estado": "pendiente", "fecha": "2026-05-05"},  # futura
    ]
    assert _calcular_dpd(cuotas, date(2026, 4, 28)) == 0


def test_sugerir_template_segun_dpd_y_contexto():
    assert _sugerir_template(0, "martes_recordatorio") == "T1"
    assert _sugerir_template(0, "miercoles") == "T2"
    assert _sugerir_template(2, "miercoles") == "T3"
    assert _sugerir_template(2, "jueves_mora") == "T3"
    assert _sugerir_template(10, "jueves_mora") == "T4"
    assert _sugerir_template(40, "jueves_mora") == "T5"
    assert _sugerir_template(40, "ad_hoc") == "T5"
    assert _sugerir_template(0, "ad_hoc") == "T1"


# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_tool_inexistente_devuelve_error():
    d = RadarToolDispatcher(db=_mock_db())
    out = await d.dispatch("tool_que_no_existe", {}, "u1")
    assert out["success"] is False
    assert "no encontrada" in out["error"]


@pytest.mark.asyncio
async def test_registrar_gestion_exito():
    d = RadarToolDispatcher(db=_mock_db())
    out = await d.dispatch("registrar_gestion", {
        "cedula": "1234567",
        "tipo": "llamada_contesta",
        "resultado": "va a pagar el viernes",
        "observacion": "cliente cordial",
    }, "u1")
    assert out["success"] is True
    d.db.crm_clientes.update_one.assert_called_once()


@pytest.mark.asyncio
async def test_registrar_gestion_falla_si_cliente_no_existe():
    db = _mock_db()
    db.crm_clientes.update_one = AsyncMock(return_value=MagicMock(matched_count=0))
    d = RadarToolDispatcher(db=db)
    out = await d.dispatch("registrar_gestion", {
        "cedula": "999", "tipo": "llamada_contesta", "resultado": "x",
    }, "u1")
    assert out["success"] is False
    assert "no encontrado" in out["error"]


@pytest.mark.asyncio
async def test_registrar_promesa_pago_exito():
    d = RadarToolDispatcher(db=_mock_db())
    fecha_futura = (date.today() + timedelta(days=2)).isoformat()
    out = await d.dispatch("registrar_promesa_pago", {
        "cedula": "1234567",
        "fecha_pactada": fecha_futura,
        "monto_pactado": 200_000,
        "canal": "whatsapp",
    }, "u1")
    assert out["success"] is True


@pytest.mark.asyncio
async def test_registrar_promesa_pago_fecha_pasada_rechaza():
    d = RadarToolDispatcher(db=_mock_db())
    fecha_pasada = (date.today() - timedelta(days=2)).isoformat()
    out = await d.dispatch("registrar_promesa_pago", {
        "cedula": "1234567",
        "fecha_pactada": fecha_pasada,
        "monto_pactado": 200_000,
    }, "u1")
    assert out["success"] is False
    assert ">= hoy" in out["error"]


@pytest.mark.asyncio
async def test_enviar_whatsapp_template_invalido():
    d = RadarToolDispatcher(db=_mock_db())
    out = await d.dispatch("enviar_whatsapp_template", {
        "cedula": "1234567", "template": "T99",
    }, "u1")
    assert out["success"] is False
    assert "T99 invalido" in out["error"]


@pytest.mark.asyncio
async def test_enviar_whatsapp_template_no_configurado_en_env(monkeypatch):
    # Asegurar que ningun template ID este configurado
    for k in ("MERCATELY_TEMPLATE_T1_RECORDATORIO_ID",
              "MERCATELY_TEMPLATE_T2_COBRO_HOY_ID",
              "MERCATELY_TEMPLATE_COBRO_ID"):
        monkeypatch.delenv(k, raising=False)
    # Reload dispatcher para que recoja env vars vacias
    import importlib, agents.radar.handlers.dispatcher as mod
    importlib.reload(mod)
    d = mod.RadarToolDispatcher(db=_mock_db())
    out = await d.dispatch("enviar_whatsapp_template", {
        "cedula": "1234567", "template": "T1",
    }, "u1")
    assert out["success"] is False
    assert "no configurado" in out["error"]


@pytest.mark.asyncio
async def test_consultar_estado_cliente_no_existe():
    d = RadarToolDispatcher(db=_mock_db())
    out = await d.dispatch("consultar_estado_cliente", {"cedula": "999"}, "u1")
    assert out["success"] is False
    assert "no encontrado" in out["error"]


@pytest.mark.asyncio
async def test_consultar_estado_cliente_existe_devuelve_loanbooks():
    db = _mock_db()
    cliente_doc = {"_id": "obj", "cedula": "1234567", "nombre": "Juan",
                   "gestiones": [{"tipo": "whatsapp_t1", "fecha": "2026-04-28T08:00:00+00:00"}],
                   "promesas_pago": [{"estado": "vigente", "fecha_pactada": "2026-05-05",
                                       "monto_pactado": 100_000}]}
    db.crm_clientes.find_one = AsyncMock(return_value=cliente_doc)

    # loanbook con cuotas
    async def _iter(self):
        yield {
            "loanbook_id": "lb-1", "vin": "VIN1", "modelo": "TVS Raider 125",
            "modalidad": "semanal", "estado": "activo", "num_cuotas": 52,
            "cliente": {"cedula": "1234567"},
            "cuotas": [
                {"estado": "pagada", "fecha": "2026-04-01"},
                {"estado": "pendiente", "fecha": "2026-04-22", "monto": 150_000},
            ],
        }
    cursor = MagicMock()
    cursor.__aiter__ = _iter
    db.loanbook.find = MagicMock(return_value=cursor)

    d = RadarToolDispatcher(db=db)
    out = await d.dispatch("consultar_estado_cliente", {"cedula": "1234567"}, "u1")
    assert out["success"] is True
    assert out["cliente"]["cedula"] == "1234567"
    assert len(out["loanbooks"]) == 1
    assert len(out["promesas_vigentes"]) == 1
