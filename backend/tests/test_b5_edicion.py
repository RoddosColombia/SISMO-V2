"""
test_b5_edicion.py — Tests para PATCH /api/loanbook/{codigo}/editar

Cubre:
- Actualización exitosa de campos editables
- Campos protegidos ignorados
- Registro de audit log en loanbook_modificaciones
- 404 para loanbook inexistente
- 400 cuando todos los campos están protegidos
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from bson import ObjectId


# ─────────────────────── Fixtures ─────────────────────────────────────────────

def make_lb(**overrides):
    base = {
        "_id": ObjectId(),
        "loanbook_id": "LB-0001",
        "loanbook_codigo": "LB-0001",
        "estado": "activo",
        "cliente": {"nombre": "Ana Torres", "cedula": "12345678", "telefono": "3001234567", "ciudad": "Bogotá"},
        "tasa_ea": 0.39,
        "vendedor": "Carlos",
        "score_riesgo": "A+",
        "cuotas": [],
        "updated_at": datetime(2026, 4, 1),
    }
    base.update(overrides)
    return base


def make_db(lb=None):
    db = MagicMock()
    lb_doc = lb or make_lb()
    db.loanbook.find_one = AsyncMock(return_value=lb_doc)
    db.loanbook.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    db.loanbook_modificaciones.insert_one = AsyncMock(return_value=MagicMock())
    return db, lb_doc


def make_user():
    return {"id": "admin", "sub": "admin", "role": "admin"}


# ─────────────────────── Tests ─────────────────────────────────────────────────

class TestEditarLoanbook:

    @pytest.mark.asyncio
    async def test_patch_actualiza_mongodb(self):
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        result = await editar_loanbook(
            codigo="LB-0001",
            campos={"vendedor": "Nuevo Vendedor", "score_riesgo": "B"},
            db=db,
            current_user=make_user(),
        )

        assert result["ok"] is True
        assert "vendedor" in result["campos_actualizados"]
        assert "score_riesgo" in result["campos_actualizados"]
        db.loanbook.update_one.assert_called_once()
        call_args = db.loanbook.update_one.call_args
        set_dict = call_args[0][1]["$set"]
        assert set_dict["vendedor"] == "Nuevo Vendedor"
        assert set_dict["score_riesgo"] == "B"

    @pytest.mark.asyncio
    async def test_patch_campos_protegidos_ignorados(self):
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        result = await editar_loanbook(
            codigo="LB-0001",
            campos={
                "_id": "hacker",
                "loanbook_id": "LB-9999",
                "cuotas": [{"numero": 1}],
                "estado": "saldado",
                "vendedor": "Valido",
            },
            db=db,
            current_user=make_user(),
        )

        assert result["ok"] is True
        set_dict = db.loanbook.update_one.call_args[0][1]["$set"]
        assert "_id" not in set_dict
        assert "loanbook_id" not in set_dict
        assert "cuotas" not in set_dict
        assert "estado" not in set_dict
        assert set_dict.get("vendedor") == "Valido"

    @pytest.mark.asyncio
    async def test_patch_registra_audit_log(self):
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        await editar_loanbook(
            codigo="LB-0001",
            campos={"vendedor": "Nuevo", "score_riesgo": "C"},
            db=db,
            current_user=make_user(),
        )

        # Debe registrar una entrada por campo modificado
        assert db.loanbook_modificaciones.insert_one.call_count == 2

    @pytest.mark.asyncio
    async def test_patch_loanbook_inexistente_404(self):
        from routers.loanbook import editar_loanbook
        from fastapi import HTTPException
        db = MagicMock()
        db.loanbook.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await editar_loanbook(
                codigo="LB-XXXX",
                campos={"vendedor": "Test"},
                db=db,
                current_user=make_user(),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_campos_vacios_400(self):
        from routers.loanbook import editar_loanbook
        from fastapi import HTTPException
        db, lb = make_db()

        # Solo campos protegidos → 400
        with pytest.raises(HTTPException) as exc_info:
            await editar_loanbook(
                codigo="LB-0001",
                campos={"_id": "x", "estado": "saldado"},
                db=db,
                current_user=make_user(),
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_patch_updated_at_no_en_audit_log(self):
        """updated_at no debe generar entrada en audit log."""
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        await editar_loanbook(
            codigo="LB-0001",
            campos={"vendedor": "Test"},
            db=db,
            current_user=make_user(),
        )
        # Solo 1 campo real + updated_at → 1 entrada en audit (no 2)
        assert db.loanbook_modificaciones.insert_one.call_count == 1

    @pytest.mark.asyncio
    async def test_patch_retorna_loanbook_actualizado(self):
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        result = await editar_loanbook(
            codigo="LB-0001",
            campos={"tasa_ea": 0.42},
            db=db,
            current_user=make_user(),
        )

        assert "loanbook" in result
        assert isinstance(result["loanbook"], dict)
        assert "_id" not in result["loanbook"]

    @pytest.mark.asyncio
    async def test_patch_multiples_campos(self):
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        campos = {
            "vendedor": "Juan",
            "score_riesgo": "A",
            "tasa_ea": 0.45,
            "factura_alegra_id": "FAC-999",
        }
        result = await editar_loanbook(
            codigo="LB-0001",
            campos=campos,
            db=db,
            current_user=make_user(),
        )

        assert result["ok"] is True
        assert len(result["campos_actualizados"]) == 4
        assert db.loanbook_modificaciones.insert_one.call_count == 4

    @pytest.mark.asyncio
    async def test_patch_campos_actualizados_no_incluye_updated_at(self):
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        result = await editar_loanbook(
            codigo="LB-0001",
            campos={"vendedor": "Test"},
            db=db,
            current_user=make_user(),
        )

        assert "updated_at" not in result["campos_actualizados"]

    @pytest.mark.asyncio
    async def test_patch_solo_un_campo(self):
        from routers.loanbook import editar_loanbook
        db, lb = make_db()

        result = await editar_loanbook(
            codigo="LB-0001",
            campos={"score_riesgo": "B+"},
            db=db,
            current_user=make_user(),
        )

        assert result["ok"] is True
        assert result["campos_actualizados"] == ["score_riesgo"]

    @pytest.mark.asyncio
    async def test_patch_preserva_campos_no_modificados(self):
        from routers.loanbook import editar_loanbook
        db, lb = make_db(make_lb(estado="activo", loanbook_id="LB-0001"))

        result = await editar_loanbook(
            codigo="LB-0001",
            campos={"vendedor": "Nuevo"},
            db=db,
            current_user=make_user(),
        )

        # No toca estado ni loanbook_id
        set_dict = db.loanbook.update_one.call_args[0][1]["$set"]
        assert "estado" not in set_dict
        assert "loanbook_id" not in set_dict
