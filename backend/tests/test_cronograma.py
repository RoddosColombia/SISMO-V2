"""
Sprint 4 — Regla del Miércoles + Cronograma de Cuotas.

La Regla del Miércoles es INVIOLABLE: todas las cuotas caen en miércoles.
- Semanal: primer miércoles >= fecha_entrega + 7 días, luego cada 7 días
- Quincenal: fecha_primer_pago (usuario, debe ser miércoles), luego cada 14 días
- Mensual: fecha_primer_pago (usuario, debe ser miércoles), luego cada 28 días
"""
import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock
import uuid


WEDNESDAY = 2  # date.weekday() == 2 is Wednesday


# ═══════════════════════════════════════════
# Semanal — primer miércoles automático
# ═══════════════════════════════════════════


class TestCronogramaSemanal:
    """Semanal: primer miércoles >= entrega + 7 días, luego cada 7."""

    def test_entrega_martes_primer_cobro_miercoles_siguiente(self):
        """Entrega mar 5 mar → +7=12 mar (miércoles) → primer cobro 12 mar."""
        from core.loanbook_model import calcular_cronograma

        # 2026-03-05 is Thursday... let me pick a real Tuesday
        # 2026-04-14 is Tuesday
        fechas = calcular_cronograma(
            fecha_entrega=date(2026, 4, 14),  # Tuesday
            modalidad="semanal",
            num_cuotas=4,
        )
        # +7 days = 2026-04-21 (Tuesday) → next Wednesday = 2026-04-22
        assert fechas[0] == date(2026, 4, 22)
        assert len(fechas) == 4

    def test_entrega_miercoles_primer_cobro_no_mismo_dia(self):
        """Entrega miércoles → +7 días → primer cobro miércoles siguiente."""
        from core.loanbook_model import calcular_cronograma

        # 2026-04-15 is Wednesday
        fechas = calcular_cronograma(
            fecha_entrega=date(2026, 4, 15),  # Wednesday
            modalidad="semanal",
            num_cuotas=3,
        )
        # +7 days = 2026-04-22 (Wednesday) → that IS a Wednesday, so first cuota
        assert fechas[0] == date(2026, 4, 22)

    def test_entrega_jueves_primer_cobro_miercoles(self):
        """Entrega jueves → +7 = jueves siguiente → avanza a miércoles."""
        from core.loanbook_model import calcular_cronograma

        # 2026-04-16 is Thursday
        fechas = calcular_cronograma(
            fecha_entrega=date(2026, 4, 16),  # Thursday
            modalidad="semanal",
            num_cuotas=3,
        )
        # +7 days = 2026-04-23 (Thursday) → next Wednesday = 2026-04-29
        assert fechas[0] == date(2026, 4, 29)

    def test_entrega_lunes_primer_cobro(self):
        """Entrega lunes → +7 = lunes → avanza a miércoles."""
        from core.loanbook_model import calcular_cronograma

        # 2026-04-20 is Monday
        fechas = calcular_cronograma(
            fecha_entrega=date(2026, 4, 20),  # Monday
            modalidad="semanal",
            num_cuotas=3,
        )
        # +7 days = 2026-04-27 (Monday) → next Wednesday = 2026-04-29
        assert fechas[0] == date(2026, 4, 29)

    def test_semanal_cuotas_cada_7_dias(self):
        """Todas las cuotas separadas por exactamente 7 días."""
        from core.loanbook_model import calcular_cronograma

        fechas = calcular_cronograma(
            fecha_entrega=date(2026, 4, 15),  # Wednesday
            modalidad="semanal",
            num_cuotas=10,
        )
        for i in range(1, len(fechas)):
            delta = (fechas[i] - fechas[i - 1]).days
            assert delta == 7, f"Cuota {i} a {i+1}: {delta} días, esperado 7"

    def test_semanal_52_cuotas(self):
        """Plan P52S semanal genera 52 fechas, todas miércoles."""
        from core.loanbook_model import calcular_cronograma

        fechas = calcular_cronograma(
            fecha_entrega=date(2026, 4, 14),
            modalidad="semanal",
            num_cuotas=52,
        )
        assert len(fechas) == 52
        for f in fechas:
            assert f.weekday() == WEDNESDAY, f"{f} is not Wednesday"


# ═══════════════════════════════════════════
# Quincenal — fecha_primer_pago obligatoria
# ═══════════════════════════════════════════


class TestCronogramaQuincenal:
    """Quincenal: fecha_primer_pago (miércoles), luego cada 14 días."""

    def test_quincenal_con_fecha_primer_pago(self):
        from core.loanbook_model import calcular_cronograma

        # 2026-04-22 is Wednesday
        fechas = calcular_cronograma(
            fecha_entrega=date(2026, 4, 14),
            modalidad="quincenal",
            num_cuotas=4,
            fecha_primer_pago=date(2026, 4, 22),
        )
        assert fechas[0] == date(2026, 4, 22)
        assert fechas[1] == date(2026, 5, 6)   # +14
        assert fechas[2] == date(2026, 5, 20)  # +14
        assert fechas[3] == date(2026, 6, 3)   # +14

    def test_quincenal_todas_miercoles(self):
        from core.loanbook_model import calcular_cronograma

        fechas = calcular_cronograma(
            fecha_entrega=date(2026, 4, 14),
            modalidad="quincenal",
            num_cuotas=26,
            fecha_primer_pago=date(2026, 4, 22),
        )
        assert len(fechas) == 26
        for f in fechas:
            assert f.weekday() == WEDNESDAY, f"{f} is not Wednesday"

    def test_quincenal_sin_fecha_raises(self):
        from core.loanbook_model import calcular_cronograma

        with pytest.raises(ValueError, match="fecha_primer_pago"):
            calcular_cronograma(
                fecha_entrega=date(2026, 4, 14),
                modalidad="quincenal",
                num_cuotas=26,
            )

    def test_quincenal_cada_14_dias(self):
        from core.loanbook_model import calcular_cronograma

        fechas = calcular_cronograma(
            fecha_entrega=date(2026, 4, 14),
            modalidad="quincenal",
            num_cuotas=10,
            fecha_primer_pago=date(2026, 4, 22),
        )
        for i in range(1, len(fechas)):
            delta = (fechas[i] - fechas[i - 1]).days
            assert delta == 14, f"Cuota {i} a {i+1}: {delta} días, esperado 14"


# ═══════════════════════════════════════════
# Mensual — fecha_primer_pago obligatoria
# ═══════════════════════════════════════════


class TestCronogramaMensual:
    """Mensual: fecha_primer_pago (miércoles), luego cada 28 días."""

    def test_mensual_con_fecha_primer_pago(self):
        from core.loanbook_model import calcular_cronograma

        fechas = calcular_cronograma(
            fecha_entrega=date(2026, 4, 14),
            modalidad="mensual",
            num_cuotas=3,
            fecha_primer_pago=date(2026, 4, 22),
        )
        assert fechas[0] == date(2026, 4, 22)
        assert fechas[1] == date(2026, 5, 20)  # +28
        assert fechas[2] == date(2026, 6, 17)  # +28

    def test_mensual_sin_fecha_raises(self):
        from core.loanbook_model import calcular_cronograma

        with pytest.raises(ValueError, match="fecha_primer_pago"):
            calcular_cronograma(
                fecha_entrega=date(2026, 4, 14),
                modalidad="mensual",
                num_cuotas=13,
            )

    def test_mensual_cada_28_dias(self):
        from core.loanbook_model import calcular_cronograma

        fechas = calcular_cronograma(
            fecha_entrega=date(2026, 4, 14),
            modalidad="mensual",
            num_cuotas=13,
            fecha_primer_pago=date(2026, 4, 22),
        )
        assert len(fechas) == 13
        for i in range(1, len(fechas)):
            delta = (fechas[i] - fechas[i - 1]).days
            assert delta == 28, f"Cuota {i} a {i+1}: {delta} días, esperado 28"


# ═══════════════════════════════════════════
# Validation rules
# ═══════════════════════════════════════════


class TestCronogramaValidation:
    """Validation: Wednesday rule, minimum gap, etc."""

    def test_fecha_primer_pago_not_wednesday_raises(self):
        from core.loanbook_model import calcular_cronograma

        # 2026-04-23 is Thursday
        with pytest.raises(ValueError, match="[Mm]i.rcoles|[Ww]ednesday"):
            calcular_cronograma(
                fecha_entrega=date(2026, 4, 14),
                modalidad="quincenal",
                num_cuotas=26,
                fecha_primer_pago=date(2026, 4, 23),  # Thursday
            )

    def test_fecha_primer_pago_anterior_o_igual_entrega_raises(self):
        """fecha_primer_pago debe ser estrictamente posterior a fecha_entrega.

        El override no exige gap canónico de +7 días (se respeta la elección
        del operador para excepciones legítimas), pero sí exige que la fecha
        sea posterior a la entrega — un pago no puede ocurrir antes de
        recibir la moto.
        """
        from core.loanbook_model import calcular_cronograma

        # 2026-04-08 is Wednesday, anterior a entrega (Tue 2026-04-14)
        with pytest.raises(ValueError, match="posterior"):
            calcular_cronograma(
                fecha_entrega=date(2026, 4, 14),
                modalidad="quincenal",
                num_cuotas=26,
                fecha_primer_pago=date(2026, 4, 8),  # miércoles anterior
            )

    def test_all_dates_are_wednesday_property(self):
        """Property test: ANY cronograma returns only Wednesdays."""
        from core.loanbook_model import calcular_cronograma

        # Test multiple entry dates
        for offset in range(7):  # All days of the week
            entrega = date(2026, 4, 13) + timedelta(days=offset)
            fechas = calcular_cronograma(
                fecha_entrega=entrega,
                modalidad="semanal",
                num_cuotas=10,
            )
            for f in fechas:
                assert f.weekday() == WEDNESDAY, (
                    f"Entrega {entrega} ({entrega.strftime('%A')}): "
                    f"cuota {f} is {f.strftime('%A')}, not Wednesday"
                )

    def test_invalid_modalidad_raises(self):
        from core.loanbook_model import calcular_cronograma

        with pytest.raises(ValueError):
            calcular_cronograma(
                fecha_entrega=date(2026, 4, 14),
                modalidad="contado",
                num_cuotas=10,
            )


# ═══════════════════════════════════════════
# asignar_cronograma — sets dates on loanbook cuotas
# ═══════════════════════════════════════════


class TestAsignarCronograma:
    """Assign calculated dates to loanbook cuotas."""

    def test_assigns_dates_to_cuotas(self):
        from core.loanbook_model import asignar_cronograma

        cuotas = [
            {"numero": 1, "monto": 160_000, "estado": "pendiente", "fecha": None},
            {"numero": 2, "monto": 160_000, "estado": "pendiente", "fecha": None},
            {"numero": 3, "monto": 160_000, "estado": "pendiente", "fecha": None},
        ]
        fechas = [date(2026, 4, 22), date(2026, 4, 29), date(2026, 5, 6)]

        result = asignar_cronograma(cuotas, fechas)

        assert result["cuotas"][0]["fecha"] == "2026-04-22"
        assert result["cuotas"][1]["fecha"] == "2026-04-29"
        assert result["cuotas"][2]["fecha"] == "2026-05-06"

    def test_sets_primera_y_ultima_cuota(self):
        from core.loanbook_model import asignar_cronograma

        cuotas = [
            {"numero": 1, "fecha": None},
            {"numero": 2, "fecha": None},
        ]
        fechas = [date(2026, 4, 22), date(2026, 4, 29)]

        result = asignar_cronograma(cuotas, fechas)

        assert result["fecha_primera_cuota"] == "2026-04-22"
        assert result["fecha_ultima_cuota"] == "2026-04-29"

    def test_mismatched_lengths_raises(self):
        from core.loanbook_model import asignar_cronograma

        cuotas = [{"numero": 1, "fecha": None}]
        fechas = [date(2026, 4, 22), date(2026, 4, 29)]

        with pytest.raises(ValueError, match="cuotas|fechas"):
            asignar_cronograma(cuotas, fechas)


# ═══════════════════════════════════════════
# Handler integration — entrega assigns cronograma
# ═══════════════════════════════════════════


PLAN_P52S = {
    "codigo": "P52S",
    "nombre": "Plan 52 Semanas",
    "cuotas_base": 52,
    "anzi_pct": 0.02,
    "cuotas_modelo": {"Sport 100": 160_000},
}


def _make_event(event_type, datos):
    from datetime import datetime, timezone
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "source": "test",
        "correlation_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "datos": datos,
        "alegra_id": None,
        "accion_ejecutada": "test",
    }


class TestEntregaAsignaCronograma:
    """handle_entrega_realizada calculates and assigns cronograma."""

    @pytest.mark.asyncio
    async def test_entrega_semanal_assigns_dates(self):
        from core.loanbook_handlers import handle_entrega_realizada

        db = AsyncMock()
        lb = {
            "loanbook_id": "lb-001",
            "vin": "VIN001",
            "estado": "pendiente_entrega",
            "modalidad": "semanal",
            "num_cuotas": 3,
            "fecha_entrega": "2026-04-14",
            "fecha_primer_pago": None,
            "cuotas": [
                {"numero": 1, "monto": 160_000, "estado": "pendiente", "fecha": None, "fecha_pago": None, "mora_acumulada": 0},
                {"numero": 2, "monto": 160_000, "estado": "pendiente", "fecha": None, "fecha_pago": None, "mora_acumulada": 0},
                {"numero": 3, "monto": 160_000, "estado": "pendiente", "fecha": None, "fecha_pago": None, "mora_acumulada": 0},
            ],
        }
        db.loanbook.find_one = AsyncMock(return_value=lb)
        db.loanbook.update_one = AsyncMock()
        db.inventario_motos.update_one = AsyncMock()

        event = _make_event("entrega.realizada", {"vin": "VIN001"})
        await handle_entrega_realizada(event, db)

        call_args = db.loanbook.update_one.call_args
        update_set = call_args[0][1]["$set"]

        # Entrega 2026-04-14 (Tue) +7 = 2026-04-21 (Tue) → next Wed = 2026-04-22
        cuotas = update_set["cuotas"]
        assert cuotas[0]["fecha"] == "2026-04-22"
        assert cuotas[1]["fecha"] == "2026-04-29"
        assert cuotas[2]["fecha"] == "2026-05-06"

        # All Wednesdays
        for c in cuotas:
            f = date.fromisoformat(c["fecha"])
            assert f.weekday() == WEDNESDAY

    @pytest.mark.asyncio
    async def test_entrega_quincenal_uses_fecha_primer_pago(self):
        from core.loanbook_handlers import handle_entrega_realizada

        db = AsyncMock()
        lb = {
            "loanbook_id": "lb-002",
            "vin": "VIN002",
            "estado": "pendiente_entrega",
            "modalidad": "quincenal",
            "num_cuotas": 3,
            "fecha_entrega": "2026-04-14",
            "fecha_primer_pago": "2026-04-22",  # Wednesday
            "cuotas": [
                {"numero": 1, "monto": 352_000, "estado": "pendiente", "fecha": None, "fecha_pago": None, "mora_acumulada": 0},
                {"numero": 2, "monto": 352_000, "estado": "pendiente", "fecha": None, "fecha_pago": None, "mora_acumulada": 0},
                {"numero": 3, "monto": 352_000, "estado": "pendiente", "fecha": None, "fecha_pago": None, "mora_acumulada": 0},
            ],
        }
        db.loanbook.find_one = AsyncMock(return_value=lb)
        db.loanbook.update_one = AsyncMock()
        db.inventario_motos.update_one = AsyncMock()

        event = _make_event("entrega.realizada", {"vin": "VIN002"})
        await handle_entrega_realizada(event, db)

        call_args = db.loanbook.update_one.call_args
        update_set = call_args[0][1]["$set"]

        cuotas = update_set["cuotas"]
        assert cuotas[0]["fecha"] == "2026-04-22"
        assert cuotas[1]["fecha"] == "2026-05-06"   # +14
        assert cuotas[2]["fecha"] == "2026-05-20"   # +14

    @pytest.mark.asyncio
    async def test_entrega_sets_fecha_primera_y_ultima(self):
        from core.loanbook_handlers import handle_entrega_realizada

        db = AsyncMock()
        lb = {
            "loanbook_id": "lb-003",
            "vin": "VIN003",
            "estado": "pendiente_entrega",
            "modalidad": "semanal",
            "num_cuotas": 3,
            "fecha_entrega": "2026-04-15",  # Wednesday
            "fecha_primer_pago": None,
            "cuotas": [
                {"numero": i, "monto": 160_000, "estado": "pendiente", "fecha": None, "fecha_pago": None, "mora_acumulada": 0}
                for i in range(1, 4)
            ],
        }
        db.loanbook.find_one = AsyncMock(return_value=lb)
        db.loanbook.update_one = AsyncMock()
        db.inventario_motos.update_one = AsyncMock()

        event = _make_event("entrega.realizada", {"vin": "VIN003"})
        await handle_entrega_realizada(event, db)

        call_args = db.loanbook.update_one.call_args
        update_set = call_args[0][1]["$set"]
        # Entrega 2026-04-15 (Wed) + 7 = 2026-04-22 (Wed) → primer cobro
        assert update_set["fecha_primera_cuota"] == "2026-04-22"
        # Última cuota = primera + (n-1) * 7 días = 2026-04-22 + 14 = 2026-05-06
        assert update_set["fecha_ultima_cuota"] == "2026-05-06"

