"""
test_datetime_utils.py — Tests para core/datetime_utils.py

Valida:
  - now_bogota() tiene offset UTC-5
  - today_bogota() retorna date (no datetime)
  - now_iso_bogota() incluye "-05:00" en el string
  - ningún archivo de runtime usa date.today() / datetime.utcnow() raw
"""
from __future__ import annotations

import re
from datetime import date, timedelta, timezone
from pathlib import Path


# ─── Tests de las funciones ───────────────────────────────────────────────────

class TestNowBogota:
    def test_offset_utc_minus_5(self):
        """now_bogota() debe tener offset UTC-5 (Colombia no usa DST)."""
        from core.datetime_utils import now_bogota
        dt = now_bogota()
        offset = dt.utcoffset()
        assert offset is not None, "now_bogota() debe ser timezone-aware"
        assert offset == timedelta(hours=-5), (
            f"Offset esperado -5h, obtenido {offset}"
        )

    def test_is_aware(self):
        """now_bogota() no debe retornar un datetime naive."""
        from core.datetime_utils import now_bogota
        dt = now_bogota()
        assert dt.tzinfo is not None

    def test_returns_datetime(self):
        from core.datetime_utils import now_bogota
        from datetime import datetime
        assert isinstance(now_bogota(), datetime)


class TestTodayBogota:
    def test_returns_date_not_datetime(self):
        """today_bogota() retorna date, no datetime."""
        from core.datetime_utils import today_bogota
        result = today_bogota()
        assert isinstance(result, date)
        # date is a base class of datetime — ensure it's not a datetime
        from datetime import datetime
        assert not isinstance(result, datetime)

    def test_not_utcnow(self):
        """today_bogota() no debe ser igual a date.today() cuando es tarde en UTC
        y temprano en Bogotá (borde de medianoche). Simulamos que now_bogota devuelve
        el valor correcto verificando que usa la TZ."""
        from core.datetime_utils import today_bogota, now_bogota
        # today_bogota() debe ser la fecha del now_bogota() — no una fecha UTC
        assert today_bogota() == now_bogota().date()


class TestNowIsoBogota:
    def test_contains_minus_05(self):
        """now_iso_bogota() debe contener '-05:00' (offset Bogotá)."""
        from core.datetime_utils import now_iso_bogota
        iso = now_iso_bogota()
        assert "-05:00" in iso, (
            f"Se esperaba '-05:00' en '{iso}'. "
            "El servidor puede estar en UTC — verificar que ZoneInfo esté disponible."
        )

    def test_is_string(self):
        from core.datetime_utils import now_iso_bogota
        assert isinstance(now_iso_bogota(), str)

    def test_parseable_as_datetime(self):
        """El string debe ser parseable de vuelta a datetime."""
        from core.datetime_utils import now_iso_bogota
        from datetime import datetime
        iso = now_iso_bogota()
        dt = datetime.fromisoformat(iso)
        assert dt.tzinfo is not None


# ─── Test de cobertura: ningún archivo de runtime usa date.today() raw ────────

class TestNoRawDateCalls:
    """Verifica que los archivos de runtime no usen date.today() ni
    datetime.utcnow() directamente — deben usar core/datetime_utils.py.

    Excepciones permitidas:
      - core/datetime_utils.py (la fuente de verdad, usa date internamente)
      - services/loanbook/dpd_scheduler.py (ya usa ZoneInfo correctamente)
      - services/loanbook/informes_service.py (ya usa ZoneInfo correctamente)
      - tests/ (los tests inyectan fechas explícitas — OK)
      - scripts/ (scripts one-shot, no afectan runtime)
    """

    ALLOWED_FILES = {
        "datetime_utils.py",
        "dpd_scheduler.py",
        "informes_service.py",
    }

    RUNTIME_DIRS = [
        "routers",
        "services",
        "core",
        "agents",
    ]

    FORBIDDEN_PATTERNS = [
        re.compile(r"\bdate\.today\(\)"),
        re.compile(r"\bdatetime\.utcnow\(\)"),
        re.compile(r"\bdatetime\.now\(\)"),         # without tz arg
        re.compile(r"\bdatetime\.date\.today\(\)"),  # via module reference
    ]

    def _scan(self):
        backend_root = Path(__file__).parent.parent
        violations = []

        for runtime_dir in self.RUNTIME_DIRS:
            scan_path = backend_root / runtime_dir
            if not scan_path.exists():
                continue
            for py_file in scan_path.rglob("*.py"):
                if py_file.name in self.ALLOWED_FILES:
                    continue
                if "__pycache__" in py_file.parts:
                    continue

                text = py_file.read_text(encoding="utf-8")
                for pattern in self.FORBIDDEN_PATTERNS:
                    for match in pattern.finditer(text):
                        line_num = text[:match.start()].count("\n") + 1
                        violations.append(
                            f"{py_file.relative_to(backend_root)}:{line_num} — {match.group()}"
                        )

        return violations

    def test_no_raw_date_today(self):
        """Ningún archivo de runtime debe usar date.today() sin timezone."""
        violations = self._scan()
        if violations:
            msg = (
                "Archivos de runtime con date.today()/datetime.utcnow() raw:\n"
                + "\n".join(f"  {v}" for v in violations)
                + "\n\nUsar today_bogota() / now_bogota() / now_iso_bogota() de core.datetime_utils"
            )
            assert False, msg
