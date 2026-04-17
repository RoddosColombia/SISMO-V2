"""
Tests for Plan Separe module.

Reglas:
  - request_with_verify() en POST abono (si falla → no guarda en MongoDB)
  - Abono lleva a 100% → estado "completada"
  - Notificar Contador solo si completada
  - Cambiar moto solo si < 50% pagado
  - Cancelar bloquea si estado == facturada
  - Stats calcula matrículas y dinero retenido
"""
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from routers.plan_separe import (
    BANCOS_ID,
    CUENTA_ANTICIPOS,
    MATRICULA_PROVISION,
    CambiarMotoBody,
    CancelarBody,
    CrearSeparacionBody,
    MarcarFacturadaBody,
    NotificarContadorBody,
    RegistrarAbonoBody,
    _compute_fields,
    cambiar_moto,
    cancelar_separacion,
    crear_separacion,
    get_separacion,
    listar_separaciones,
    marcar_facturada,
    notificar_contador,
    plan_separe_stats,
    registrar_abono,
)


# ═══════════════════════════════════════════
# Mock DB helpers
# ═══════════════════════════════════════════


def _mock_cursor(docs: list[dict]):
    cur = MagicMock()
    cur.sort = MagicMock(return_value=cur)
    cur.skip = MagicMock(return_value=cur)
    cur.limit = MagicMock(return_value=cur)
    cur.to_list = AsyncMock(return_value=docs)
    return cur


def _mock_db_with_separaciones(docs: list[dict] | None = None, *, existing_doc: dict | None = None):
    """Common mock shape for plan_separe_separaciones."""
    docs = docs or []
    db = MagicMock()
    db.plan_separe_separaciones = MagicMock()
    db.plan_separe_separaciones.find_one = AsyncMock(return_value=existing_doc)
    db.plan_separe_separaciones.find = MagicMock(return_value=_mock_cursor(docs))
    db.plan_separe_separaciones.insert_one = AsyncMock()
    db.plan_separe_separaciones.update_one = AsyncMock()
    db.plan_separe_separaciones.count_documents = AsyncMock(return_value=len(docs))
    db.plan_separe_notificaciones = MagicMock()
    db.plan_separe_notificaciones.insert_one = AsyncMock()
    return db


def _base_doc(
    sep_id: str = "PS-2026-001",
    total_abonado: float = 0,
    estado: str = "activa",
    cuota_inicial: float = 1_460_000,
) -> dict:
    abonos = [{"monto": total_abonado, "fecha": "2026-04-16", "banco": "bancolombia_2029"}] if total_abonado else []
    return {
        "separacion_id": sep_id,
        "cliente": {"cc": "123", "nombre": "Test Cliente", "telefono": "3001234567", "tipo_documento": "CC"},
        "moto": {"modelo": "Raider 125", "cuota_inicial_requerida": cuota_inicial, "precio_venta": 8_000_000},
        "abonos": abonos,
        "estado": estado,
        "fecha_creacion": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════
# _compute_fields
# ═══════════════════════════════════════════


def test_compute_fields_calculates_saldo_and_pct():
    doc = _base_doc(total_abonado=500_000)
    result = _compute_fields(doc)
    assert result["total_abonado"] == 500_000
    assert result["saldo_pendiente"] == 960_000
    assert result["porcentaje_pagado"] == round((500_000 / 1_460_000) * 100, 2)


def test_compute_fields_100_percent():
    doc = _base_doc(total_abonado=1_460_000)
    result = _compute_fields(doc)
    assert result["saldo_pendiente"] == 0
    assert result["porcentaje_pagado"] == 100


# ═══════════════════════════════════════════
# crear_separacion
# ═══════════════════════════════════════════


@pytest.mark.asyncio
async def test_crear_separacion_happy_path():
    db = _mock_db_with_separaciones(existing_doc=None)
    db.plan_separe_separaciones.find = MagicMock(return_value=_mock_cursor([]))
    body = CrearSeparacionBody(
        cliente_cc="6998154", cliente_nombre="Antony Rico",
        cliente_telefono="3001234567", moto_modelo="Raider 125",
        cuota_inicial=1_460_000,
    )
    result = await crear_separacion(body, db=db)
    assert result["separacion_id"].startswith("PS-")
    assert result["estado"] == "activa"
    assert result["saldo_pendiente"] == 1_460_000
    db.plan_separe_separaciones.insert_one.assert_called_once()


@pytest.mark.asyncio
async def test_crear_separacion_rechaza_duplicado():
    existing = _base_doc()
    db = _mock_db_with_separaciones(existing_doc=existing)
    body = CrearSeparacionBody(
        cliente_cc="123", cliente_nombre="Test",
        moto_modelo="Raider 125", cuota_inicial=1_460_000,
    )
    with pytest.raises(HTTPException) as exc:
        await crear_separacion(body, db=db)
    assert exc.value.status_code == 409


# ═══════════════════════════════════════════
# registrar_abono
# ═══════════════════════════════════════════


class _MockAlegra:
    """Fake AlegraClient — tracks request_with_verify() calls."""

    def __init__(self, should_fail: bool = False, fail_message: str = "Alegra caído"):
        self.calls: list[dict] = []
        self.should_fail = should_fail
        self.fail_message = fail_message

    async def request_with_verify(self, *, endpoint, method, payload):
        self.calls.append({"endpoint": endpoint, "method": method, "payload": payload})
        if self.should_fail:
            from services.alegra.client import AlegraError
            raise AlegraError(self.fail_message)
        return {"id": "J-PS-001", "_alegra_id": "J-PS-001"}


@pytest.mark.asyncio
async def test_abono_llega_a_99_no_completa():
    existing = _base_doc(total_abonado=0)
    db = _mock_db_with_separaciones(existing_doc=existing)
    # Second find_one returns fresh state (after update)
    fresh = _base_doc(total_abonado=1_400_000)  # 95%
    db.plan_separe_separaciones.find_one = AsyncMock(side_effect=[existing, fresh])

    alegra = _MockAlegra()
    body = RegistrarAbonoBody(monto=1_400_000, banco="bancolombia_2029")
    result = await registrar_abono("PS-2026-001", body, db=db, alegra=alegra)

    assert result["estado"] == "activa"  # sigue activa
    assert len(alegra.calls) == 1  # Un solo journal
    call = alegra.calls[0]
    assert call["endpoint"] == "journals"
    # Partida doble: debit banco + credit 5370
    entries = call["payload"]["entries"]
    assert entries[0]["id"] == "5314" and entries[0]["debit"] == 1_400_000
    assert entries[1]["id"] == "5370" and entries[1]["credit"] == 1_400_000


@pytest.mark.asyncio
async def test_abono_llega_a_100_completa():
    existing = _base_doc(total_abonado=960_000)
    fresh = _base_doc(total_abonado=1_460_000, estado="completada")
    db = _mock_db_with_separaciones(existing_doc=existing)
    db.plan_separe_separaciones.find_one = AsyncMock(side_effect=[existing, fresh])

    alegra = _MockAlegra()
    body = RegistrarAbonoBody(monto=500_000, banco="bancolombia_2029")
    result = await registrar_abono("PS-2026-001", body, db=db, alegra=alegra)

    assert result["estado"] == "completada"
    # Check update_one was called with estado completada
    call_args = db.plan_separe_separaciones.update_one.call_args
    update_set = call_args[0][1]["$set"]
    assert update_set["estado"] == "completada"
    assert "fecha_100porciento" in update_set


@pytest.mark.asyncio
async def test_abono_alegra_falla_no_guarda_en_mongo():
    """ROG-1: Si request_with_verify falla, NO se guarda el abono en MongoDB."""
    existing = _base_doc(total_abonado=0)
    db = _mock_db_with_separaciones(existing_doc=existing)

    alegra = _MockAlegra(should_fail=True, fail_message="HTTP 500")
    body = RegistrarAbonoBody(monto=500_000, banco="bancolombia_2029")
    with pytest.raises(HTTPException) as exc:
        await registrar_abono("PS-2026-001", body, db=db, alegra=alegra)
    assert exc.value.status_code == 502
    # update_one NO se llamó (no se guardó nada)
    db.plan_separe_separaciones.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_abono_excede_saldo_pendiente_rechaza():
    existing = _base_doc(total_abonado=1_000_000)
    db = _mock_db_with_separaciones(existing_doc=existing)
    alegra = _MockAlegra()
    body = RegistrarAbonoBody(monto=500_000, banco="bancolombia_2029")  # 1M + 500k > 1.46M
    with pytest.raises(HTTPException) as exc:
        await registrar_abono("PS-2026-001", body, db=db, alegra=alegra)
    assert exc.value.status_code == 400
    assert "excede" in exc.value.detail.lower() or "saldo" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_abono_banco_invalido_rechaza():
    existing = _base_doc()
    db = _mock_db_with_separaciones(existing_doc=existing)
    alegra = _MockAlegra()
    body = RegistrarAbonoBody(monto=500_000, banco="btc")
    with pytest.raises(HTTPException) as exc:
        await registrar_abono("PS-2026-001", body, db=db, alegra=alegra)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_multiples_abonos_suma_correcta():
    # Abono 1: 500k, abono 2: 460k — total 960k
    doc_after_1 = _base_doc(total_abonado=500_000)
    doc_after_2 = _base_doc(total_abonado=960_000)
    db = _mock_db_with_separaciones(existing_doc=_base_doc(total_abonado=500_000))
    db.plan_separe_separaciones.find_one = AsyncMock(side_effect=[doc_after_1, doc_after_2])
    alegra = _MockAlegra()
    body = RegistrarAbonoBody(monto=460_000, banco="bbva_0210")
    result = await registrar_abono("PS-2026-001", body, db=db, alegra=alegra)
    assert result["total_abonado"] == 960_000
    assert result["saldo_pendiente"] == 500_000


# ═══════════════════════════════════════════
# notificar_contador
# ═══════════════════════════════════════════


@pytest.mark.asyncio
async def test_notificar_contador_rechaza_si_no_completada():
    existing = _base_doc(estado="activa")
    db = _mock_db_with_separaciones(existing_doc=existing)
    body = NotificarContadorBody(notificado_por="liz")
    with pytest.raises(HTTPException) as exc:
        await notificar_contador("PS-2026-001", body, db=db)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_notificar_contador_ok_cuando_completada():
    existing = _base_doc(total_abonado=1_460_000, estado="completada")
    db = _mock_db_with_separaciones(existing_doc=existing)
    body = NotificarContadorBody(notificado_por="liz")
    result = await notificar_contador("PS-2026-001", body, db=db)
    assert "instruccion_contador" in result
    assert "PS-2026-001" in result["instruccion_contador"]
    db.plan_separe_notificaciones.insert_one.assert_called_once()


# ═══════════════════════════════════════════
# cambiar_moto
# ═══════════════════════════════════════════


@pytest.mark.asyncio
async def test_cambiar_moto_permite_si_menos_50pct():
    existing = _base_doc(total_abonado=500_000)  # 34%
    db = _mock_db_with_separaciones(existing_doc=existing)
    body = CambiarMotoBody(moto_modelo="Sport 100", razon="cliente cambió de opinión")
    result = await cambiar_moto("PS-2026-001", body, db=db)
    assert result["moto_modelo"] == "Sport 100"


@pytest.mark.asyncio
async def test_cambiar_moto_rechaza_si_50pct_o_mas():
    existing = _base_doc(total_abonado=1_000_000)  # ~68%
    db = _mock_db_with_separaciones(existing_doc=existing)
    body = CambiarMotoBody(moto_modelo="Sport 100")
    with pytest.raises(HTTPException) as exc:
        await cambiar_moto("PS-2026-001", body, db=db)
    assert exc.value.status_code == 400


# ═══════════════════════════════════════════
# cancelar
# ═══════════════════════════════════════════


@pytest.mark.asyncio
async def test_cancelar_permite_en_activa():
    existing = _base_doc(estado="activa")
    db = _mock_db_with_separaciones(existing_doc=existing)
    body = CancelarBody(razon="cliente se arrepintió")
    result = await cancelar_separacion("PS-2026-001", body, db=db)
    assert result["estado"] == "cancelada"


@pytest.mark.asyncio
async def test_cancelar_rechaza_en_facturada():
    existing = _base_doc(estado="facturada")
    db = _mock_db_with_separaciones(existing_doc=existing)
    body = CancelarBody(razon="x")
    with pytest.raises(HTTPException) as exc:
        await cancelar_separacion("PS-2026-001", body, db=db)
    assert exc.value.status_code == 400


# ═══════════════════════════════════════════
# stats (CFO widget)
# ═══════════════════════════════════════════


@pytest.mark.asyncio
async def test_stats_matriculas_calculation():
    # 2 completadas + 4 activas = 6 total; matriculas 2 × 580k actual, 6 × 580k proyectado
    cursor_docs = [
        {"estado": "completada", "abonos": [{"monto": 1_460_000}]},
        {"estado": "completada", "abonos": [{"monto": 1_460_000}]},
        {"estado": "activa", "abonos": [{"monto": 500_000}]},
        {"estado": "activa", "abonos": [{"monto": 500_000}]},
        {"estado": "activa", "abonos": [{"monto": 600_000}]},
        {"estado": "activa", "abonos": [{"monto": 600_000}]},
    ]

    # Mock async iteration
    class AsyncIter:
        def __init__(self, items): self.items = list(items)
        def __aiter__(self): return self
        async def __anext__(self):
            if not self.items: raise StopAsyncIteration
            return self.items.pop(0)

    db = MagicMock()
    db.plan_separe_separaciones = MagicMock()
    db.plan_separe_separaciones.find = MagicMock(return_value=AsyncIter(cursor_docs))
    db.plan_separe_separaciones.count_documents = AsyncMock(return_value=0)

    stats = await plan_separe_stats(db=db)
    # 1_460_000 * 2 + 500_000 * 2 + 600_000 * 2 = 5_120_000
    assert stats["total_retenido"] == 5_120_000
    assert stats["matriculas_provision_actual"] == 2 * MATRICULA_PROVISION
    assert stats["matriculas_provision_proyectada"] == 6 * MATRICULA_PROVISION
    assert stats["por_estado"]["activa"] == 4
    assert stats["por_estado"]["completada"] == 2


# ═══════════════════════════════════════════
# Constantes de catálogo
# ═══════════════════════════════════════════


def test_cuenta_anticipos_es_5370():
    """ID 5370 corresponde al code 2805 'Anticipos y avances recibidos'."""
    assert CUENTA_ANTICIPOS == "5370"


def test_bancos_ids_reales():
    """Deben ser los IDs reales verificados en CLAUDE.md."""
    assert BANCOS_ID["bancolombia_2029"] == "5314"
    assert BANCOS_ID["bbva_0210"] == "5318"
    assert BANCOS_ID["davivienda_482"] == "5322"
