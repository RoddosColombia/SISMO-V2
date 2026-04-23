"""
test_b5_comprobantes.py — Tests para POST/GET /cuotas/{n}/comprobante

Cubre:
- Subida exitosa JPEG, PNG, PDF
- Tipo MIME inválido → 422
- Cuota anterior 22-abr-2026 rechazada
- Cuota exactamente 22-abr-2026 permitida
- Imagen/PDF > límite → 422
- GET comprobante existente → ok
- GET sin comprobante → 404
- GET loanbook inexistente → 404
- Metadata correctamente guardada
"""
import io
import base64
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from bson import ObjectId


# ─────────────────────── Helpers ──────────────────────────────────────────────

def make_cuota(numero: int, fecha: str, con_comprobante: bool = False) -> dict:
    c: dict = {
        "numero": numero,
        "fecha_programada": fecha,
        "fecha": fecha,
        "estado": "pendiente",
        "monto": 80_000,
        "monto_total": 80_000,
        "monto_capital": 70_000,
        "monto_interes": 10_000,
    }
    if con_comprobante:
        c["comprobante"] = {
            "filename": "recibo.jpg",
            "content_type": "image/jpeg",
            "data_b64": base64.b64encode(b"FAKEIMG").decode(),
            "uploaded_at": datetime(2026, 4, 25),
            "uploaded_by": "admin",
            "size_bytes": 1024,
        }
    return c


def make_lb(cuotas=None):
    return {
        "_id": ObjectId(),
        "loanbook_id": "LB-0001",
        "cuotas": cuotas or [],
    }


def make_db(lb=None, found=True):
    db = MagicMock()
    db.loanbook.find_one = AsyncMock(return_value=lb if found else None)
    db.loanbook.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    return db


def make_upload_file(content: bytes, content_type: str, filename: str = "file.jpg"):
    f = MagicMock()
    f.content_type = content_type
    f.filename = filename
    f.read = AsyncMock(return_value=content)
    return f


def make_user():
    return {"id": "admin"}


# ─────────────────────── Tests subir_comprobante ──────────────────────────────

class TestSubirComprobante:

    @pytest.mark.asyncio
    async def test_subir_jpeg_ok(self):
        from routers.loanbook import subir_comprobante
        cuotas = [make_cuota(1, "2026-04-22")]
        lb = make_lb(cuotas)
        db = make_db(lb)
        file = make_upload_file(b"JPEG_DATA", "image/jpeg", "comprobante.jpg")

        result = await subir_comprobante("LB-0001", 1, file, db, make_user())

        assert result["ok"] is True
        assert result["cuota"] == 1
        assert result["filename"] == "comprobante.jpg"
        db.loanbook.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_subir_png_ok(self):
        from routers.loanbook import subir_comprobante
        cuotas = [make_cuota(1, "2026-05-01")]
        lb = make_lb(cuotas)
        db = make_db(lb)
        file = make_upload_file(b"PNG_DATA", "image/png", "foto.png")

        result = await subir_comprobante("LB-0001", 1, file, db, make_user())
        assert result["ok"] is True
        assert result["tipo"] == "image/png"

    @pytest.mark.asyncio
    async def test_subir_pdf_ok(self):
        from routers.loanbook import subir_comprobante
        cuotas = [make_cuota(1, "2026-06-01")]
        lb = make_lb(cuotas)
        db = make_db(lb)
        file = make_upload_file(b"PDF_DATA", "application/pdf", "comprobante.pdf")

        result = await subir_comprobante("LB-0001", 1, file, db, make_user())
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_tipo_invalido_422(self):
        from routers.loanbook import subir_comprobante
        from fastapi import HTTPException
        cuotas = [make_cuota(1, "2026-04-22")]
        lb = make_lb(cuotas)
        db = make_db(lb)
        file = make_upload_file(b"DATA", "application/zip", "archivo.zip")

        with pytest.raises(HTTPException) as exc_info:
            await subir_comprobante("LB-0001", 1, file, db, make_user())
        assert exc_info.value.status_code == 422
        assert "Tipo no permitido" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_cuota_anterior_abril22_rechazada(self):
        from routers.loanbook import subir_comprobante
        from fastapi import HTTPException
        cuotas = [make_cuota(1, "2026-04-01")]  # antes del mínimo
        lb = make_lb(cuotas)
        db = make_db(lb)
        file = make_upload_file(b"DATA", "image/jpeg")

        with pytest.raises(HTTPException) as exc_info:
            await subir_comprobante("LB-0001", 1, file, db, make_user())
        assert exc_info.value.status_code == 422
        assert "22 de abril" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_cuota_abril22_exacto_permitida(self):
        from routers.loanbook import subir_comprobante
        cuotas = [make_cuota(1, "2026-04-22")]  # exactamente el mínimo — OK
        lb = make_lb(cuotas)
        db = make_db(lb)
        file = make_upload_file(b"DATA", "image/jpeg")

        result = await subir_comprobante("LB-0001", 1, file, db, make_user())
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_imagen_muy_grande_422(self):
        from routers.loanbook import subir_comprobante
        from fastapi import HTTPException
        cuotas = [make_cuota(1, "2026-04-22")]
        lb = make_lb(cuotas)
        db = make_db(lb)
        # 2MB + 1 byte
        file = make_upload_file(b"X" * (2 * 1024 * 1024 + 1), "image/jpeg")

        with pytest.raises(HTTPException) as exc_info:
            await subir_comprobante("LB-0001", 1, file, db, make_user())
        assert exc_info.value.status_code == 422
        assert "grande" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_pdf_muy_grande_422(self):
        from routers.loanbook import subir_comprobante
        from fastapi import HTTPException
        cuotas = [make_cuota(1, "2026-04-22")]
        lb = make_lb(cuotas)
        db = make_db(lb)
        # 5MB + 1 byte
        file = make_upload_file(b"X" * (5 * 1024 * 1024 + 1), "application/pdf")

        with pytest.raises(HTTPException) as exc_info:
            await subir_comprobante("LB-0001", 1, file, db, make_user())
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_cuota_inexistente_404(self):
        from routers.loanbook import subir_comprobante
        from fastapi import HTTPException
        cuotas = [make_cuota(1, "2026-04-22")]
        lb = make_lb(cuotas)
        db = make_db(lb)
        file = make_upload_file(b"DATA", "image/jpeg")

        with pytest.raises(HTTPException) as exc_info:
            await subir_comprobante("LB-0001", 99, file, db, make_user())  # cuota 99 no existe
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_comprobante_guarda_metadata_correcta(self):
        from routers.loanbook import subir_comprobante
        cuotas = [make_cuota(1, "2026-04-22")]
        lb = make_lb(cuotas)
        db = make_db(lb)
        contenido = b"JPEG_CONTENT"
        file = make_upload_file(contenido, "image/jpeg", "pago_semana1.jpg")

        await subir_comprobante("LB-0001", 1, file, db, make_user())

        set_dict = db.loanbook.update_one.call_args[0][1]["$set"]
        comp = set_dict["cuotas.0.comprobante"]
        assert comp["filename"] == "pago_semana1.jpg"
        assert comp["content_type"] == "image/jpeg"
        assert comp["size_bytes"] == len(contenido)
        # Verificar que data_b64 es base64 válido
        decoded = base64.b64decode(comp["data_b64"])
        assert decoded == contenido


# ─────────────────────── Tests obtener_comprobante ────────────────────────────

class TestObtenerComprobante:

    @pytest.mark.asyncio
    async def test_obtener_comprobante_existente_ok(self):
        from routers.loanbook import obtener_comprobante
        cuotas = [make_cuota(1, "2026-04-22", con_comprobante=True)]
        lb = make_lb(cuotas)
        db = make_db(lb)

        result = await obtener_comprobante("LB-0001", 1, db, make_user())

        assert result["filename"] == "recibo.jpg"
        assert result["content_type"] == "image/jpeg"
        assert "data_b64" in result
        assert result["size_kb"] > 0

    @pytest.mark.asyncio
    async def test_obtener_comprobante_sin_comprobante_404(self):
        from routers.loanbook import obtener_comprobante
        from fastapi import HTTPException
        cuotas = [make_cuota(1, "2026-04-22", con_comprobante=False)]
        lb = make_lb(cuotas)
        db = make_db(lb)

        with pytest.raises(HTTPException) as exc_info:
            await obtener_comprobante("LB-0001", 1, db, make_user())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_obtener_loanbook_inexistente_404(self):
        from routers.loanbook import obtener_comprobante
        from fastapi import HTTPException
        db = make_db(found=False)

        with pytest.raises(HTTPException) as exc_info:
            await obtener_comprobante("LB-XXXX", 1, db, make_user())
        assert exc_info.value.status_code == 404
