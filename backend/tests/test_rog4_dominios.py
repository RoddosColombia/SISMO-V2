"""
ROG-4b — Test estático de separación de dominio entre agentes.

Escanea los handlers de cada agente buscando patrones de escritura sobre
colecciones MongoDB que no son suyas. Si encuentra alguno, falla el CI
antes del merge.

Cambia el carácter de ROG-4 de "regla documental" a "regla ejecutable".

Documentación: .claude/CLAUDE.md (sección ROG-4b — Cada colección operativa
tiene UN dueño).

Reglas de ownership (matriz de qué agente puede escribir qué):

| Colección                     | Dueño        |
|-------------------------------|--------------|
| roddos_events                 | TODOS (append via publish_event) |
| inventario_motos              | Loanbook     |
| loanbook, apartados           | Loanbook     |
| crm_clientes (sync inicial)   | Loanbook (en factura.venta.creada) |
| crm_clientes (gestiones)      | RADAR        |
| gestiones_cobranza            | RADAR        |
| radar_alertas                 | RADAR        |
| cfo_informes, cfo_alertas     | CFO          |
| conciliacion_jobs             | Contador     |
| backlog_movimientos           | Contador     |
| chat_sessions, agent_sessions | Sistema      |
| alegra_stats_cache            | DataKeeper   |
| system_health                 | Sistema (Circuit Breaker) |

Lecturas son libres — no se validan.
"""
from __future__ import annotations
from pathlib import Path
import re
import pytest

BACKEND = Path(__file__).parent.parent

# Operaciones de escritura que rastrea el test
WRITE_OPS = ("insert_one", "insert_many", "update_one", "update_many",
             "replace_one", "delete_one", "delete_many", "find_one_and_update",
             "find_one_and_replace", "find_one_and_delete", "bulk_write")

# Por cada directorio de agente, qué colecciones tiene PROHIBIDAS escribir.
# Las colecciones no listadas se asumen permitidas (whitelist invertida).
PROHIBIDOS_POR_AGENTE: dict[str, list[str]] = {
    # ── Contador ─────────────────────────────────────────────────────────────
    # Solo puede escribir en: roddos_events (vía publish_event), conciliacion_jobs,
    # backlog_movimientos, chat_sessions, alegra_stats_cache. Todo lo demás es
    # de otro dueño.
    "agents/contador/handlers/": [
        "inventario_motos",     # Loanbook (mutex)
        "loanbook",             # Loanbook
        "apartados",            # Loanbook
        "crm_clientes",         # Loanbook (sync) + RADAR (gestiones)
        "gestiones_cobranza",   # RADAR
        "radar_alertas",        # RADAR
        "cfo_informes",         # CFO
        "cfo_alertas",          # CFO
        "plan_cuentas_roddos",  # Deprecada Phase 5.5 — usar AlegraAccountsService
        "cartera_pagos",        # Loanbook
        "cxc_socios",           # Solo Alegra (CXC_socios id 5329)
        "cxc_clientes",         # CRM (Loanbook/RADAR)
    ],

    # ── Loanbook ─────────────────────────────────────────────────────────────
    # Dueño de inventario_motos, loanbook, apartados. Sync inicial de crm_clientes.
    # NO debe tocar nada del Contador (Alegra) ni de RADAR.
    "agents/loanbook/handlers/": [
        "gestiones_cobranza",   # RADAR
        "radar_alertas",        # RADAR
        "cfo_informes",         # CFO
        "cfo_alertas",          # CFO
        "conciliacion_jobs",    # Contador
        "backlog_movimientos",  # Contador
        "alegra_stats_cache",   # DataKeeper
    ],

    # ── RADAR ────────────────────────────────────────────────────────────────
    # Dueño de gestiones_cobranza, radar_alertas, gestiones en crm_clientes.
    "agents/radar/": [
        "inventario_motos",     # Loanbook
        "loanbook",             # Loanbook
        "apartados",            # Loanbook
        "cfo_informes",         # CFO
        "cfo_alertas",          # CFO
        "conciliacion_jobs",    # Contador
        "backlog_movimientos",  # Contador
        "alegra_stats_cache",   # DataKeeper
    ],

    # ── CFO ──────────────────────────────────────────────────────────────────
    # Dueño de cfo_informes, cfo_alertas. Solo lectura sobre todo lo demás.
    "agents/cfo/": [
        "inventario_motos", "loanbook", "apartados",
        "crm_clientes", "gestiones_cobranza", "radar_alertas",
        "conciliacion_jobs", "backlog_movimientos", "alegra_stats_cache",
        "plan_cuentas_roddos", "cartera_pagos",
    ],
}


def _scan_directory(directory: Path, prohibited_collections: list[str]) -> list[tuple[str, str, int, str]]:
    """Devuelve lista de (path_relativo, coleccion, lineno, snippet) violaciones."""
    violations: list[tuple[str, str, int, str]] = []
    if not directory.exists():
        return violations

    for py_file in directory.rglob("*.py"):
        # Saltar __pycache__ y __init__.py
        if "__pycache__" in str(py_file):
            continue

        try:
            lines = py_file.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue

        rel = py_file.relative_to(BACKEND).as_posix()

        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            # Saltar comentarios completos y docstrings simples
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            for col in prohibited_collections:
                # Buscar patrón db.{col}.{write_op}
                # También db["col"].{write_op}
                for op in WRITE_OPS:
                    patterns = [
                        rf"\b{col}\.{op}\b",
                        rf"\[['\"]?{col}['\"]?\]\.{op}\b",
                    ]
                    for pat in patterns:
                        if re.search(pat, line):
                            # Excepción: línea con comentario "# ROG-4 OK"
                            if "ROG-4 OK" in line or "rog-4 ok" in line.lower():
                                continue
                            violations.append((rel, col, lineno, line.strip()[:140]))

    return violations


def test_rog4b_separacion_dominio_estatica():
    """ROG-4b — Cada agente solo escribe en sus colecciones."""
    todas_las_violaciones: list[str] = []

    for prefix, prohibidos in PROHIBIDOS_POR_AGENTE.items():
        directory = BACKEND / prefix
        violaciones = _scan_directory(directory, prohibidos)
        for rel, col, lineno, snippet in violaciones:
            todas_las_violaciones.append(
                f"  {rel}:{lineno} -> {col} (escritura prohibida)\n      {snippet}"
            )

    if todas_las_violaciones:
        msg = (
            "ROG-4b VIOLADA — los siguientes handlers escriben en colecciones "
            "fuera de su dominio:\n\n"
            + "\n".join(todas_las_violaciones)
            + "\n\nVer .claude/CLAUDE.md (sección ROG-4b) para la matriz de "
            "ownership por colección. Si la escritura es legítima (ej: caso "
            "edge documentado), agrega comentario 'ROG-4 OK: <razón>' en la "
            "línea para que el test la ignore."
        )
        pytest.fail(msg)


def test_rog4a_alegra_es_fuente_unica():
    """ROG-4a — Plan de cuentas y montos contables solo en Alegra.
    Verifica que ningún handler use plan_cuentas_roddos como fuente
    de IDs de cuenta (debe usar AlegraAccountsService)."""
    handlers_dirs = [
        "agents/contador/handlers/",
        "agents/loanbook/handlers/",
        "agents/radar/",
        "agents/cfo/",
    ]
    violations: list[str] = []
    for d in handlers_dirs:
        directory = BACKEND / d
        if not directory.exists():
            continue
        for py in directory.rglob("*.py"):
            if "__pycache__" in str(py):
                continue
            text = py.read_text(encoding="utf-8")
            # Buscar lecturas de plan_cuentas_roddos (find_one, find, etc.)
            if re.search(r"plan_cuentas_roddos\.(find_one|find\(|aggregate)", text):
                # Permitir si hay comentario ROG-4 OK
                for lineno, line in enumerate(text.splitlines(), 1):
                    if "plan_cuentas_roddos" in line and "ROG-4 OK" not in line:
                        if re.search(r"\.find_one|\.find\(|\.aggregate", line):
                            rel = py.relative_to(BACKEND).as_posix()
                            violations.append(f"  {rel}:{lineno}  {line.strip()[:140]}")

    if violations:
        pytest.fail(
            "ROG-4a VIOLADA — plan_cuentas_roddos deprecada en Phase 5.5. "
            "Usar AlegraAccountsService (services/alegra_accounts.py) que "
            "lee desde Alegra GET /categories con cache 5 min:\n\n"
            + "\n".join(violations)
        )


def test_writes_use_publish_event_for_roddos_events():
    """Append a roddos_events debe ir vía publish_event, no insert_one directo
    (excepto en core/events.py que es la implementación del helper)."""
    violations: list[str] = []
    handlers_dirs = [
        "agents/contador/handlers/",
        "agents/loanbook/handlers/",
        "agents/radar/",
        "agents/cfo/",
    ]
    for d in handlers_dirs:
        directory = BACKEND / d
        if not directory.exists():
            continue
        for py in directory.rglob("*.py"):
            if "__pycache__" in str(py):
                continue
            text = py.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                # roddos_events.insert_one o roddos_events.update_one directos
                if re.search(r"roddos_events\.(insert_one|update_one|replace_one)", line):
                    if "ROG-4 OK" in line:
                        continue
                    rel = py.relative_to(BACKEND).as_posix()
                    violations.append(f"  {rel}:{lineno}  {line.strip()[:140]}")

    if violations:
        pytest.fail(
            "Escritura directa a roddos_events fuera de publish_event:\n\n"
            + "\n".join(violations)
            + "\n\nUsar `await publish_event(db, event_type, source, datos, ...)` "
            "de core.events. El helper persiste el evento + dispara el "
            "EventProcessor."
        )
