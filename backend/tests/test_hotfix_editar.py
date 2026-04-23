"""
test_hotfix_editar.py — Verifica que PATCH /editar persiste correctamente en MongoDB.

Foco crítico: el bug original era campos: dict sin Body(...) → FastAPI no parseaba el body.
Ahora el test verifica que update_one se llama con los campos correctos y retorna modified=1.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from bson import ObjectId


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_lb(**overrides):
    base = {
        "_id": ObjectId(),
        "loanbook_id": "LB-2026-0001",
        "estado": "activo",
        "vendedor": "Carlos",
        "score_riesgo": "A+",
        "cuotas": [],
    }
    base.update(overrides)
    return base


def make_update_result(matched=1, modified=1):
    r = MagicMock()
    r.matched_count = matched
    r.modified_count = modified
    return r


def make_db(lb=None):
    db = MagicMock()
    lb_doc = lb or make_lb()
    db.loanbook.find_one = AsyncMock(return_value=lb_doc)
    db.loanbook.update_one = AsyncMock(return_value=make_update_result())
    db.loanbook_modificaciones.insert_one = AsyncMock(return_value=MagicMock())
    return db, lb_doc


def make_user():
    return {"id": "admin", "sub": "admin"}


# ─── Tests críticos ────────────────────────────────────────────────────────────

class TestPatchEditarPersiste:

    @pytest.mark.asyncio
    async def test_patch_editar_persiste_en_mongodb(self):
        """Caso crítico: update_one se llama con los campos correctos."""
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        result = await editar_loanbook(
            codigo="LB-2026-0001",
            campos={"vendedor": "Ivan Echeverri"},
            db=db,
            current_user=make_user(),
        )

        # update_one fue llamado
        db.loanbook.update_one.assert_called_once()
        # El filtro usa _id del documento encontrado
        call_filter = db.loanbook.update_one.call_args[0][0]
        assert call_filter == {"_id": lb["_id"]}
        # El $set contiene el campo correcto
        call_update = db.loanbook.update_one.call_args[0][1]
        assert call_update["$set"]["vendedor"] == "Ivan Echeverri"
        # Respuesta incluye ok=True y modified
        assert result["ok"] is True
        assert result["modified"] == 1

    @pytest.mark.asyncio
    async def test_patch_editar_retorna_modified_1(self):
        """modified_count=1 confirmado en respuesta."""
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        result = await editar_loanbook(
            codigo="LB-2026-0001",
            campos={"score_riesgo": "B"},
            db=db,
            current_user=make_user(),
        )

        assert result["matched"] == 1
        assert result["modified"] == 1

    @pytest.mark.asyncio
    async def test_patch_editar_campos_protegidos_ignorados(self):
        """_id, loanbook_id, cuotas, estado no deben llegar a MongoDB."""
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        result = await editar_loanbook(
            codigo="LB-2026-0001",
            campos={
                "_id": "hack",
                "loanbook_id": "LB-9999",
                "cuotas": [{"numero": 99}],
                "estado": "saldado",
                "vendedor": "Valido",
            },
            db=db,
            current_user=make_user(),
        )

        assert result["ok"] is True
        set_dict = db.loanbook.update_one.call_args[0][1]["$set"]
        for protegido in ("_id", "loanbook_id", "cuotas", "estado"):
            assert protegido not in set_dict
        assert set_dict["vendedor"] == "Valido"

    @pytest.mark.asyncio
    async def test_patch_editar_loanbook_inexistente_404(self):
        """Retorna 404 cuando el loanbook no existe."""
        from routers.loanbook import editar_loanbook
        from fastapi import HTTPException
        db = MagicMock()
        db.loanbook.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await editar_loanbook(
                codigo="LB-GHOST",
                campos={"vendedor": "Test"},
                db=db,
                current_user=make_user(),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_editar_campos_vacios_400(self):
        """Solo campos protegidos → 400."""
        from routers.loanbook import editar_loanbook
        from fastapi import HTTPException
        db, lb = make_db()

        with pytest.raises(HTTPException) as exc_info:
            await editar_loanbook(
                codigo="LB-2026-0001",
                campos={"_id": "x", "estado": "saldado"},
                db=db,
                current_user=make_user(),
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_patch_busca_por_loanbook_id(self):
        """La búsqueda usa $or con loanbook_id, loanbook_codigo, vin."""
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        await editar_loanbook(
            codigo="LB-2026-0001",
            campos={"vendedor": "Test"},
            db=db,
            current_user=make_user(),
        )

        # find_one fue llamado dos veces: primero con $or, luego con _id para lb_actualizado
        # Usamos call_args_list[0] para la primera llamada (la búsqueda inicial)
        call_query = db.loanbook.find_one.call_args_list[0][0][0]
        assert "$or" in call_query
        or_fields = [list(cond.keys())[0] for cond in call_query["$or"]]
        assert "loanbook_id" in or_fields

    @pytest.mark.asyncio
    async def test_patch_registra_audit_log(self):
        """Cada campo modificado genera una entrada en loanbook_modificaciones."""
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        await editar_loanbook(
            codigo="LB-2026-0001",
            campos={"vendedor": "Ivan", "score_riesgo": "B"},
            db=db,
            current_user=make_user(),
        )

        assert db.loanbook_modificaciones.insert_one.call_count == 2

    @pytest.mark.asyncio
    async def test_patch_multiples_campos_todos_persisten(self):
        """Múltiples campos en un solo PATCH llegan todos a $set."""
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        campos = {
            "vendedor": "Juan",
            "tasa_ea": 0.42,
            "factura_alegra_id": "FAC-001",
        }
        result = await editar_loanbook(
            codigo="LB-2026-0001",
            campos=campos,
            db=db,
            current_user=make_user(),
        )

        set_dict = db.loanbook.update_one.call_args[0][1]["$set"]
        assert set_dict["vendedor"] == "Juan"
        assert set_dict["tasa_ea"] == 0.42
        assert set_dict["factura_alegra_id"] == "FAC-001"
        assert result["ok"] is True
        assert len(result["campos_actualizados"]) == 3

    @pytest.mark.asyncio
    async def test_patch_updated_at_no_en_campos_actualizados(self):
        """updated_at se añade internamente pero no aparece en campos_actualizados."""
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        result = await editar_loanbook(
            codigo="LB-2026-0001",
            campos={"vendedor": "Test"},
            db=db,
            current_user=make_user(),
        )

        assert "updated_at" not in result["campos_actualizados"]
        # Pero sí está en el $set de MongoDB
        set_dict = db.loanbook.update_one.call_args[0][1]["$set"]
        assert "updated_at" in set_dict

    @pytest.mark.asyncio
    async def test_patch_audit_log_fallo_no_rompe_operacion(self):
        """Si el audit log falla, la operación principal debe completarse igual."""
        from routers.loanbook import editar_loanbook
        db, lb = make_db()
        db.loanbook_modificaciones.insert_one = AsyncMock(side_effect=Exception("MongoDB error"))

        # No debe lanzar excepción
        result = await editar_loanbook(
            codigo="LB-2026-0001",
            campos={"vendedor": "Test"},
            db=db,
            current_user=make_user(),
        )
        assert result["ok"] is True
