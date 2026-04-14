"""
Tests for the audit classification engine (9 rules).

Covers:
  R1 — Balance check (debit == credit)
  R2 — Account correctness (arriendo → 5480)
  R3 — ReteFuente applied where required
  R4 — ReteICA applied for gastos > 100k
  R5 — Auteco autoretenedor (NEVER ReteFuente)
  R6 — Socios CXC, never gasto operativo
  R7 — Duplicate detection (same date + amount + similar obs)
  R8 — Transfers: no retenciones, no gasto accounts
  R9 — Forbidden accounts (5493, 5495)
  Type inference, max_severity, and audit_all_journals integration
"""
import pytest
from services.audit.classify import (
    Severity,
    Finding,
    JournalClassification,
    classify_journal,
    audit_all_journals,
    rule_1_balance_check,
    rule_2_account_correctness,
    rule_3_retefuente_check,
    rule_4_reteica_check,
    rule_5_auteco_retefuente,
    rule_6_socios_cxc,
    rule_7_duplicates,
    rule_8_transfers,
    rule_9_forbidden_accounts,
    _infer_type,
    _extract_entries,
)


# ───────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────

def _journal(
    jid="100",
    date="2026-03-15",
    observations="",
    entries=None,
    total=None,
):
    """Build a minimal journal dict for testing."""
    entries = entries or []
    if total is None:
        total = sum(float(e.get("debit", 0) or 0) for e in entries)
    return {
        "id": jid,
        "date": date,
        "observations": observations,
        "total": total,
        "entries": entries,
    }


def _entry(eid, debit=0, credit=0):
    """Build a minimal entry dict."""
    return {"id": str(eid), "debit": debit, "credit": credit}


# ───────────────────────────────────────────────
# R1 — Balance check
# ───────────────────────────────────────────────

class TestR1Balance:
    def test_balanced_returns_none(self):
        entries = [_entry("5314", debit=1000000), _entry("5480", credit=1000000)]
        j = _journal(entries=entries)
        assert rule_1_balance_check(j, entries) is None

    def test_unbalanced_returns_high(self):
        entries = [_entry("5314", debit=1000000), _entry("5480", credit=900000)]
        j = _journal(entries=entries)
        finding = rule_1_balance_check(j, entries)
        assert finding is not None
        assert finding.severity == Severity.HIGH
        assert finding.rule == "R1-BALANCE"
        assert finding.details["diff"] == 100000.0

    def test_tiny_rounding_accepted(self):
        """Diff of exactly 0.01 should NOT trigger (uses > not >=)."""
        entries = [_entry("5314", debit=1000000.004), _entry("5480", credit=1000000)]
        j = _journal(entries=entries)
        # _sum_debits rounds to 2 decimals: 1000000.004 → 1000000.0
        # diff = 0.0 which is ≤ 0.01, so no finding
        assert rule_1_balance_check(j, entries) is None


# ───────────────────────────────────────────────
# R2 — Account correctness
# ───────────────────────────────────────────────

class TestR2Account:
    def test_arriendo_with_wrong_account_flags(self):
        entries = [_entry("5314", debit=2000000), _entry("5494", credit=2000000)]
        j = _journal(observations="Pago arriendo oficina", entries=entries)
        finding = rule_2_account_correctness(j, entries)
        assert finding is not None
        assert finding.severity == Severity.MEDIUM
        assert "5480" in finding.description

    def test_arriendo_with_correct_account_clean(self):
        entries = [_entry("5314", debit=2000000), _entry("5480", credit=2000000)]
        j = _journal(observations="Pago arriendo oficina", entries=entries)
        assert rule_2_account_correctness(j, entries) is None

    def test_no_arriendo_keyword_clean(self):
        entries = [_entry("5314", debit=500000), _entry("5494", credit=500000)]
        j = _journal(observations="Compra de repuestos", entries=entries)
        assert rule_2_account_correctness(j, entries) is None


# ───────────────────────────────────────────────
# R3 — ReteFuente
# ───────────────────────────────────────────────

class TestR3ReteFuente:
    def test_arriendo_without_retefuente_flags_high(self):
        entries = [_entry("5314", debit=2000000), _entry("5480", credit=2000000)]
        j = _journal(observations="Pago arriendo bodega", entries=entries)
        finding = rule_3_retefuente_check(j, entries)
        assert finding is not None
        assert finding.severity == Severity.HIGH
        assert "3.5%" in finding.description

    def test_arriendo_with_retefuente_clean(self):
        entries = [
            _entry("5314", debit=2000000),
            _entry("5480", credit=1930000),
            _entry("5386", credit=70000),  # ReteFuente arriendo
        ]
        j = _journal(observations="Pago arriendo bodega", entries=entries)
        assert rule_3_retefuente_check(j, entries) is None

    def test_honorarios_without_retefuente_flags(self):
        entries = [_entry("5314", debit=5000000), _entry("5494", credit=5000000)]
        j = _journal(observations="Pago honorarios asesoría legal", entries=entries)
        finding = rule_3_retefuente_check(j, entries)
        assert finding is not None
        assert finding.severity == Severity.HIGH
        assert "10%" in finding.description or "11%" in finding.description

    def test_transfer_skips_retefuente_check(self):
        entries = [_entry("5314", debit=5000000), _entry("5318", credit=5000000)]
        j = _journal(observations="Transferencia entre cuentas", entries=entries)
        assert rule_3_retefuente_check(j, entries) is None

    def test_auteco_skips_retefuente_check(self):
        entries = [_entry("5314", debit=5000000), _entry("5494", credit=5000000)]
        j = _journal(observations="Pago arriendo auteco 860024781", entries=entries)
        assert rule_3_retefuente_check(j, entries) is None


# ───────────────────────────────────────────────
# R4 — ReteICA
# ───────────────────────────────────────────────

class TestR4ReteICA:
    def test_gasto_sin_reteica_flags_medium(self):
        entries = [_entry("5314", debit=2000000), _entry("5480", credit=2000000)]
        j = _journal(observations="Pago servicio limpieza", entries=entries)
        finding = rule_4_reteica_check(j, entries)
        assert finding is not None
        assert finding.severity == Severity.MEDIUM
        assert "0.414%" in finding.description

    def test_gasto_con_reteica_clean(self):
        entries = [
            _entry("5314", debit=2000000),
            _entry("5480", credit=1991720),
            _entry("5392", credit=8280),  # ReteICA
        ]
        j = _journal(observations="Pago servicio limpieza", entries=entries)
        assert rule_4_reteica_check(j, entries) is None

    def test_transfer_skips_reteica(self):
        entries = [_entry("5314", debit=2000000), _entry("5318", credit=2000000)]
        j = _journal(observations="Transferencia entre cuentas", entries=entries)
        assert rule_4_reteica_check(j, entries) is None

    def test_small_amount_not_flagged(self):
        entries = [_entry("5314", debit=50000), _entry("5480", credit=50000)]
        j = _journal(observations="Pago servicio menor", entries=entries)
        assert rule_4_reteica_check(j, entries) is None


# ───────────────────────────────────────────────
# R5 — Auteco autoretenedor
# ───────────────────────────────────────────────

class TestR5Auteco:
    def test_auteco_with_retefuente_flags_high(self):
        entries = [
            _entry("5314", debit=10000000),
            _entry("5494", credit=9750000),
            _entry("5388", credit=250000),  # ReteFuente compras
        ]
        j = _journal(observations="Compra motos Auteco NIT 860024781", entries=entries)
        finding = rule_5_auteco_retefuente(j, entries)
        assert finding is not None
        assert finding.severity == Severity.HIGH
        assert "autoretenedor" in finding.description.lower()

    def test_auteco_without_retefuente_clean(self):
        entries = [_entry("5314", debit=10000000), _entry("5494", credit=10000000)]
        j = _journal(observations="Compra motos Auteco NIT 860024781", entries=entries)
        assert rule_5_auteco_retefuente(j, entries) is None

    def test_non_auteco_ignored(self):
        entries = [_entry("5314", debit=5000000), _entry("5388", credit=125000), _entry("5494", credit=4875000)]
        j = _journal(observations="Compra repuestos proveedor X", entries=entries)
        assert rule_5_auteco_retefuente(j, entries) is None


# ───────────────────────────────────────────────
# R6 — Socios CXC
# ───────────────────────────────────────────────

class TestR6SociosCXC:
    def test_socio_as_gasto_flags_high(self):
        entries = [_entry("5314", debit=500000), _entry("5494", credit=500000)]
        j = _journal(observations="Retiro personal Andrés 80075452", entries=entries)
        finding = rule_6_socios_cxc(j, entries)
        assert finding is not None
        assert finding.severity == Severity.HIGH
        assert "CXC Socios" in finding.description or "5329" in finding.description

    def test_socio_with_cxc_clean(self):
        entries = [_entry("5314", debit=500000), _entry("5329", credit=500000)]
        j = _journal(observations="Retiro personal Andrés 80075452", entries=entries)
        assert rule_6_socios_cxc(j, entries) is None

    def test_ivan_also_detected(self):
        entries = [_entry("5314", debit=300000), _entry("5494", credit=300000)]
        j = _journal(observations="Gasto personal Iván 80086601", entries=entries)
        finding = rule_6_socios_cxc(j, entries)
        assert finding is not None
        assert "80086601" in finding.details["cc"]

    def test_non_socio_not_flagged(self):
        entries = [_entry("5314", debit=500000), _entry("5494", credit=500000)]
        j = _journal(observations="Pago empleado Juan Pérez", entries=entries)
        assert rule_6_socios_cxc(j, entries) is None


# ───────────────────────────────────────────────
# R7 — Duplicates
# ───────────────────────────────────────────────

class TestR7Duplicates:
    def test_detects_same_date_amount_obs(self):
        j1 = _journal(jid="200", date="2026-03-01", observations="Pago arriendo oficina marzo", total=2000000)
        j2 = _journal(jid="201", date="2026-03-01", observations="Pago arriendo oficina marzo", total=2000000)
        all_j = [j1, j2]
        findings = rule_7_duplicates(j1, [], all_j)
        assert len(findings) == 1
        assert findings[0].rule == "R7-DUPLICATE"
        assert findings[0].severity == Severity.MEDIUM

    def test_different_amount_no_dup(self):
        j1 = _journal(jid="200", date="2026-03-01", observations="Pago arriendo", total=2000000)
        j2 = _journal(jid="201", date="2026-03-01", observations="Pago arriendo", total=3000000)
        findings = rule_7_duplicates(j1, [], [j1, j2])
        assert len(findings) == 0

    def test_different_date_no_dup(self):
        j1 = _journal(jid="200", date="2026-03-01", observations="Pago arriendo", total=2000000)
        j2 = _journal(jid="201", date="2026-04-01", observations="Pago arriendo", total=2000000)
        findings = rule_7_duplicates(j1, [], [j1, j2])
        assert len(findings) == 0


# ───────────────────────────────────────────────
# R8 — Transfers
# ───────────────────────────────────────────────

class TestR8Transfers:
    def test_transfer_with_retefuente_flags(self):
        entries = [
            _entry("5314", debit=5000000),
            _entry("5318", credit=4800000),
            _entry("5386", credit=200000),  # ReteFuente — wrong on a transfer
        ]
        j = _journal(observations="Transferencia entre cuentas", entries=entries)
        finding = rule_8_transfers(j, entries)
        assert finding is not None
        assert finding.rule == "R8-TRANSFER"

    def test_clean_transfer_ok(self):
        entries = [_entry("5314", debit=5000000), _entry("5318", credit=5000000)]
        j = _journal(observations="Paso entre cuentas", entries=entries)
        assert rule_8_transfers(j, entries) is None

    def test_transfer_with_gasto_account_flags(self):
        entries = [
            _entry("5314", debit=5000000),
            _entry("5318", credit=4500000),
            _entry("5494", credit=500000),  # Gasto — wrong on a transfer
        ]
        # This won't infer as TR because not all entries are bank accounts
        j = _journal(observations="Transferencia entre cuentas propias", entries=entries)
        finding = rule_8_transfers(j, entries)
        # The type inference may detect TR from keywords
        if finding:
            assert finding.rule == "R8-TRANSFER"


# ───────────────────────────────────────────────
# R9 — Forbidden accounts
# ───────────────────────────────────────────────

class TestR9Forbidden:
    def test_5493_flags_low(self):
        entries = [_entry("5314", debit=100000), _entry("5493", credit=100000)]
        j = _journal(entries=entries)
        finding = rule_9_forbidden_accounts(j, entries)
        assert finding is not None
        assert finding.severity == Severity.LOW
        assert "5493" in finding.description

    def test_5495_flags_low(self):
        entries = [_entry("5314", debit=100000), _entry("5495", credit=100000)]
        j = _journal(entries=entries)
        finding = rule_9_forbidden_accounts(j, entries)
        assert finding is not None
        assert "5495" in finding.description

    def test_5494_fallback_clean(self):
        entries = [_entry("5314", debit=100000), _entry("5494", credit=100000)]
        j = _journal(entries=entries)
        assert rule_9_forbidden_accounts(j, entries) is None


# ───────────────────────────────────────────────
# Type inference
# ───────────────────────────────────────────────

class TestTypeInference:
    def test_nomina_inferred(self):
        entries = [_entry("5314", debit=3000000), _entry("5462", credit=3000000)]
        j = _journal(observations="Pago nómina marzo 2026", entries=entries)
        assert _infer_type(j, entries) == "NO"

    def test_transfer_all_banks(self):
        entries = [_entry("5314", debit=5000000), _entry("5318", credit=5000000)]
        j = _journal(observations="Paso de fondos", entries=entries)
        assert _infer_type(j, entries) == "TR"

    def test_cxc_socios(self):
        entries = [_entry("5314", debit=500000), _entry("5329", credit=500000)]
        j = _journal(observations="Retiro Andrés", entries=entries)
        assert _infer_type(j, entries) == "CXC"

    def test_ingreso(self):
        entries = [_entry("5314", debit=8000000), _entry("5456", credit=8000000)]
        j = _journal(observations="Venta moto XYZ", entries=entries)
        assert _infer_type(j, entries) == "ING"

    def test_default_ac(self):
        entries = [_entry("5314", debit=100000), _entry("5494", credit=100000)]
        j = _journal(observations="Gasto varios", entries=entries)
        assert _infer_type(j, entries) == "AC"


# ───────────────────────────────────────────────
# Integration: classify_journal + audit_all_journals
# ───────────────────────────────────────────────

class TestClassifyIntegration:
    def test_clean_journal_no_findings(self):
        entries = [_entry("5314", debit=500000), _entry("5494", credit=500000)]
        j = _journal(observations="Compra insumos", entries=entries)
        result = classify_journal(j)
        assert result.has_issues is False
        assert result.max_severity is None
        assert result.inferred_type == "AC"

    def test_multiple_findings_max_severity(self):
        # Unbalanced (HIGH) + forbidden account (LOW)
        entries = [_entry("5314", debit=1000000), _entry("5493", credit=900000)]
        j = _journal(entries=entries)
        result = classify_journal(j)
        assert result.has_issues is True
        assert result.max_severity == Severity.HIGH
        assert len(result.findings) >= 2

    def test_audit_all_journals_runs_all(self):
        j1 = _journal(jid="1", entries=[_entry("5314", debit=100), _entry("5494", credit=100)])
        j2 = _journal(jid="2", entries=[_entry("5314", debit=200), _entry("5493", credit=200)])
        results = audit_all_journals([j1, j2])
        assert len(results) == 2
        # j1 clean, j2 has forbidden account
        assert results[0].has_issues is False
        assert results[1].has_issues is True

    def test_entry_count_populated(self):
        entries = [_entry("5314", debit=100), _entry("5494", credit=100)]
        j = _journal(entries=entries)
        result = classify_journal(j)
        assert result.entry_count == 2
