"""Tests para services/mercately/internal_notifications.py.

Cubre:
- Helpers puros (_resolver_telefono, _hash_mensaje, _formatear_mensaje)
- Validacion entrada (persona invalida, nivel invalido, mensaje vacio)
- Skip cuando no hay telefono configurado
- Anti-spam diario (>=10 → skip)
- Dedupe 1h (mismo hash en ventana → skip)
- Envio exitoso via send_text
- Fallback a template cuando send_text falla
- Error duro cuando ambos fallan y no hay template
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.mercately.internal_notifications import (
    _resolver_telefono,
    _hash_mensaje,
    _formatear_mensaje,
    notificar_interno,
)


# ─── Helpers puros ───────────────────────────────────────────────────────────

def test_resolver_telefono_co_10_dig(monkeypatch):
    monkeypatch.setenv("INTERNAL_WA_ANDRES", "3001234567")
    assert _resolver_telefono("andres") == "573001234567"

def test_resolver_telefono_ya_normalizado(monkeypatch):
    monkeypatch.setenv("INTERNAL_WA_IVAN", "573001234568")
    assert _resolver_telefono("ivan") == "573001234568"

def test_resolver_telefono_vacio_devuelve_string_vacio(monkeypatch):
    monkeypatch.delenv("INTERNAL_WA_FABIAN", raising=False)
    assert _resolver_telefono("fabian") == ""

def test_resolver_telefono_invalido_devuelve_string_vacio(monkeypatch):
    monkeypatch.setenv("INTERNAL_WA_ANDRES", "abc123")
    assert _resolver_telefono("andres") == ""

def test_hash_mensaje_consistente():
    h1 = _hash_mensaje("andres", "info", "hola mundo")
    h2 = _hash_mensaje("andres", "info", "hola mundo")
    assert h1 == h2 and len(h1) == 24

def test_hash_mensaje_distinto_persona_da_hash_distinto():
    h1 = _hash_mensaje("andres", "info", "hola")
    h2 = _hash_mensaje("ivan", "info", "hola")
    assert h1 != h2

def test_formatear_mensaje_usa_prefijo_correcto():
    assert _formatear_mensaje("alerta", "Saldo bajo", None).startswith("[ALERTA]")
    assert _formatear_mensaje("task", "Conciliar", None).startswith("[TAREA]")
    assert _formatear_mensaje("info", "FYI", None).startswith("[INFO]")

def test_formatear_mensaje_incluye_contexto():
    res = _formatear_mensaje("info", "Factura creada", {"alegra_id": "12345"})
    assert "alegra_id=12345" in res


# ─── Mock DB helper ──────────────────────────────────────────────────────────

def _make_mock_db():
    db = MagicMock()
    audit = MagicMock()
    audit.insert_one = AsyncMock()
    audit.count_documents = AsyncMock(return_value=0)
    audit.find_one = AsyncMock(return_value=None)
    db.whatsapp_internal_audit = audit
    return db


# ─── notificar_interno ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_notificar_persona_invalida():
    db = _make_mock_db()
    res = await notificar_interno(db, "perez", "info", "hola")
    assert res["success"] is False
    assert "persona invalida" in res["error"]


@pytest.mark.asyncio
async def test_notificar_nivel_invalido():
    db = _make_mock_db()
    res = await notificar_interno(db, "andres", "urgente", "hola")
    assert res["success"] is False
    assert "nivel invalido" in res["error"]


@pytest.mark.asyncio
async def test_notificar_mensaje_vacio():
    db = _make_mock_db()
    res = await notificar_interno(db, "andres", "info", "  ")
    assert res["success"] is False
    assert "vacio" in res["error"]


@pytest.mark.asyncio
async def test_notificar_skip_si_no_telefono(monkeypatch):
    monkeypatch.delenv("INTERNAL_WA_ANDRES", raising=False)
    db = _make_mock_db()
    res = await notificar_interno(db, "andres", "info", "hola")
    assert res["success"] is False
    assert res["skip"] == "no_telefono"
    db.whatsapp_internal_audit.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_notificar_skip_si_max_diario(monkeypatch):
    monkeypatch.setenv("INTERNAL_WA_ANDRES", "3001234567")
    db = _make_mock_db()
    db.whatsapp_internal_audit.count_documents = AsyncMock(return_value=10)
    res = await notificar_interno(db, "andres", "info", "msg #11")
    assert res["success"] is False
    assert res["skip"] == "max_diario_alcanzado"
    db.whatsapp_internal_audit.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_notificar_skip_si_duplicado_1h(monkeypatch):
    monkeypatch.setenv("INTERNAL_WA_IVAN", "3001234568")
    db = _make_mock_db()
    # No alcanza max diario pero find_one detecta duplicado
    db.whatsapp_internal_audit.count_documents = AsyncMock(return_value=2)
    db.whatsapp_internal_audit.find_one = AsyncMock(return_value={"_id": "x", "hash": "abc"})
    res = await notificar_interno(db, "ivan", "alerta", "saldo bajo")
    assert res["success"] is False
    assert res["skip"] == "duplicado_1h"


@pytest.mark.asyncio
async def test_notificar_envio_exitoso_via_send_text(monkeypatch):
    monkeypatch.setenv("INTERNAL_WA_FABIAN", "3001234569")
    db = _make_mock_db()

    fake_client = MagicMock()
    fake_client.send_text = AsyncMock(return_value={
        "success": True, "message_id": "msg-123",
    })
    fake_client.send_template = AsyncMock()  # no se debe llamar

    with patch(
        "services.mercately.internal_notifications.get_mercately_client",
        return_value=fake_client,
    ):
        res = await notificar_interno(
            db, "fabian", "task",
            "Conciliar Bancolombia 2029 antes de mañana",
            contexto={"banco": "bancolombia_2029"},
        )

    assert res["success"] is True
    assert res["via"] == "send_text"
    assert res["message_id"] == "msg-123"
    assert res["persona"] == "fabian"
    assert res["telefono"] == "573001234569"
    fake_client.send_text.assert_awaited_once()
    fake_client.send_template.assert_not_awaited()
    db.whatsapp_internal_audit.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_notificar_fallback_a_template_si_send_text_falla(monkeypatch):
    monkeypatch.setenv("INTERNAL_WA_ANDRES", "3001234567")
    monkeypatch.setenv("MERCATELY_TEMPLATE_INTERNO_ID", "tpl-uuid-123")
    db = _make_mock_db()

    fake_client = MagicMock()
    fake_client.send_text = AsyncMock(return_value={
        "success": False, "error": "fuera de ventana 24h",
    })
    fake_client.send_template = AsyncMock(return_value={
        "success": True, "message_id": "tpl-msg-456",
    })

    with patch(
        "services.mercately.internal_notifications.get_mercately_client",
        return_value=fake_client,
    ):
        res = await notificar_interno(db, "andres", "alerta", "saldo bajo BBVA")

    assert res["success"] is True
    assert res["via"] == "template"
    assert res["message_id"] == "tpl-msg-456"
    fake_client.send_text.assert_awaited_once()
    fake_client.send_template.assert_awaited_once()


@pytest.mark.asyncio
async def test_notificar_error_si_fallan_ambos_y_no_hay_template(monkeypatch):
    monkeypatch.setenv("INTERNAL_WA_ANDRES", "3001234567")
    monkeypatch.delenv("MERCATELY_TEMPLATE_INTERNO_ID", raising=False)
    db = _make_mock_db()

    fake_client = MagicMock()
    fake_client.send_text = AsyncMock(return_value={
        "success": False, "error": "fuera de ventana 24h",
    })

    with patch(
        "services.mercately.internal_notifications.get_mercately_client",
        return_value=fake_client,
    ):
        res = await notificar_interno(db, "andres", "info", "hola")

    assert res["success"] is False
    assert "error" in res
