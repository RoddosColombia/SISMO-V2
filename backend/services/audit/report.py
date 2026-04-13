"""
Audit Report Generator — Static HTML triage dashboard.

Generates a self-contained HTML file with:
- Summary metrics (total, % with issues, HIGH/MEDIUM/LOW counts)
- Sortable table with all journals and their findings
- Filterable by severity, type, date range
"""
from datetime import datetime, timezone
from services.audit.classify import JournalClassification, Severity


def generate_report_html(
    classifications: list[JournalClassification],
    output_path: str | None = None,
) -> str:
    """
    Generate a static HTML triage dashboard.

    Args:
        classifications: List of JournalClassification from audit_all_journals().
        output_path: If provided, write HTML to this file.

    Returns:
        HTML string.
    """
    total = len(classifications)
    with_issues = sum(1 for c in classifications if c.has_issues)
    high_count = sum(1 for c in classifications if c.max_severity == Severity.HIGH)
    medium_count = sum(1 for c in classifications if c.max_severity == Severity.MEDIUM)
    low_count = sum(1 for c in classifications if c.max_severity == Severity.LOW)
    clean_count = total - with_issues
    pct_issues = round(with_issues / total * 100, 1) if total > 0 else 0

    # Count by inferred type
    type_counts: dict[str, int] = {}
    for c in classifications:
        type_counts[c.inferred_type] = type_counts.get(c.inferred_type, 0) + 1

    # Build table rows
    rows_html = ""
    for c in sorted(classifications, key=lambda x: (
        0 if x.max_severity == Severity.HIGH else 1 if x.max_severity == Severity.MEDIUM else 2 if x.max_severity == Severity.LOW else 3,
        x.date,
    )):
        severity_class = ""
        severity_text = "OK"
        if c.max_severity == Severity.HIGH:
            severity_class = "severity-high"
            severity_text = "HIGH"
        elif c.max_severity == Severity.MEDIUM:
            severity_class = "severity-medium"
            severity_text = "MEDIUM"
        elif c.max_severity == Severity.LOW:
            severity_class = "severity-low"
            severity_text = "LOW"

        findings_html = ""
        for f in c.findings:
            findings_html += f'<div class="finding finding-{f.severity.value.lower()}">[{f.rule}] {_escape(f.description)}</div>'
        if not findings_html:
            findings_html = '<span class="ok">Sin hallazgos</span>'

        obs_short = _escape((c.observations or "")[:80])
        rows_html += f"""
        <tr class="{severity_class}" data-severity="{severity_text}" data-type="{c.inferred_type}" data-date="{c.date}">
            <td>{c.journal_id}</td>
            <td>{c.date}</td>
            <td class="money">${c.total:,.0f}</td>
            <td><span class="type-badge type-{c.inferred_type}">{c.inferred_type}</span></td>
            <td>{c.entry_count}</td>
            <td><span class="severity-badge {severity_class}">{severity_text}</span></td>
            <td class="findings-cell">{findings_html}</td>
            <td class="obs-cell" title="{obs_short}">{obs_short}</td>
        </tr>"""

    # Type distribution
    type_dist_html = ""
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        type_dist_html += f'<div class="type-stat"><span class="type-badge type-{t}">{t}</span> {count}</div>'

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SISMO Audit Report — RODDOS S.A.S.</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: #f8f9fa; color: #1a1a2e; padding: 24px; }}
.header {{ margin-bottom: 24px; }}
.header h1 {{ font-size: 24px; font-weight: 700; }}
.header .subtitle {{ color: #666; font-size: 14px; margin-top: 4px; }}
.metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 24px; }}
.metric {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
.metric .value {{ font-size: 32px; font-weight: 700; }}
.metric .label {{ font-size: 12px; color: #666; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }}
.metric.high .value {{ color: #dc2626; }}
.metric.medium .value {{ color: #f59e0b; }}
.metric.low .value {{ color: #3b82f6; }}
.metric.clean .value {{ color: #16a34a; }}
.metric.pct .value {{ color: #7c3aed; }}
.filters {{ display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }}
.filters select, .filters input {{ padding: 8px 12px; border: 1px solid #e5e7eb; border-radius: 8px; font-size: 13px; background: white; }}
.type-dist {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }}
.type-stat {{ display: flex; align-items: center; gap: 4px; font-size: 13px; }}
table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
th {{ background: #f1f5f9; padding: 12px 16px; text-align: left; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #475569; cursor: pointer; user-select: none; }}
th:hover {{ background: #e2e8f0; }}
td {{ padding: 10px 16px; border-top: 1px solid #f1f5f9; font-size: 13px; }}
tr:hover {{ background: #f8fafc; }}
.money {{ text-align: right; font-variant-numeric: tabular-nums; }}
.severity-badge {{ padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
.severity-high {{ background: #fef2f2; color: #dc2626; }}
.severity-medium {{ background: #fffbeb; color: #d97706; }}
.severity-low {{ background: #eff6ff; color: #3b82f6; }}
.type-badge {{ padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; background: #f1f5f9; color: #475569; }}
.type-AC {{ background: #f1f5f9; }} .type-NO {{ background: #ecfdf5; color: #059669; }}
.type-TR {{ background: #eff6ff; color: #2563eb; }} .type-CXC {{ background: #fef3c7; color: #d97706; }}
.type-RDX {{ background: #f0fdf4; color: #16a34a; }} .type-ING {{ background: #f0f9ff; color: #0284c7; }}
.type-D {{ background: #faf5ff; color: #7c3aed; }}
.finding {{ font-size: 12px; padding: 2px 0; }}
.finding-high {{ color: #dc2626; }} .finding-medium {{ color: #d97706; }} .finding-low {{ color: #3b82f6; }}
.ok {{ color: #16a34a; font-size: 12px; }}
.obs-cell {{ max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #6b7280; font-size: 12px; }}
.findings-cell {{ max-width: 400px; }}
</style>
</head>
<body>
<div class="header">
    <h1>SISMO Audit Report</h1>
    <div class="subtitle">RODDOS S.A.S. — Generado {now}</div>
</div>

<div class="metrics">
    <div class="metric"><div class="value">{total}</div><div class="label">Total Journals</div></div>
    <div class="metric pct"><div class="value">{pct_issues}%</div><div class="label">Con hallazgos</div></div>
    <div class="metric high"><div class="value">{high_count}</div><div class="label">HIGH (tributario)</div></div>
    <div class="metric medium"><div class="value">{medium_count}</div><div class="label">MEDIUM</div></div>
    <div class="metric low"><div class="value">{low_count}</div><div class="label">LOW</div></div>
    <div class="metric clean"><div class="value">{clean_count}</div><div class="label">Sin hallazgos</div></div>
</div>

<div class="type-dist">{type_dist_html}</div>

<div class="filters">
    <select id="filterSeverity" onchange="filterTable()">
        <option value="">Todas las severidades</option>
        <option value="HIGH">HIGH</option>
        <option value="MEDIUM">MEDIUM</option>
        <option value="LOW">LOW</option>
        <option value="OK">Sin hallazgos</option>
    </select>
    <select id="filterType" onchange="filterTable()">
        <option value="">Todos los tipos</option>
        {"".join(f'<option value="{t}">{t} ({c})</option>' for t, c in sorted(type_counts.items()))}
    </select>
    <input type="text" id="filterObs" placeholder="Buscar en observations..." oninput="filterTable()">
</div>

<table id="auditTable">
<thead>
<tr>
    <th onclick="sortTable(0)">ID</th>
    <th onclick="sortTable(1)">Fecha</th>
    <th onclick="sortTable(2)">Monto</th>
    <th onclick="sortTable(3)">Tipo</th>
    <th onclick="sortTable(4)">Entries</th>
    <th onclick="sortTable(5)">Severidad</th>
    <th>Hallazgos</th>
    <th>Observations</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>

<script>
function filterTable() {{
    const sev = document.getElementById('filterSeverity').value;
    const type = document.getElementById('filterType').value;
    const obs = document.getElementById('filterObs').value.toLowerCase();
    const rows = document.querySelectorAll('#auditTable tbody tr');
    rows.forEach(row => {{
        const rowSev = row.dataset.severity;
        const rowType = row.dataset.type;
        const rowObs = row.querySelector('.obs-cell')?.textContent?.toLowerCase() || '';
        let show = true;
        if (sev && rowSev !== sev) show = false;
        if (type && rowType !== type) show = false;
        if (obs && !rowObs.includes(obs)) show = false;
        row.style.display = show ? '' : 'none';
    }});
}}
let sortDir = {{}};
function sortTable(col) {{
    const table = document.getElementById('auditTable');
    const rows = Array.from(table.querySelectorAll('tbody tr'));
    sortDir[col] = !sortDir[col];
    rows.sort((a, b) => {{
        let va = a.cells[col].textContent.trim();
        let vb = b.cells[col].textContent.trim();
        if (col === 0 || col === 2 || col === 4) {{ va = parseFloat(va.replace(/[$,]/g, '')) || 0; vb = parseFloat(vb.replace(/[$,]/g, '')) || 0; }}
        if (va < vb) return sortDir[col] ? -1 : 1;
        if (va > vb) return sortDir[col] ? 1 : -1;
        return 0;
    }});
    const tbody = table.querySelector('tbody');
    rows.forEach(r => tbody.appendChild(r));
}}
</script>
</body>
</html>"""

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

    return html


def _escape(text: str) -> str:
    """Escape HTML entities."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
