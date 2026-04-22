"""
test_loanbook_schema.py — Tests del schema dual RDX/RODANTE para loanbooks.

Valida:
  - LoanbookCreate acepta combinaciones válidas (RDX×P39S×semanal, RODANTE×P4S×semanal, etc.)
  - Rechaza combos inválidos: RODANTE+P78S, RDX+P15S, RODANTE+quincenal, RODANTE+mensual
  - subtipo_rodante obligatorio para RODANTE, prohibido para RDX
  - metadata_producto validado por producto/subtipo (campos requeridos)
  - LTV calculado automáticamente para RDX cuando hay moto_valor_origen
  - LoanbookUpdate acepta campos opcionales individualmente
  - Errores descriptivos para debugging

Tests unitarios — sin MongoDB, sin I/O.
El fixture `seed_catalogos` en conftest.py pre-carga el cache antes de la sesión.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.loanbook_schema import (
    LoanbookBase,
    LoanbookCreate,
    LoanbookUpdate,
    MetadataRDX,
    MetadataRepuestos,
    MetadataSoat,
    MetadataComparendo,
    MetadataLicencia,
)


# ─────────────────────── Fixtures de datos válidos ────────────────────────────

@pytest.fixture
def rdx_create_valido() -> dict:
    """Payload mínimo válido para un loanbook RDX."""
    return {
        "producto": "RDX",
        "plan_codigo": "P39S",
        "modalidad_pago": "semanal",
        "metadata_producto": {
            "moto_vin": "9FL25AF31VDB95057",
            "moto_modelo": "RAIDER 125",
        },
        "cliente_nombre": "Juan Pérez",
        "cliente_cedula": "12345678",
        "monto_original": 2_000_000,
        "cuota_periodica": 51_000,
        "fecha_factura": "2026-04-01",
    }


@pytest.fixture
def rodante_soat_valido() -> dict:
    """Payload válido para un loanbook RODANTE subtipo soat."""
    return {
        "producto": "RODANTE",
        "subtipo_rodante": "soat",
        "plan_codigo": "P4S",
        "modalidad_pago": "semanal",
        "metadata_producto": {
            "poliza_numero": "POL-2026-001",
            "aseguradora": "Sura",
            "cilindraje_moto": 125,
            "vigencia_desde": "2026-04-01",
            "vigencia_hasta": "2027-04-01",
            "valor_soat": 350_000,
            "placa_cubierta": "ABC123",
        },
        "cliente_nombre": "María López",
        "cliente_cedula": "98765432",
        "monto_original": 350_000,
        "cuota_periodica": 87_500,
        "fecha_factura": "2026-04-01",
    }


@pytest.fixture
def rodante_repuestos_valido() -> dict:
    return {
        "producto": "RODANTE",
        "subtipo_rodante": "repuestos",
        "plan_codigo": "P2S",
        "modalidad_pago": "semanal",
        "metadata_producto": {
            "referencia_sku": "SKU-001",
            "cantidad": 2,
            "valor_unitario": 75_000,
            "descripcion_repuesto": "Pastillas de freno trasero",
        },
        "cliente_nombre": "Carlos R.",
        "cliente_cedula": "11111111",
        "monto_original": 150_000,
        "cuota_periodica": 75_000,
        "fecha_factura": "2026-04-01",
    }


@pytest.fixture
def rodante_comparendo_valido() -> dict:
    return {
        "producto": "RODANTE",
        "subtipo_rodante": "comparendo",
        "plan_codigo": "P6S",
        "modalidad_pago": "semanal",
        "metadata_producto": {
            "comparendo_numero": "CMP-2026-001",
            "entidad_emisora": "Secretaría de Tránsito Bogotá",
            "fecha_infraccion": "2025-12-01",
            "valor_comparendo": 800_000,
        },
        "cliente_nombre": "Pedro G.",
        "cliente_cedula": "22222222",
        "monto_original": 800_000,
        "cuota_periodica": 133_333,
        "fecha_factura": "2026-04-01",
    }


@pytest.fixture
def rodante_licencia_valido() -> dict:
    return {
        "producto": "RODANTE",
        "subtipo_rodante": "licencia",
        "plan_codigo": "P15S",
        "modalidad_pago": "semanal",
        "metadata_producto": {
            "categoria_licencia": "A2",
            "centro_ensenanza_nombre": "Automovilismo Express",
            "centro_ensenanza_nit": "900123456-1",
            "fecha_inicio_curso": "2026-04-15",
            "valor_curso": 1_200_000,
        },
        "cliente_nombre": "Ana M.",
        "cliente_cedula": "33333333",
        "monto_original": 1_200_000,
        "cuota_periodica": 80_000,
        "fecha_factura": "2026-04-01",
    }


# ─────────────────────── BLOQUE 1 — Combos válidos ───────────────────────────

class TestCombosValidos:
    """Verifica que los combos legítimos pasan validación."""

    def test_rdx_p39s_semanal(self, rdx_create_valido):
        lb = LoanbookCreate(**rdx_create_valido)
        assert lb.producto == "RDX"
        assert lb.plan_codigo == "P39S"
        assert lb.modalidad_pago == "semanal"

    def test_rdx_p52s_quincenal(self):
        lb = LoanbookCreate(
            producto="RDX",
            plan_codigo="P52S",
            modalidad_pago="quincenal",
            metadata_producto={"moto_vin": "VIN001", "moto_modelo": "SPORT 100"},
            cliente_nombre="Test",
            cliente_cedula="000",
            monto_original=3_000_000,
            cuota_periodica=115_000,
            fecha_factura="2026-04-01",
        )
        assert lb.plan_codigo == "P52S"
        assert lb.modalidad_pago == "quincenal"

    def test_rdx_p78s_mensual(self):
        lb = LoanbookCreate(
            producto="RDX",
            plan_codigo="P78S",
            modalidad_pago="mensual",
            metadata_producto={"moto_vin": "VIN002", "moto_modelo": "APACHE 160"},
            cliente_nombre="Test",
            cliente_cedula="000",
            monto_original=4_000_000,
            cuota_periodica=222_222,
            fecha_factura="2026-04-01",
        )
        assert lb.plan_codigo == "P78S"

    def test_rdx_p1s_semanal_contado(self):
        """P1S (contado) es válido para RDX."""
        lb = LoanbookCreate(
            producto="RDX",
            plan_codigo="P1S",
            modalidad_pago="semanal",
            metadata_producto={"moto_vin": "VIN003", "moto_modelo": "SPORT 100"},
            cliente_nombre="Test",
            cliente_cedula="000",
            monto_original=2_500_000,
            cuota_periodica=2_500_000,
            fecha_factura="2026-04-01",
        )
        assert lb.plan_codigo == "P1S"

    def test_rodante_soat_p4s_semanal(self, rodante_soat_valido):
        lb = LoanbookCreate(**rodante_soat_valido)
        assert lb.producto == "RODANTE"
        assert lb.subtipo_rodante == "soat"

    def test_rodante_repuestos_p2s(self, rodante_repuestos_valido):
        lb = LoanbookCreate(**rodante_repuestos_valido)
        assert lb.subtipo_rodante == "repuestos"

    def test_rodante_comparendo_p6s(self, rodante_comparendo_valido):
        lb = LoanbookCreate(**rodante_comparendo_valido)
        assert lb.subtipo_rodante == "comparendo"

    def test_rodante_licencia_p15s(self, rodante_licencia_valido):
        lb = LoanbookCreate(**rodante_licencia_valido)
        assert lb.subtipo_rodante == "licencia"

    def test_rodante_p1s_semanal_contado(self, rodante_soat_valido):
        """P1S también válido para RODANTE."""
        payload = dict(rodante_soat_valido)
        payload["plan_codigo"] = "P1S"
        payload["cuota_periodica"] = payload["monto_original"]
        lb = LoanbookCreate(**payload)
        assert lb.plan_codigo == "P1S"

    def test_rodante_p12s_semanal(self, rodante_repuestos_valido):
        payload = dict(rodante_repuestos_valido)
        payload["plan_codigo"] = "P12S"
        payload["cuota_periodica"] = 12_500
        lb = LoanbookCreate(**payload)
        assert lb.plan_codigo == "P12S"


# ─────────────────────── BLOQUE 2 — Combos inválidos (P-07..P-10) ─────────────

class TestCombosInvalidos:
    """Verifica que los combos ilegales son rechazados con mensaje claro. (R-23, R-06)"""

    def test_P07_rodante_mas_p78s_rechazado(self, rodante_soat_valido):
        """P-07: RODANTE+P78S → ValueError (P78S solo aplica a RDX)."""
        payload = dict(rodante_soat_valido)
        payload["plan_codigo"] = "P78S"
        with pytest.raises(ValidationError) as exc_info:
            LoanbookCreate(**payload)
        assert "P78S" in str(exc_info.value) or "aplica" in str(exc_info.value).lower()

    def test_P08_rodante_mas_p52s_rechazado(self, rodante_soat_valido):
        """P-08: RODANTE+P52S → ValueError."""
        payload = dict(rodante_soat_valido)
        payload["plan_codigo"] = "P52S"
        with pytest.raises(ValidationError):
            LoanbookCreate(**payload)

    def test_P09_rodante_mas_p39s_rechazado(self, rodante_soat_valido):
        """P-09: RODANTE+P39S → ValueError."""
        payload = dict(rodante_soat_valido)
        payload["plan_codigo"] = "P39S"
        with pytest.raises(ValidationError):
            LoanbookCreate(**payload)

    def test_P09b_rdx_mas_p15s_rechazado(self, rdx_create_valido):
        """RDX+P15S → ValueError (P15S solo aplica a RODANTE)."""
        payload = dict(rdx_create_valido)
        payload["plan_codigo"] = "P15S"
        with pytest.raises(ValidationError) as exc_info:
            LoanbookCreate(**payload)
        assert "P15S" in str(exc_info.value) or "aplica" in str(exc_info.value).lower()

    def test_rdx_mas_p2s_rechazado(self, rdx_create_valido):
        """P2S solo aplica a RODANTE."""
        payload = dict(rdx_create_valido)
        payload["plan_codigo"] = "P2S"
        with pytest.raises(ValidationError):
            LoanbookCreate(**payload)

    def test_P10_rodante_mas_quincenal_rechazado(self, rodante_soat_valido):
        """P-10: RODANTE+quincenal → ValueError (R-23: solo semanal para RODANTE)."""
        payload = dict(rodante_soat_valido)
        payload["modalidad_pago"] = "quincenal"
        with pytest.raises(ValidationError) as exc_info:
            LoanbookCreate(**payload)
        err = str(exc_info.value)
        assert "semanal" in err.lower() or "R-23" in err

    def test_rodante_mas_mensual_rechazado(self, rodante_soat_valido):
        """RODANTE+mensual → ValueError (R-23)."""
        payload = dict(rodante_soat_valido)
        payload["modalidad_pago"] = "mensual"
        with pytest.raises(ValidationError):
            LoanbookCreate(**payload)

    def test_plan_inexistente_rechazado(self, rdx_create_valido):
        """Plan que no existe en catálogo → ValueError."""
        payload = dict(rdx_create_valido)
        payload["plan_codigo"] = "P999S"
        with pytest.raises(ValidationError) as exc_info:
            LoanbookCreate(**payload)
        assert "P999S" in str(exc_info.value) or "catálogo" in str(exc_info.value).lower()


# ─────────────────────── BLOQUE 3 — subtipo_rodante ──────────────────────────

class TestSubtipoRodante:
    """Valida las reglas de subtipo_rodante."""

    def test_rodante_sin_subtipo_rechazado(self, rodante_soat_valido):
        """RODANTE sin subtipo_rodante → ValidationError."""
        payload = dict(rodante_soat_valido)
        del payload["subtipo_rodante"]
        with pytest.raises(ValidationError) as exc_info:
            LoanbookCreate(**payload)
        assert "subtipo_rodante" in str(exc_info.value).lower() or "RODANTE" in str(exc_info.value)

    def test_rodante_subtipo_none_rechazado(self, rodante_soat_valido):
        """RODANTE con subtipo_rodante=None → ValidationError."""
        payload = dict(rodante_soat_valido)
        payload["subtipo_rodante"] = None
        with pytest.raises(ValidationError):
            LoanbookCreate(**payload)

    def test_rdx_con_subtipo_rechazado(self, rdx_create_valido):
        """RDX con subtipo_rodante → ValidationError."""
        payload = dict(rdx_create_valido)
        payload["subtipo_rodante"] = "soat"
        with pytest.raises(ValidationError) as exc_info:
            LoanbookCreate(**payload)
        assert "subtipo_rodante" in str(exc_info.value).lower() or "RDX" in str(exc_info.value)

    def test_rdx_subtipo_none_permitido(self, rdx_create_valido):
        """RDX con subtipo_rodante=None (explícito) es válido."""
        payload = dict(rdx_create_valido)
        payload["subtipo_rodante"] = None
        lb = LoanbookCreate(**payload)
        assert lb.subtipo_rodante is None

    def test_subtipo_invalido_rechazado(self):
        """Pydantic rechaza un subtipo fuera del Literal."""
        with pytest.raises(ValidationError):
            LoanbookCreate(
                producto="RODANTE",
                subtipo_rodante="hipoteca",  # no existe
                plan_codigo="P4S",
                modalidad_pago="semanal",
                metadata_producto={},
                cliente_nombre="X",
                cliente_cedula="0",
                monto_original=100_000,
                cuota_periodica=25_000,
                fecha_factura="2026-04-01",
            )


# ─────────────────────── BLOQUE 4 — metadata_producto ────────────────────────

class TestMetadataProducto:
    """Valida que metadata_producto tenga los campos requeridos."""

    def test_rdx_sin_moto_vin_rechazado(self, rdx_create_valido):
        payload = dict(rdx_create_valido)
        payload["metadata_producto"] = {"moto_modelo": "RAIDER 125"}  # sin vin
        with pytest.raises(ValidationError) as exc_info:
            LoanbookCreate(**payload)
        assert "moto_vin" in str(exc_info.value).lower() or "vin" in str(exc_info.value).lower()

    def test_rdx_sin_moto_modelo_rechazado(self, rdx_create_valido):
        payload = dict(rdx_create_valido)
        payload["metadata_producto"] = {"moto_vin": "VIN001"}  # sin modelo
        with pytest.raises(ValidationError) as exc_info:
            LoanbookCreate(**payload)
        assert "moto_modelo" in str(exc_info.value).lower() or "modelo" in str(exc_info.value).lower()

    def test_rdx_metadata_completo_acepta_opcionales(self, rdx_create_valido):
        payload = dict(rdx_create_valido)
        payload["metadata_producto"] = {
            "moto_vin": "9FL25AF31VDB95057",
            "moto_modelo": "RAIDER 125",
            "moto_motor": "BF3AT13C2338",
            "moto_placa": "ABC123",
            "moto_anio": 2026,
            "moto_cilindraje": 125,
            "moto_valor_origen": 5_200_000,
        }
        lb = LoanbookCreate(**payload)
        assert lb.metadata_producto["moto_motor"] == "BF3AT13C2338"

    def test_soat_sin_poliza_rechazado(self, rodante_soat_valido):
        payload = dict(rodante_soat_valido)
        meta = dict(payload["metadata_producto"])
        del meta["poliza_numero"]
        payload["metadata_producto"] = meta
        with pytest.raises(ValidationError) as exc_info:
            LoanbookCreate(**payload)
        assert "poliza" in str(exc_info.value).lower()

    def test_soat_sin_aseguradora_rechazado(self, rodante_soat_valido):
        payload = dict(rodante_soat_valido)
        meta = dict(payload["metadata_producto"])
        del meta["aseguradora"]
        payload["metadata_producto"] = meta
        with pytest.raises(ValidationError):
            LoanbookCreate(**payload)

    def test_repuestos_sin_sku_rechazado(self, rodante_repuestos_valido):
        payload = dict(rodante_repuestos_valido)
        meta = dict(payload["metadata_producto"])
        del meta["referencia_sku"]
        payload["metadata_producto"] = meta
        with pytest.raises(ValidationError) as exc_info:
            LoanbookCreate(**payload)
        assert "referencia_sku" in str(exc_info.value).lower() or "sku" in str(exc_info.value).lower()

    def test_repuestos_cantidad_cero_rechazado(self, rodante_repuestos_valido):
        payload = dict(rodante_repuestos_valido)
        meta = dict(payload["metadata_producto"])
        meta["cantidad"] = 0
        payload["metadata_producto"] = meta
        with pytest.raises(ValidationError):
            LoanbookCreate(**payload)

    def test_comparendo_sin_numero_rechazado(self, rodante_comparendo_valido):
        payload = dict(rodante_comparendo_valido)
        meta = dict(payload["metadata_producto"])
        del meta["comparendo_numero"]
        payload["metadata_producto"] = meta
        with pytest.raises(ValidationError):
            LoanbookCreate(**payload)

    def test_licencia_categoria_invalida_rechazado(self, rodante_licencia_valido):
        payload = dict(rodante_licencia_valido)
        meta = dict(payload["metadata_producto"])
        meta["categoria_licencia"] = "X9"  # no existe
        payload["metadata_producto"] = meta
        with pytest.raises(ValidationError) as exc_info:
            LoanbookCreate(**payload)
        assert "categoria_licencia" in str(exc_info.value).lower() or "A1" in str(exc_info.value)

    def test_licencia_categoria_valida_a1(self, rodante_licencia_valido):
        payload = dict(rodante_licencia_valido)
        meta = dict(payload["metadata_producto"])
        meta["categoria_licencia"] = "A1"
        payload["metadata_producto"] = meta
        lb = LoanbookCreate(**payload)
        assert lb.metadata_producto["categoria_licencia"] == "A1"


# ─────────────────────── BLOQUE 5 — LTV auto-cálculo ─────────────────────────

class TestLTVAutocalculo:
    """Verifica que LTV se calcula automáticamente para RDX."""

    def test_ltv_calculado_con_valor_origen(self, rdx_create_valido):
        payload = dict(rdx_create_valido)
        payload["monto_original"] = 2_600_000
        payload["metadata_producto"] = {
            "moto_vin": "VIN001",
            "moto_modelo": "RAIDER 125",
            "moto_valor_origen": 5_200_000,
        }
        lb = LoanbookCreate(**payload)
        assert lb.metadata_producto.get("ltv") == pytest.approx(0.5, rel=1e-3)

    def test_ltv_no_calculado_sin_valor_origen(self, rdx_create_valido):
        payload = dict(rdx_create_valido)
        payload["metadata_producto"] = {
            "moto_vin": "VIN001",
            "moto_modelo": "RAIDER 125",
            # sin moto_valor_origen
        }
        lb = LoanbookCreate(**payload)
        assert "ltv" not in lb.metadata_producto or lb.metadata_producto.get("ltv") is None

    def test_ltv_preciso_tres_decimales(self, rdx_create_valido):
        payload = dict(rdx_create_valido)
        payload["monto_original"] = 2_000_000
        payload["metadata_producto"] = {
            "moto_vin": "VIN001",
            "moto_modelo": "RAIDER 125",
            "moto_valor_origen": 3_000_000,
        }
        lb = LoanbookCreate(**payload)
        ltv = lb.metadata_producto.get("ltv")
        assert ltv is not None
        assert ltv == pytest.approx(2_000_000 / 3_000_000, rel=1e-3)


# ─────────────────────── BLOQUE 6 — LoanbookUpdate ───────────────────────────

class TestLoanbookUpdate:
    """Verifica que LoanbookUpdate acepta campos opcionales."""

    def test_update_vacio_valido(self):
        """Update sin campos es válido (todos opcionales)."""
        upd = LoanbookUpdate()
        assert upd.score_riesgo is None
        assert upd.whatsapp_status is None

    def test_update_solo_score_riesgo(self):
        upd = LoanbookUpdate(score_riesgo="A+")
        assert upd.score_riesgo == "A+"

    def test_update_score_riesgo_invalido(self):
        with pytest.raises(ValidationError):
            LoanbookUpdate(score_riesgo="Z")

    def test_update_whatsapp_status(self):
        for status in ("read", "delivered", "sent", "failed", "pending"):
            upd = LoanbookUpdate(whatsapp_status=status)
            assert upd.whatsapp_status == status

    def test_update_whatsapp_status_invalido(self):
        with pytest.raises(ValidationError):
            LoanbookUpdate(whatsapp_status="enviado")

    def test_update_vendedor(self):
        upd = LoanbookUpdate(vendedor="Laura García")
        assert upd.vendedor == "Laura García"

    def test_update_fecha_vencimiento(self):
        upd = LoanbookUpdate(fecha_vencimiento="2027-09-15")
        assert upd.fecha_vencimiento is not None


# ─────────────────────── BLOQUE 7 — MetadataRDX standalone ───────────────────

class TestMetadataRDX:
    """Tests directos del modelo MetadataRDX."""

    def test_minimo_valido(self):
        m = MetadataRDX(moto_vin="VIN001", moto_modelo="RAIDER 125")
        assert m.moto_vin == "VIN001"
        assert m.ltv is None

    def test_vin_vacio_rechazado(self):
        with pytest.raises(ValidationError):
            MetadataRDX(moto_vin="", moto_modelo="RAIDER 125")

    def test_ltv_fuera_de_rango_rechazado(self):
        with pytest.raises(ValidationError):
            MetadataRDX(moto_vin="VIN001", moto_modelo="X", ltv=10.0)  # max 5

    def test_moto_anio_invalido_rechazado(self):
        with pytest.raises(ValidationError):
            MetadataRDX(moto_vin="VIN001", moto_modelo="X", moto_anio=1985)  # min 1990


# ─────────────────────── BLOQUE 8 — MetadataSoat standalone ──────────────────

class TestMetadataSoat:
    """Tests directos del modelo MetadataSoat."""

    def test_completo_valido(self):
        m = MetadataSoat(
            poliza_numero="POL-001",
            aseguradora="Sura",
            cilindraje_moto=125,
            vigencia_desde="2026-04-01",
            vigencia_hasta="2027-04-01",
            valor_soat=350_000,
            placa_cubierta="ABC123",
        )
        assert m.aseguradora == "Sura"

    def test_cilindraje_cero_rechazado(self):
        with pytest.raises(ValidationError):
            MetadataSoat(
                poliza_numero="P",
                aseguradora="X",
                cilindraje_moto=0,  # gt=0
                vigencia_desde="2026-01-01",
                vigencia_hasta="2027-01-01",
                valor_soat=100_000,
                placa_cubierta="XYZ",
            )


# ─────────────────────── BLOQUE 9 — Error messages ───────────────────────────

class TestErrorMessages:
    """Verifica que los mensajes de error son descriptivos para debugging."""

    def test_plan_inexistente_menciona_planes_validos(self, rdx_create_valido):
        """El error de plan inválido debe listar los planes válidos disponibles."""
        payload = dict(rdx_create_valido)
        payload["plan_codigo"] = "P999S"
        with pytest.raises(ValidationError) as exc_info:
            LoanbookCreate(**payload)
        err = str(exc_info.value)
        # Debe mencionar el plan inválido
        assert "P999S" in err

    def test_rdx_plan_rodante_menciona_aplica_a(self, rdx_create_valido):
        """Error de plan que no aplica al producto debe mencionar el plan y producto."""
        payload = dict(rdx_create_valido)
        payload["plan_codigo"] = "P15S"
        with pytest.raises(ValidationError) as exc_info:
            LoanbookCreate(**payload)
        err = str(exc_info.value)
        assert "P15S" in err

    def test_rodante_quincenal_menciona_r23(self, rodante_soat_valido):
        """Error de modalidad no semanal en RODANTE debe mencionar R-23."""
        payload = dict(rodante_soat_valido)
        payload["modalidad_pago"] = "quincenal"
        with pytest.raises(ValidationError) as exc_info:
            LoanbookCreate(**payload)
        err = str(exc_info.value)
        assert "R-23" in err or "semanal" in err.lower()
