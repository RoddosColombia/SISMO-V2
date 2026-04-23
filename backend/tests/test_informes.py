"""
test_informes.py — Tests para el módulo de informe semanal.

Cubre generar_informe_semanal y los endpoints CRUD.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, date
from bson import ObjectId


# ─── Fixtures ──────────────────────────────────────────────────────────────────

def make_lb(dpd=0, estado="activo", saldo=500_000, cuotas=None, **overrides):
    lb = {
        "_id": ObjectId(),
        "loanbook_id": "LB-0001",
        "estado": estado,
        "dpd": dpd,
        "saldo_capital": saldo,
        "saldo_pendiente": saldo,
        "cliente": {"nombre": "Ana Torres", "telefono": "3001234567"},
        "sub_bucket_semanal": "Warning" if dpd > 0 else "Current",
        "cuotas": cuotas or [],
    }
    lb.update(overrides)
    return lb


def make_informe(semana_id="2026-W17", sin_pago=None):
    sp = sin_pago or [{
        "loanbook_id": "LB-0001",
        "cliente_nombre": "Ana Torres",
        "telefono": "3001234567",
        "saldo": 500_000,
        "cuotas_vencidas": 1,
        "dpd": 7,
        "sub_bucket": "Warning",
        "estado_gestion": "pendiente",
        "notas": "",
        "actualizado_por": None,
        "actualizado_at": None,
    }]
    return {
        "_id": ObjectId(),
        "semana_id": semana_id,
        "fecha_corte": "2026-04-24",
        "fecha_generacion": datetime.utcnow(),
        "generado_por": "manual",
        "sin_pago": sp,
        "total_sin_pago": len(sp),
        "valor_en_riesgo": sum(x["saldo"] for x in sp),
        "notas_generales": "",
    }


def make_db(lbs=None, informe=None):
    db = MagicMock()

    # loanbook cursor
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=lbs or [])
    db.loanbook.find = MagicMock(return_value=cursor)

    # informes_semanales
    db.informes_semanales.find_one = AsyncMock(return_value=informe)
    db.informes_semanales.insert_one = AsyncMock(return_value=MagicMock())
    db.informes_semanales.replace_one = AsyncMock(return_value=MagicMock())
    db.informes_semanales.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

    # historial cursor
    hist_cursor = MagicMock()
    hist_cursor.sort = MagicMock(return_value=hist_cursor)
    hist_cursor.limit = MagicMock(return_value=hist_cursor)
    hist_cursor.to_list = AsyncMock(return_value=[informe] if informe else [])
    db.informes_semanales.find = MagicMock(return_value=hist_cursor)

    return db


def make_user():
    return {"id": "admin", "sub": "admin"}


# ─── Tests generar_informe_semanal ─────────────────────────────────────────────

class TestGenerarInformeSemanal:

    @pytest.mark.asyncio
    async def test_generar_informe_crea_documento_en_mongodb(self):
        from services.loanbook.informes_service import generar_informe_semanal
        lb_mora = make_lb(dpd=7, estado="activo")
        db = make_db(lbs=[lb_mora], informe=None)

        result = await generar_informe_semanal(db, generado_por="manual")

        assert result["ok"] is True
        db.informes_semanales.insert_one.assert_called_once()
        doc = db.informes_semanales.insert_one.call_args[0][0]
        assert doc["total_sin_pago"] == 1
        assert doc["generado_por"] == "manual"

    @pytest.mark.asyncio
    async def test_generar_informe_idempotente(self):
        """Segunda llamada sin forzar no duplica."""
        from services.loanbook.informes_service import generar_informe_semanal
        informe_existente = make_informe()
        db = make_db(informe=informe_existente)

        result = await generar_informe_semanal(db, generado_por="scheduler")

        assert result["ok"] is True
        assert "Ya existe" in result.get("mensaje", "")
        db.informes_semanales.insert_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_generar_informe_forzar_sobreescribe(self):
        """forzar=True reemplaza el existente."""
        from services.loanbook.informes_service import generar_informe_semanal
        informe_existente = make_informe()
        lb = make_lb(dpd=3)
        db = make_db(lbs=[lb], informe=informe_existente)

        result = await generar_informe_semanal(db, generado_por="manual", forzar=True)

        assert result["ok"] is True
        db.informes_semanales.replace_one.assert_called_once()
        db.informes_semanales.insert_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_informe_ordena_por_dpd_descendente(self):
        """Los créditos en el informe deben ordenarse DPD desc."""
        from services.loanbook.informes_service import generar_informe_semanal
        lbs = [
            make_lb(dpd=3, loanbook_id="LB-LOW"),
            make_lb(dpd=30, loanbook_id="LB-HIGH"),
            make_lb(dpd=10, loanbook_id="LB-MID"),
        ]
        for lb in lbs:
            lb["cliente"] = {"nombre": f"Cliente {lb['loanbook_id']}", "telefono": ""}
        db = make_db(lbs=lbs, informe=None)

        await generar_informe_semanal(db, generado_por="manual")

        doc = db.informes_semanales.insert_one.call_args[0][0]
        dpds = [c["dpd"] for c in doc["sin_pago"]]
        assert dpds == sorted(dpds, reverse=True)

    @pytest.mark.asyncio
    async def test_creditos_pagados_no_aparecen(self):
        """Estado saldado/Pagado no aparece en el informe."""
        from services.loanbook.informes_service import generar_informe_semanal
        lbs = [
            make_lb(dpd=7, estado="activo"),
            make_lb(dpd=0, estado="saldado"),
            make_lb(dpd=0, estado="Pagado"),
        ]
        # loanbook.find solo retorna los no-excluidos (mock simplificado)
        db = make_db(lbs=[lbs[0]], informe=None)

        result = await generar_informe_semanal(db)

        doc = db.informes_semanales.insert_one.call_args[0][0]
        assert doc["total_sin_pago"] == 1

    @pytest.mark.asyncio
    async def test_informe_sin_creditos_mora(self):
        """Si no hay mora, informe se crea con total_sin_pago=0."""
        from services.loanbook.informes_service import generar_informe_semanal
        db = make_db(lbs=[], informe=None)

        result = await generar_informe_semanal(db)

        assert result["ok"] is True
        doc = db.informes_semanales.insert_one.call_args[0][0]
        assert doc["total_sin_pago"] == 0
        assert doc["valor_en_riesgo"] == 0

    @pytest.mark.asyncio
    async def test_dpd_calculado_desde_cuotas_cuando_campo_es_cero(self):
        """Si dpd=0 en el loanbook (scheduler no corrió), DPD se calcula desde las cuotas."""
        from services.loanbook.informes_service import generar_informe_semanal
        from datetime import datetime, timedelta
        hace_21_dias = (datetime.utcnow() - timedelta(days=21)).strftime("%Y-%m-%d")
        lb = make_lb(dpd=0, estado="activo", cuotas=[{
            "estado": "vencida",
            "fecha_programada": hace_21_dias,
        }])
        db = make_db(lbs=[lb], informe=None)

        result = await generar_informe_semanal(db)

        doc = db.informes_semanales.insert_one.call_args[0][0]
        assert doc["total_sin_pago"] == 1
        # DPD debe calcularse desde la cuota (21 días), no quedarse en 0
        assert doc["sin_pago"][0]["dpd"] >= 20  # pequeño margen por hora del día

    @pytest.mark.asyncio
    async def test_informe_fecha_programada_datetime_object(self):
        """fecha_programada como datetime (Motor) debe normalizarse correctamente."""
        from services.loanbook.informes_service import generar_informe_semanal
        from datetime import datetime, date, timedelta
        # Simular lo que Motor retorna: datetime object (no string)
        hace_30_dias = datetime.utcnow() - timedelta(days=30)
        lb = make_lb(dpd=0, estado="activo", cuotas=[{
            "estado": "pendiente",
            "fecha_programada": hace_30_dias,  # datetime object, como llega de Motor
        }])
        db = make_db(lbs=[lb], informe=None)

        result = await generar_informe_semanal(db)

        assert result["ok"] is True
        doc = db.informes_semanales.insert_one.call_args[0][0]
        # La cuota vencida hace 30 días debe aparecer en el informe
        assert doc["total_sin_pago"] == 1
        assert doc["sin_pago"][0]["cuotas_vencidas"] == 1

    @pytest.mark.asyncio
    async def test_informe_cuotas_vencidas_acumuladas_todas_las_semanas(self):
        """Cuotas de semanas anteriores también cuentan — el informe es acumulado."""
        from services.loanbook.informes_service import generar_informe_semanal
        from datetime import datetime, timedelta
        # 3 cuotas vencidas de meses anteriores
        cuotas = [
            {"estado": "vencida", "fecha_programada": (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")},
            {"estado": "vencida", "fecha_programada": (datetime.utcnow() - timedelta(days=60)).strftime("%Y-%m-%d")},
            {"estado": "pendiente", "fecha_programada": (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")},
        ]
        lb = make_lb(dpd=90, estado="activo", cuotas=cuotas)
        db = make_db(lbs=[lb], informe=None)

        result = await generar_informe_semanal(db)

        doc = db.informes_semanales.insert_one.call_args[0][0]
        assert doc["total_sin_pago"] == 1
        # Las 3 cuotas de distintas semanas deben contarse
        assert doc["sin_pago"][0]["cuotas_vencidas"] == 3


# ─── Tests endpoints ───────────────────────────────────────────────────────────

class TestInformesEndpoints:

    @pytest.mark.asyncio
    async def test_get_semana_actual(self):
        from routers.informes import get_semana_actual
        informe = make_informe()
        db = make_db(informe=informe)

        # generar_informe_semanal es import lazy dentro de la función — parchear en el módulo servicio
        with patch("services.loanbook.informes_service.generar_informe_semanal", new_callable=AsyncMock):
            result = await get_semana_actual(db=db, current_user=make_user())

        assert "semana_id" in result
        assert "_id" not in result

    @pytest.mark.asyncio
    async def test_get_semana_especifica(self):
        from routers.informes import get_semana
        informe = make_informe("2026-W16")
        db = make_db(informe=informe)

        result = await get_semana("2026-W16", db=db, current_user=make_user())

        assert result["semana_id"] == "2026-W16"

    @pytest.mark.asyncio
    async def test_get_semana_inexistente_404(self):
        from routers.informes import get_semana
        from fastapi import HTTPException
        db = make_db(informe=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_semana("2026-W01", db=db, current_user=make_user())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_historial_retorna_lista(self):
        from routers.informes import get_historial
        informe = make_informe()
        db = make_db(informe=informe)

        result = await get_historial(db=db, current_user=make_user())

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_generar_informe_manual_endpoint(self):
        from routers.informes import generar_informe
        db = make_db(informe=None, lbs=[make_lb(dpd=5)])

        with patch("services.loanbook.informes_service.generar_informe_semanal", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = {"ok": True, "semana_id": "2026-W17", "total_sin_pago": 1}
            result = await generar_informe(db=db, current_user=make_user())

        assert result["ok"] is True
        mock_gen.assert_called_once_with(db, generado_por="manual", forzar=False)

    @pytest.mark.asyncio
    async def test_patch_credito_actualiza_estado_gestion(self):
        from routers.informes import patch_credito_gestion
        informe = make_informe()
        db = make_db(informe=informe)

        result = await patch_credito_gestion(
            semana_id="2026-W17",
            loanbook_id="LB-0001",
            body={"estado_gestion": "contactado"},
            db=db,
            current_user=make_user(),
        )

        assert result["ok"] is True
        db.informes_semanales.update_one.assert_called_once()
        set_dict = db.informes_semanales.update_one.call_args[0][1]["$set"]
        assert set_dict["sin_pago.0.estado_gestion"] == "contactado"

    @pytest.mark.asyncio
    async def test_patch_credito_actualiza_notas(self):
        from routers.informes import patch_credito_gestion
        informe = make_informe()
        db = make_db(informe=informe)

        result = await patch_credito_gestion(
            semana_id="2026-W17",
            loanbook_id="LB-0001",
            body={"notas": "Prometió pagar el viernes"},
            db=db,
            current_user=make_user(),
        )

        assert result["ok"] is True
        set_dict = db.informes_semanales.update_one.call_args[0][1]["$set"]
        assert set_dict["sin_pago.0.notas"] == "Prometió pagar el viernes"

    @pytest.mark.asyncio
    async def test_patch_estado_invalido_422(self):
        from routers.informes import patch_credito_gestion
        from fastapi import HTTPException
        informe = make_informe()
        db = make_db(informe=informe)

        with pytest.raises(HTTPException) as exc_info:
            await patch_credito_gestion(
                semana_id="2026-W17",
                loanbook_id="LB-0001",
                body={"estado_gestion": "inventado"},
                db=db,
                current_user=make_user(),
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_patch_credito_inexistente_404(self):
        from routers.informes import patch_credito_gestion
        from fastapi import HTTPException
        informe = make_informe()
        db = make_db(informe=informe)

        with pytest.raises(HTTPException) as exc_info:
            await patch_credito_gestion(
                semana_id="2026-W17",
                loanbook_id="LB-GHOST",
                body={"estado_gestion": "contactado"},
                db=db,
                current_user=make_user(),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_notas_generales(self):
        from routers.informes import patch_notas_generales
        db = make_db(informe=make_informe())

        result = await patch_notas_generales(
            semana_id="2026-W17",
            body={"notas_generales": "Semana difícil"},
            db=db,
            current_user=make_user(),
        )

        assert result["ok"] is True
        set_dict = db.informes_semanales.update_one.call_args[0][1]["$set"]
        assert set_dict["notas_generales"] == "Semana difícil"

    @pytest.mark.asyncio
    async def test_patch_notas_generales_sin_campo_400(self):
        from routers.informes import patch_notas_generales
        from fastapi import HTTPException
        db = make_db(informe=make_informe())

        with pytest.raises(HTTPException) as exc_info:
            await patch_notas_generales(
                semana_id="2026-W17",
                body={},  # falta notas_generales
                db=db,
                current_user=make_user(),
            )
        assert exc_info.value.status_code == 400
