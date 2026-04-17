"""
PATCH /api/plan-separe/{id} tests.

Coverage:
  - Valid edit of cliente_nombre → success + audit entry
  - cuota_inicial_esperada <= 0 → 422
  - cedula duplicada en otra activa → 422
  - Separación facturada → 423 Locked
  - Campo read-only en body → 422
  - Edit sin motivo → success (motivo es opcional)
  - audit[] contiene user_email del JWT
  - Publica evento plan_separe.editada al bus
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from routers.plan_separe import editar_separacion


def _base_doc(sep_id="PS-2026-TEST", estado="activa", cc="999",
              cuota_inicial=1_460_000):
    return {
        "separacion_id": sep_id,
        "cliente": {"cc": cc, "nombre": "Test Cliente", "telefono": "3000000000",
                    "tipo_documento": "CC"},
        "moto": {"modelo": "Raider 125", "cuota_inicial_requerida": cuota_inicial,
                 "precio_venta": 8_000_000},
        "estado": estado,
        "abonos": [], "total_abonado": 0,
    }


def _db_with(doc: dict | None, dup_doc: dict | None = None):
    db = MagicMock()
    db.plan_separe_separaciones = MagicMock()

    async def _find_one(q):
        # Uniqueness check: query with cliente.cc + estado != current id
        if "cliente.cc" in q and q.get("separacion_id", {}).get("$ne"):
            return dup_doc
        # Single fetch by separacion_id
        if q.get("separacion_id") == (doc or {}).get("separacion_id"):
            return doc
        return None

    db.plan_separe_separaciones.find_one = AsyncMock(side_effect=_find_one)
    db.plan_separe_separaciones.update_one = AsyncMock()
    db.roddos_events = MagicMock()
    db.roddos_events.insert_one = AsyncMock()
    return db


USER = {"email": "liz@roddos.com", "role": "contador"}


# ── Valid edits ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_nombre_success_appends_audit_and_publishes_event():
    fresh = _base_doc()
    fresh["cliente"]["nombre"] = "Nuevo Nombre"
    fresh["audit"] = [{"user_email": "liz@roddos.com"}]

    db = _db_with(_base_doc())
    # Second find_one (for fresh read after update)
    calls = {"n": 0}
    async def find_seq(q):
        calls["n"] += 1
        if calls["n"] == 1:
            return _base_doc()
        return fresh
    db.plan_separe_separaciones.find_one = AsyncMock(side_effect=find_seq)

    with patch("routers.plan_separe.publish_event", new_callable=AsyncMock) as pub:
        result = await editar_separacion(
            "PS-2026-TEST",
            raw={"cliente_nombre": "Nuevo Nombre", "motivo": "Actualización por cliente"},
            db=db, current_user=USER,
        )

    assert result["modificado"] is True
    assert any(c["campo"] == "cliente.nombre" for c in result["cambios"])
    # Audit entry pushed
    update_call = db.plan_separe_separaciones.update_one.call_args
    assert "$push" in update_call.args[1]
    audit = update_call.args[1]["$push"]["audit"]
    assert audit["user_email"] == "liz@roddos.com"
    assert audit["motivo"] == "Actualización por cliente"
    assert len(audit["campos_modificados"]) == 1
    # Event published
    pub.assert_called_once()
    assert pub.call_args.kwargs["event_type"] == "plan_separe.editada"


@pytest.mark.asyncio
async def test_patch_sin_motivo_es_valido():
    """motivo es opcional — se persiste como null."""
    db = _db_with(_base_doc())
    calls = {"n": 0}
    async def find_seq(q):
        calls["n"] += 1
        return _base_doc() if calls["n"] == 1 else {**_base_doc(), "cliente": {"cc": "999", "nombre": "X", "tipo_documento": "CC"}}
    db.plan_separe_separaciones.find_one = AsyncMock(side_effect=find_seq)

    with patch("routers.plan_separe.publish_event", new_callable=AsyncMock):
        result = await editar_separacion(
            "PS-2026-TEST",
            raw={"cliente_nombre": "X"},
            db=db, current_user=USER,
        )
    assert result["modificado"] is True


@pytest.mark.asyncio
async def test_patch_audit_entry_incluye_user_email_del_jwt():
    db = _db_with(_base_doc())
    calls = {"n": 0}
    async def find_seq(q):
        calls["n"] += 1
        return _base_doc() if calls["n"] == 1 else _base_doc()
    db.plan_separe_separaciones.find_one = AsyncMock(side_effect=find_seq)

    with patch("routers.plan_separe.publish_event", new_callable=AsyncMock):
        await editar_separacion(
            "PS-2026-TEST",
            raw={"cliente_nombre": "X"},
            db=db, current_user={"email": "andres@roddos.com"},
        )
    audit = db.plan_separe_separaciones.update_one.call_args.args[1]["$push"]["audit"]
    assert audit["user_email"] == "andres@roddos.com"


# ── Validations ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_cuota_inicial_cero_rechaza_422():
    db = _db_with(_base_doc())
    with pytest.raises(HTTPException) as exc:
        await editar_separacion(
            "PS-2026-TEST",
            raw={"cuota_inicial_esperada": 0},
            db=db, current_user=USER,
        )
    assert exc.value.status_code == 422
    assert "> 0" in exc.value.detail


@pytest.mark.asyncio
async def test_patch_cedula_duplicada_otra_activa_rechaza_422():
    db = _db_with(
        _base_doc(cc="111"),
        dup_doc={"separacion_id": "PS-2026-OTHER", "cliente": {"cc": "222"}, "estado": "activa"},
    )
    with pytest.raises(HTTPException) as exc:
        await editar_separacion(
            "PS-2026-TEST",
            raw={"cliente_documento_numero": "222"},
            db=db, current_user=USER,
        )
    assert exc.value.status_code == 422
    assert "ya tiene separación activa" in exc.value.detail


@pytest.mark.asyncio
async def test_patch_facturada_rechaza_423():
    db = _db_with(_base_doc(estado="facturada"))
    with pytest.raises(HTTPException) as exc:
        await editar_separacion(
            "PS-2026-TEST",
            raw={"cliente_nombre": "X"},
            db=db, current_user=USER,
        )
    assert exc.value.status_code == 423
    assert "facturada" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_patch_readonly_field_rechaza_422():
    db = _db_with(_base_doc())
    with pytest.raises(HTTPException) as exc:
        await editar_separacion(
            "PS-2026-TEST",
            raw={"estado": "completada"},
            db=db, current_user=USER,
        )
    assert exc.value.status_code == 422
    assert "read-only" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_patch_campo_desconocido_rechaza_422():
    db = _db_with(_base_doc())
    with pytest.raises(HTTPException) as exc:
        await editar_separacion(
            "PS-2026-TEST",
            raw={"unknown_field": "x"},
            db=db, current_user=USER,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_patch_tipo_doc_invalido_rechaza_422():
    db = _db_with(_base_doc())
    with pytest.raises(HTTPException) as exc:
        await editar_separacion(
            "PS-2026-TEST",
            raw={"cliente_documento_tipo": "NIT"},  # not in valid set
            db=db, current_user=USER,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_patch_evento_publicado_con_cambios():
    db = _db_with(_base_doc())
    calls = {"n": 0}
    async def find_seq(q):
        calls["n"] += 1
        return _base_doc() if calls["n"] == 1 else _base_doc()
    db.plan_separe_separaciones.find_one = AsyncMock(side_effect=find_seq)

    with patch("routers.plan_separe.publish_event", new_callable=AsyncMock) as pub:
        await editar_separacion(
            "PS-2026-TEST",
            raw={"cuota_inicial_esperada": 1_500_000, "motivo": "Ajuste"},
            db=db, current_user=USER,
        )
    pub.assert_called_once()
    kwargs = pub.call_args.kwargs
    assert kwargs["event_type"] == "plan_separe.editada"
    assert kwargs["source"] == "router.plan_separe"
    datos = kwargs["datos"]
    assert datos["separacion_id"] == "PS-2026-TEST"
    assert datos["motivo"] == "Ajuste"
    assert len(datos["campos_modificados"]) == 1
