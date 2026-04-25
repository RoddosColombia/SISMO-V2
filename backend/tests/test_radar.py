"""
Tests para el módulo RADAR de alertas de cobranza.

test_enviar_alertas_no_miercoles    — si hoy no es miércoles, retorna sin envíos
test_enviar_alertas_dry_run         — dry_run calcula destinatarios sin llamar Mercately
test_limpiar_telefono               — normalización de números colombianos
test_skip_sin_telefono              — loanbook sin teléfono → skip, no error
"""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────── Fixture: mock db ────────────────────────────────────

def _make_db(loanbooks: list[dict] | None = None) -> MagicMock:
    """Mock de Motor db con colección loanbook y radar_alertas."""
    db = MagicMock()

    # loanbook.find().to_list()
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=loanbooks or [])
    db.loanbook = MagicMock()
    db.loanbook.find = MagicMock(return_value=mock_cursor)

    # radar_alertas.insert_one()
    db.radar_alertas = MagicMock()
    db.radar_alertas.insert_one = AsyncMock()

    return db


def _loanbook(
    lb_id: str = "LB-001",
    nombre: str = "Juan Pérez",
    telefono: str = "573001234567",
    cuota_monto: float = 120_000,
    dpd: int = 0,
    mora_cop: float = 0,
    fecha_cuota_hoy: bool = False,
    hoy_str: str = "2026-04-29",   # miércoles fijo para tests
) -> dict:
    """Construye un documento loanbook mínimo para tests."""
    cuotas = []
    if fecha_cuota_hoy:
        cuotas.append({
            "numero": 1,
            "monto": cuota_monto,
            "estado": "pendiente",
            "fecha": hoy_str,
        })
    return {
        "loanbook_id": lb_id,
        "estado": "activo",
        "cliente": {"nombre": nombre, "telefono": telefono},
        "cuota_monto": cuota_monto,
        "cuotas": cuotas,
        "dpd": dpd,
        "mora_acumulada_cop": mora_cop,
    }


# ─────────────────────── Test 1 — no es miércoles ────────────────────────────

@pytest.mark.asyncio
async def test_enviar_alertas_no_miercoles():
    """Si hoy no es miércoles, la función retorna inmediatamente sin envíos."""
    from agents.radar.alertas import enviar_alertas_cobro

    db = _make_db()

    # Parchamos today_bogota() para que devuelva un lunes (weekday=0)
    lunes = date(2026, 4, 27)  # lunes
    assert lunes.weekday() == 0, "El fixture debe ser lunes"

    with patch("agents.radar.alertas.today_bogota", return_value=lunes):
        result = await enviar_alertas_cobro(db, dry_run=False)

    assert result["es_miercoles"] is False
    assert result["alertas_cobro"] == 0
    assert result["alertas_mora"] == 0
    assert result["errores"] == 0
    # No debe haber llamado a loanbook.find
    db.loanbook.find.assert_not_called()


# ─────────────────────── Test 2 — dry_run ────────────────────────────────────

@pytest.mark.asyncio
async def test_enviar_alertas_dry_run():
    """En dry_run=True, calcula destinatarios pero NO llama a Mercately."""
    from agents.radar.alertas import enviar_alertas_cobro

    hoy = date(2026, 4, 29)   # miércoles fijo
    assert hoy.weekday() == 2, "El fixture debe ser miércoles"
    hoy_str = hoy.isoformat()

    lb = _loanbook(fecha_cuota_hoy=True, hoy_str=hoy_str, dpd=3, mora_cop=6000)
    db = _make_db(loanbooks=[lb])

    with (
        patch("agents.radar.alertas.today_bogota", return_value=hoy),
        patch.dict("os.environ", {
            "MERCATELY_TEMPLATE_COBRO_ID": "uuid-cobro",
            "MERCATELY_TEMPLATE_MORA_ID":  "uuid-mora",
            "MERCATELY_API_KEY": "test-key",
        }),
        # MercatelyClient.send_template NO debe llamarse en dry_run
        patch("agents.radar.alertas.MercatelyClient") as mock_mercately_cls,
    ):
        mock_client = MagicMock()
        mock_client.send_template = AsyncMock(return_value={"success": True, "message_id": "x"})
        mock_mercately_cls.return_value = mock_client

        result = await enviar_alertas_cobro(db, dry_run=True)

    assert result["es_miercoles"] is True
    assert result["dry_run"] is True
    # Cobro + mora identificados para este loanbook
    assert result["alertas_cobro"] == 1
    assert result["alertas_mora"] == 1
    # Mercately NO debe haberse llamado en dry_run
    mock_client.send_template.assert_not_called()
    # radar_alertas NO debe escribirse en dry_run
    db.radar_alertas.insert_one.assert_not_called()


# ─────────────────────── Test 3 — limpieza de teléfono ───────────────────────

def test_limpiar_telefono():
    """Normalización de números de teléfono colombianos."""
    from services.mercately.client import _limpiar_telefono

    # Ya tiene código de país y formato correcto
    assert _limpiar_telefono("573001234567") == "573001234567"

    # Tiene + al inicio
    assert _limpiar_telefono("+573001234567") == "573001234567"

    # Solo 10 dígitos (celular colombiano sin código)
    assert _limpiar_telefono("3001234567") == "573001234567"

    # Con espacios y guiones
    assert _limpiar_telefono("+57 300 123-4567") == "573001234567"

    # Con paréntesis
    assert _limpiar_telefono("+57 (300) 123 4567") == "573001234567"


# ─────────────────────── Test 4 — skip sin teléfono ─────────────────────────

@pytest.mark.asyncio
async def test_skip_sin_telefono():
    """Loanbook sin teléfono → skip, sin error, sin llamada a Mercately."""
    from agents.radar.alertas import enviar_alertas_cobro

    hoy = date(2026, 4, 29)  # miércoles
    hoy_str = hoy.isoformat()

    lb_sin_tel = _loanbook(
        lb_id="LB-002",
        telefono="",            # sin teléfono
        fecha_cuota_hoy=True,
        hoy_str=hoy_str,
    )
    # Limpiar el campo telefono del dict cliente
    lb_sin_tel["cliente"]["telefono"] = ""

    db = _make_db(loanbooks=[lb_sin_tel])

    with (
        patch("agents.radar.alertas.today_bogota", return_value=hoy),
        patch.dict("os.environ", {
            "MERCATELY_TEMPLATE_COBRO_ID": "uuid-cobro",
            "MERCATELY_TEMPLATE_MORA_ID":  "uuid-mora",
            "MERCATELY_API_KEY": "test-key",
        }),
        patch("agents.radar.alertas.MercatelyClient") as mock_mercately_cls,
    ):
        mock_client = MagicMock()
        mock_client.send_template = AsyncMock()
        mock_mercately_cls.return_value = mock_client

        result = await enviar_alertas_cobro(db, dry_run=False)

    assert result["skipped"] == 1
    assert result["alertas_cobro"] == 0
    assert result["errores"] == 0
    mock_client.send_template.assert_not_called()
