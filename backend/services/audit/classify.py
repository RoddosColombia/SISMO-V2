"""
Audit Classification Engine — 9 rules for validating RODDOS journals.

Each rule returns a Finding with severity (HIGH/MEDIUM/LOW) and description.
The engine combines account IDs + observations text + amount patterns + known exceptions.
"""
import re
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    HIGH = "HIGH"      # Tax liability risk (ReteFuente, ReteICA errors)
    MEDIUM = "MEDIUM"  # Misclassification (wrong account, CXC vs gasto)
    LOW = "LOW"        # Cosmetic (missing prefix, minor labeling)


@dataclass
class Finding:
    rule: str
    severity: Severity
    description: str
    journal_id: str
    details: dict = field(default_factory=dict)


@dataclass
class JournalClassification:
    journal_id: str
    date: str
    total: float
    observations: str
    inferred_type: str  # AC, NO, RDX, ING, CI, D, RET, TR, CXC
    findings: list[Finding] = field(default_factory=list)
    entry_count: int = 0

    @property
    def has_issues(self) -> bool:
        return len(self.findings) > 0

    @property
    def max_severity(self) -> Severity | None:
        if not self.findings:
            return None
        severity_order = {Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1}
        return max(self.findings, key=lambda f: severity_order[f.severity]).severity


# ═══════════════════════════════════════════════════════
# KNOWN PATTERNS AND RULES
# ═══════════════════════════════════════════════════════

SOCIOS_CC = {"80075452": "Andrés Sanjuan", "80086601": "Iván Echeverri"}
AUTECO_NIT = "860024781"
CXC_SOCIOS_ID = "5329"  # 132505 CXC Socios y accionistas

# Real Alegra category IDs for banks (used to detect inter-bank transfers)
BANK_CATEGORY_IDS = {
    "5314", "5315",  # Bancolombia 2029, 2540
    "5318", "5319",  # BBVA 0210, 0212
    "5322",          # Davivienda
    "5321",          # Banco de Bogota
    "5536",          # Global66
    "5310",          # Caja general
    "5311",          # Caja menor
}

# ReteFuente account IDs (por pagar)
RETEFUENTE_IDS = {"5381", "5382", "5383", "5384", "5386", "5388"}

# ReteICA account IDs
RETEICA_IDS = {"5392", "5393"}

# Expense account IDs (gastos P&L)
GASTO_IDS = {
    "5462", "5470", "5471", "5472", "5473", "5475", "5476",
    "5480", "5484", "5485", "5486", "5487", "5490", "5491",
    "5492", "5494", "5497", "5499", "5500", "5501",
    "5507", "5508", "5509", "5510", "5533",
}

# Forbidden account IDs
FORBIDDEN_IDS = {"5493", "5495"}

# Keywords for type inference
NOMINA_KEYWORDS = ["nómina", "nomina", "salario", "sueldo", "salarios"]
ARRIENDO_KEYWORDS = ["arriend", "arriendo", "alquiler"]
TRANSFER_KEYWORDS = ["transferencia entre", "traslado entre", "paso entre cuentas"]
CXC_KEYWORDS = ["cxc socio", "retiro personal", "gasto personal"]
CUOTA_KEYWORDS = ["cuota", "pago cuota", "recaudo"]
DEPRECIACION_KEYWORDS = ["depreciación", "depreciacion"]

# ReteFuente rates by expense type (for validation)
RETEFUENTE_RATES = {
    "arriendo": 0.035,
    "servicios": 0.04,
    "honorarios_pn": 0.10,
    "honorarios_pj": 0.11,
    "compras": 0.025,
}
RETEICA_RATE = 0.00414
COMPRAS_BASE_MINIMA = 1_344_573.0


def _extract_entries(journal: dict) -> list[dict]:
    """Extract entry lines from journal."""
    return journal.get("entries", [])


def _get_entry_ids(entries: list[dict]) -> set[str]:
    """Get all account IDs from entries."""
    ids = set()
    for e in entries:
        eid = e.get("id") or e.get("account", {}).get("id")
        if eid:
            ids.add(str(eid))
    return ids


def _sum_debits(entries: list[dict]) -> float:
    return round(sum(float(e.get("debit", 0) or 0) for e in entries), 2)


def _sum_credits(entries: list[dict]) -> float:
    return round(sum(float(e.get("credit", 0) or 0) for e in entries), 2)


def _has_retefuente(entries: list[dict]) -> bool:
    ids = _get_entry_ids(entries)
    return bool(ids & RETEFUENTE_IDS)


def _has_reteica(entries: list[dict]) -> bool:
    ids = _get_entry_ids(entries)
    return bool(ids & RETEICA_IDS)


def _obs_lower(journal: dict) -> str:
    return (journal.get("observations") or "").lower()


def _obs_contains_any(journal: dict, keywords: list[str]) -> bool:
    obs = _obs_lower(journal)
    return any(kw in obs for kw in keywords)


def _infer_type(journal: dict, entries: list[dict]) -> str:
    """Infer comprobante type from observations + entry patterns."""
    obs = _obs_lower(journal)
    ids = _get_entry_ids(entries)

    # Nómina
    if _obs_contains_any(journal, NOMINA_KEYWORDS):
        return "NO"

    # CXC Socios
    if CXC_SOCIOS_ID in ids or _obs_contains_any(journal, CXC_KEYWORDS):
        return "CXC"
    for cc in SOCIOS_CC:
        if cc in obs:
            return "CXC"

    # Transferencia entre cuentas propias (all entries are bank accounts)
    debit_ids = {str(e.get("id") or e.get("account", {}).get("id", "")) for e in entries if float(e.get("debit", 0) or 0) > 0}
    credit_ids = {str(e.get("id") or e.get("account", {}).get("id", "")) for e in entries if float(e.get("credit", 0) or 0) > 0}
    if debit_ids.issubset(BANK_CATEGORY_IDS) and credit_ids.issubset(BANK_CATEGORY_IDS):
        return "TR"
    if _obs_contains_any(journal, TRANSFER_KEYWORDS):
        return "TR"

    # Depreciación
    if _obs_contains_any(journal, DEPRECIACION_KEYWORDS):
        return "D"

    # Recaudo cuota
    if _obs_contains_any(journal, CUOTA_KEYWORDS):
        return "RDX"

    # Ingreso (credit to ingreso accounts)
    ingreso_ids = {"5456", "5442", "5436"}
    if ids & ingreso_ids:
        return "ING"

    # Default: Ajuste Contable (gasto)
    return "AC"


# ═══════════════════════════════════════════════════════
# THE 9 RULES
# ═══════════════════════════════════════════════════════


def rule_1_balance_check(journal: dict, entries: list[dict]) -> Finding | None:
    """R1: Débito = Crédito (balance check). CRITICAL if unbalanced."""
    total_debit = _sum_debits(entries)
    total_credit = _sum_credits(entries)
    if abs(total_debit - total_credit) > 0.01:
        return Finding(
            rule="R1-BALANCE",
            severity=Severity.HIGH,
            description=f"Asiento desbalanceado: débitos ${total_debit:,.2f} != créditos ${total_credit:,.2f}",
            journal_id=str(journal.get("id")),
            details={"debit": total_debit, "credit": total_credit, "diff": round(total_debit - total_credit, 2)},
        )
    return None


def rule_2_account_correctness(journal: dict, entries: list[dict]) -> Finding | None:
    """R2: Cuenta de gasto correcta para la descripción."""
    obs = _obs_lower(journal)
    ids = _get_entry_ids(entries)

    # Check specific mismatches
    if any(kw in obs for kw in ARRIENDO_KEYWORDS) and "5480" not in ids:
        gasto_ids = ids & GASTO_IDS
        if gasto_ids and gasto_ids != {"5480"}:
            return Finding(
                rule="R2-ACCOUNT",
                severity=Severity.MEDIUM,
                description=f"Arriendo detectado en observations pero cuenta de gasto es {gasto_ids}, no 5480 (Arrendamientos)",
                journal_id=str(journal.get("id")),
                details={"expected": "5480", "found": list(gasto_ids)},
            )
    return None


def rule_3_retefuente_check(journal: dict, entries: list[dict]) -> Finding | None:
    """R3: ReteFuente aplicada cuando corresponde."""
    obs = _obs_lower(journal)
    total = _sum_debits(entries)

    # Skip if it's a transfer, nomina, or CXC
    inferred = _infer_type(journal, entries)
    if inferred in ("TR", "NO", "CXC", "RDX", "ING", "D"):
        return None

    # Check if Auteco (handled by rule 5)
    if AUTECO_NIT in obs or "auteco" in obs:
        return None

    # Arriendo should have ReteFuente
    if any(kw in obs for kw in ARRIENDO_KEYWORDS) and not _has_retefuente(entries):
        return Finding(
            rule="R3-RETEFUENTE",
            severity=Severity.HIGH,
            description=f"Arriendo por ${total:,.0f} sin ReteFuente 3.5%. Riesgo tributario.",
            journal_id=str(journal.get("id")),
            details={"tipo": "arriendo", "tasa_esperada": 0.035, "monto": total},
        )

    # Honorarios should have ReteFuente
    if any(kw in obs for kw in ["honorar", "asesoria", "asesoría"]) and not _has_retefuente(entries):
        return Finding(
            rule="R3-RETEFUENTE",
            severity=Severity.HIGH,
            description=f"Honorarios/asesoría por ${total:,.0f} sin ReteFuente (10% o 11%). Riesgo tributario.",
            journal_id=str(journal.get("id")),
            details={"tipo": "honorarios", "monto": total},
        )

    return None


def rule_4_reteica_check(journal: dict, entries: list[dict]) -> Finding | None:
    """R4: ReteICA 0.414% aplicada cuando corresponde."""
    obs = _obs_lower(journal)
    inferred = _infer_type(journal, entries)

    if inferred in ("TR", "RDX", "ING", "D"):
        return None

    # Only flag for gastos operativos that should have ReteICA
    if inferred == "AC" and not _has_reteica(entries):
        total = _sum_debits(entries)
        if total > 100_000:  # Don't flag tiny amounts
            # Only flag specific known categories
            if any(kw in obs for kw in ARRIENDO_KEYWORDS + ["servicio", "honorar", "comision"]):
                return Finding(
                    rule="R4-RETEICA",
                    severity=Severity.MEDIUM,
                    description=f"Gasto por ${total:,.0f} sin ReteICA Bogotá 0.414%.",
                    journal_id=str(journal.get("id")),
                    details={"tasa": 0.00414, "monto": total, "reteica_esperada": round(total * 0.00414, 2)},
                )
    return None


def rule_5_auteco_retefuente(journal: dict, entries: list[dict]) -> Finding | None:
    """R5: Auteco NIT 860024781 NO debe tener ReteFuente (autoretenedor)."""
    obs = _obs_lower(journal)
    if AUTECO_NIT in obs or "auteco" in obs:
        if _has_retefuente(entries):
            return Finding(
                rule="R5-AUTECO",
                severity=Severity.HIGH,
                description="Auteco (NIT 860024781) tiene ReteFuente aplicada. Es autoretenedor, NUNCA debe tener ReteFuente.",
                journal_id=str(journal.get("id")),
                details={"nit": AUTECO_NIT, "autoretenedor": True},
            )
    return None


def rule_6_socios_cxc(journal: dict, entries: list[dict]) -> Finding | None:
    """R6: Gastos de socios en CXC Socios (5329), NO en gastos operativos."""
    obs = _obs_lower(journal)
    ids = _get_entry_ids(entries)

    for cc, nombre in SOCIOS_CC.items():
        if cc in obs or nombre.lower().split()[0] in obs:
            # Check if CXC account is used
            if CXC_SOCIOS_ID not in ids:
                # Check if a gasto account is used instead
                gasto_used = ids & GASTO_IDS
                if gasto_used:
                    return Finding(
                        rule="R6-SOCIOS-CXC",
                        severity=Severity.HIGH,
                        description=f"Gasto de socio {nombre} (CC {cc}) registrado como gasto operativo ({gasto_used}), NO como CXC Socios (5329). Distorsiona el P&L.",
                        journal_id=str(journal.get("id")),
                        details={"socio": nombre, "cc": cc, "expected": CXC_SOCIOS_ID, "found": list(gasto_used)},
                    )
    return None


def rule_7_duplicates(journal: dict, entries: list[dict], all_journals: list[dict]) -> list[Finding]:
    """R7: Detectar duplicados (mismo monto + misma fecha + misma cuenta principal)."""
    findings = []
    jid = str(journal.get("id"))
    date = journal.get("date", "")
    total = float(journal.get("total", 0) or 0)
    obs = (journal.get("observations") or "")[:50]

    for other in all_journals:
        oid = str(other.get("id"))
        if oid == jid:
            continue
        if other.get("date") == date and abs(float(other.get("total", 0) or 0) - total) < 0.01:
            other_obs = (other.get("observations") or "")[:50]
            # Check if observations are similar
            if _similar_text(obs, other_obs):
                findings.append(Finding(
                    rule="R7-DUPLICATE",
                    severity=Severity.MEDIUM,
                    description=f"Posible duplicado: Journal #{oid} mismo monto (${total:,.0f}), misma fecha ({date}), observations similares.",
                    journal_id=jid,
                    details={"duplicate_of": oid, "date": date, "total": total},
                ))
                break  # Only flag first match per journal
    return findings


def _similar_text(a: str, b: str, threshold: float = 0.8) -> bool:
    """Similarity check: ratio of common words. Threshold 0.8 to avoid false positives."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return False
    # If observations differ in unique words (names, IDs), they're different journals
    diff = words_a.symmetric_difference(words_b)
    if len(diff) >= 2:
        return False
    common = words_a & words_b
    return len(common) / max(len(words_a), len(words_b)) >= threshold


def rule_8_transfers(journal: dict, entries: list[dict]) -> Finding | None:
    """R8: Transferencias entre cuentas propias NO deben tener retenciones ni estar como gasto."""
    inferred = _infer_type(journal, entries)
    if inferred != "TR":
        return None

    # Transfers should NOT have retefuente or reteica
    if _has_retefuente(entries) or _has_reteica(entries):
        return Finding(
            rule="R8-TRANSFER",
            severity=Severity.MEDIUM,
            description="Transferencia entre cuentas propias tiene retenciones aplicadas. Las transferencias internas no generan retenciones.",
            journal_id=str(journal.get("id")),
            details={"has_retefuente": _has_retefuente(entries), "has_reteica": _has_reteica(entries)},
        )

    # Transfers should NOT use gasto accounts
    ids = _get_entry_ids(entries)
    gasto_used = ids & GASTO_IDS
    if gasto_used:
        return Finding(
            rule="R8-TRANSFER",
            severity=Severity.MEDIUM,
            description=f"Transferencia entre cuentas propias usa cuenta de gasto ({gasto_used}). Debería ser solo cuentas de banco.",
            journal_id=str(journal.get("id")),
            details={"gasto_accounts": list(gasto_used)},
        )
    return None


def rule_9_forbidden_accounts(journal: dict, entries: list[dict]) -> Finding | None:
    """R9: NUNCA usar 5493 ni 5495. Fallback correcto es 5494."""
    ids = _get_entry_ids(entries)
    forbidden_used = ids & FORBIDDEN_IDS
    if forbidden_used:
        return Finding(
            rule="R9-FORBIDDEN",
            severity=Severity.LOW,
            description=f"Usa cuenta(s) prohibida(s): {forbidden_used}. Fallback correcto es 5494 (Gastos Varios).",
            journal_id=str(journal.get("id")),
            details={"forbidden": list(forbidden_used), "correct_fallback": "5494"},
        )
    return None


# ═══════════════════════════════════════════════════════
# MAIN CLASSIFICATION FUNCTION
# ═══════════════════════════════════════════════════════


def classify_journal(journal: dict, all_journals: list[dict] | None = None) -> JournalClassification:
    """
    Classify a single journal and run all 9 validation rules.

    Args:
        journal: Full journal dict from Alegra API.
        all_journals: All journals (needed for duplicate detection).

    Returns:
        JournalClassification with inferred type and findings.
    """
    entries = _extract_entries(journal)
    jid = str(journal.get("id", "?"))
    date = journal.get("date", "")
    total = float(journal.get("total", 0) or 0)
    obs = journal.get("observations", "")

    inferred_type = _infer_type(journal, entries)

    classification = JournalClassification(
        journal_id=jid,
        date=date,
        total=total,
        observations=obs,
        inferred_type=inferred_type,
        entry_count=len(entries),
    )

    # Run all 9 rules
    for rule_fn in [
        rule_1_balance_check,
        rule_2_account_correctness,
        rule_3_retefuente_check,
        rule_4_reteica_check,
        rule_5_auteco_retefuente,
        rule_6_socios_cxc,
        rule_8_transfers,
        rule_9_forbidden_accounts,
    ]:
        finding = rule_fn(journal, entries)
        if finding:
            classification.findings.append(finding)

    # Rule 7 needs all journals for comparison
    if all_journals:
        dup_findings = rule_7_duplicates(journal, entries, all_journals)
        classification.findings.extend(dup_findings)

    return classification


def audit_all_journals(journals: list[dict]) -> list[JournalClassification]:
    """Run classification + validation on all journals."""
    results = []
    for j in journals:
        classification = classify_journal(j, all_journals=journals)
        results.append(classification)
    return results
