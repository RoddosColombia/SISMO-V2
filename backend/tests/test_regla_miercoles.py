"""
test_regla_miercoles.py — Tests para primer_miercoles_cobro() en reglas_negocio.

Valida la Regla del Miércoles RODDOS:
  Primera cuota = primer miércoles >= fecha_entrega + 7 días.
  Si la entrega ES miércoles, la cuota es el miércoles SIGUIENTE (nunca mismo día).
"""
from __future__ import annotations

import pytest
from datetime import date
from services.loanbook.reglas_negocio import primer_miercoles_cobro


# ─── Tabla de casos de prueba ──────────────────────────────────────────────────
# (descripcion, fecha_entrega, primera_cuota_esperada)
CASOS = [
    # Casos del Excel V1 — fuente de verdad
    ("entrega jueves → siguiente miercoles +7",  date(2026, 3,  5), date(2026, 3, 18)),
    ("entrega martes → siguiente miercoles +7",  date(2026, 3, 10), date(2026, 3, 18)),
    ("entrega martes → siguiente miercoles +7",  date(2026, 3, 24), date(2026, 4,  1)),
    ("entrega miercoles → miercoles SIGUIENTE",  date(2026, 3, 25), date(2026, 4,  1)),
    ("entrega viernes → miercoles siguiente +7", date(2026, 3, 27), date(2026, 4,  8)),
    ("entrega sabado → miercoles siguiente +7",  date(2026, 3, 28), date(2026, 4,  8)),
    # Caso crítico: entrega EN miércoles → pago ES el miércoles siguiente
    ("entrega miercoles → cuota es miercoles+7", date(2026, 4,  8), date(2026, 4, 15)),
    ("entrega viernes → miercoles siguiente",     date(2026, 4, 10), date(2026, 4, 22)),
    # Casos de borde adicionales
    ("entrega lunes → miercoles de esa semana+7",date(2026, 4, 13), date(2026, 4, 22)),
    ("entrega domingo → miercoles siguiente +7", date(2026, 4, 12), date(2026, 4, 22)),
]


class TestPrimerMiercolesCobroFormula:
    """La función retorna el miércoles correcto para cada caso de la tabla."""

    @pytest.mark.parametrize("descripcion,entrega,esperado", CASOS)
    def test_fecha_correcta(self, descripcion: str, entrega: date, esperado: date):
        resultado = primer_miercoles_cobro(entrega)
        assert resultado == esperado, (
            f"{descripcion}: entrega={entrega} → esperado {esperado}, obtenido {resultado}"
        )

    def test_retorna_date(self):
        """La función siempre retorna date, nunca datetime."""
        resultado = primer_miercoles_cobro(date(2026, 3, 5))
        assert isinstance(resultado, date)
        from datetime import datetime
        assert not isinstance(resultado, datetime)

    def test_resultado_es_miercoles(self):
        """El resultado siempre es miércoles (weekday == 2)."""
        fechas_prueba = [
            date(2026, 3, 5),
            date(2026, 3, 10),
            date(2026, 3, 25),   # entrega = miércoles
            date(2026, 4,  8),   # entrega = miércoles
            date(2026, 4, 12),   # domingo
            date(2026, 4, 19),   # domingo
        ]
        for entrega in fechas_prueba:
            resultado = primer_miercoles_cobro(entrega)
            assert resultado.weekday() == 2, (
                f"entrega={entrega}: se esperaba miércoles, se obtuvo {resultado} "
                f"({resultado.strftime('%A')})"
            )

    def test_minimo_7_dias_despues(self):
        """El resultado siempre es >= fecha_entrega + 7 días."""
        fechas_prueba = [
            date(2026, 3, 5),
            date(2026, 3, 10),
            date(2026, 3, 25),
            date(2026, 4,  8),
            date(2026, 4, 12),
        ]
        from datetime import timedelta
        for entrega in fechas_prueba:
            resultado = primer_miercoles_cobro(entrega)
            minimo = entrega + timedelta(days=7)
            assert resultado >= minimo, (
                f"entrega={entrega}: resultado {resultado} es antes del mínimo {minimo}"
            )

    def test_no_mas_de_14_dias_despues(self):
        """El resultado nunca es más de 13 días después de entrega + 7 (max gap = 6 días)."""
        from datetime import timedelta
        fechas_prueba = [date(2026, 3, d) for d in range(1, 32) if d <= 31]
        fechas_prueba += [date(2026, 4, d) for d in range(1, 31)]
        for entrega in fechas_prueba:
            resultado = primer_miercoles_cobro(entrega)
            maximo = entrega + timedelta(days=13)
            assert resultado <= maximo, (
                f"entrega={entrega}: resultado {resultado} excede el máximo {maximo}"
            )
