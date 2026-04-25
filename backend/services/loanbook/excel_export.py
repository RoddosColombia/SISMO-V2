"""
services/loanbook/excel_export.py — Export de portafolio a Excel (.xlsx).

Produce un workbook con 2 hojas:
  - "Creditos": una fila por loanbook con comparación DB vs tabla PLAN_CUOTAS.
    Celdas con diferencias resaltadas en rojo para revisión humana.
  - "Cuotas": una fila por cuota con flags de corrupción (es_cuota_corrupta,
    motivo_corrupcion).

Función pura: recibe los loanbooks ya fetcheados, devuelve bytes del .xlsx.
Sin I/O de DB — el caller (endpoint HTTP) es responsable de traer los docs.
"""

from __future__ import annotations

import io
from datetime import date
from core.datetime_utils import now_bogota, today_bogota, now_iso_bogota

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from services.loanbook.reglas_negocio import get_num_cuotas, get_valor_total

# ─────────────────────── Paleta de estilos ────────────────────────────────────

_ROJO_FILL   = PatternFill("solid", fgColor="FFCCCC")   # diferencia detectada
_VERDE_FILL  = PatternFill("solid", fgColor="CCFFCC")   # valor correcto
_HEADER_FILL = PatternFill("solid", fgColor="1F497D")   # azul Roddos oscuro
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
_CENTER      = Alignment(horizontal="center", vertical="center", wrap_text=True)
_LEFT        = Alignment(horizontal="left",   vertical="center")


def _header_row(ws, cols: list[str]) -> None:
    """Escribe la fila de cabecera con estilo."""
    ws.append(cols)
    for cell in ws[1]:
        cell.font      = _HEADER_FONT
        cell.fill      = _HEADER_FILL
        cell.alignment = _CENTER
    ws.row_dimensions[1].height = 28


def _autofit(ws, min_width: int = 10, max_width: int = 40) -> None:
    """Ajuste aproximado de ancho de columnas."""
    for col_idx, col_cells in enumerate(ws.columns, start=1):
        max_len = max(
            (len(str(c.value)) if c.value is not None else 0) for c in col_cells
        )
        ws.column_dimensions[get_column_letter(col_idx)].width = min(
            max_width, max(min_width, max_len + 2)
        )


def _cuota_corrupta(c: dict, hoy_str: str) -> tuple[bool, str]:
    """Determina si una cuota es corrupta y el motivo.

    Returns:
        (es_corrupta: bool, motivo: str)
    """
    estado   = c.get("estado", "")
    fecha_c  = c.get("fecha", "") or ""
    fecha_p  = c.get("fecha_pago", "") or ""
    ref      = c.get("referencia")
    metodo   = c.get("metodo_pago")
    tiene_ev = bool(ref) or bool(metodo and metodo not in ("", "seed", None))

    # Caso A: fecha_pago registrada en el futuro
    if fecha_p and fecha_p > hoy_str:
        if not tiene_ev:
            return True, "fecha_pago futura sin referencia (imposible)"
        return True, "fecha_pago futura con referencia (requiere revisión)"

    # Caso B: cuota futura marcada pagada sin evidencia (seed corrupto)
    if estado == "pagada" and fecha_c > hoy_str and not tiene_ev:
        return True, "cuota futura marcada pagada sin evidencia"

    return False, ""


# ─────────────────────── Función principal ────────────────────────────────────

def generar_excel(loanbooks: list[dict]) -> bytes:
    """Genera el archivo Excel con 2 hojas y retorna los bytes.

    Args:
        loanbooks: Lista de documentos loanbook (sin _id de MongoDB).

    Returns:
        bytes — contenido del archivo .xlsx listo para StreamingResponse.
    """
    hoy     = today_bogota()
    hoy_str = hoy.isoformat()

    wb = openpyxl.Workbook()

    # ═══════════════════════════════════════════
    # HOJA 1 — Créditos
    # ═══════════════════════════════════════════
    ws_cred = wb.active
    ws_cred.title = "Creditos"

    cols_cred = [
        "loanbook_id",
        "Cliente",
        "Cédula",
        "Plan",
        "Modalidad",
        "Cuota monto (DB)",
        "Cuota inicial (DB)",
        "Num cuotas (DB)",
        "Num cuotas (tabla)",
        "Cuotas OK",
        "Valor total (DB)",
        "Valor total (tabla)",
        "Total OK",
        "Diferencia ($)",
        "Estado",
        "Fecha entrega",
        "Total pagado",
        "Saldo capital",
        "Cuotas futuras pagadas",
    ]
    _header_row(ws_cred, cols_cred)

    for lb in loanbooks:
        loanbook_id    = lb.get("loanbook_id", "?")
        cliente        = lb.get("cliente", {})
        nombre         = cliente.get("nombre", "?")
        cedula         = cliente.get("cedula", "?")
        plan_codigo    = lb.get("plan_codigo") or lb.get("plan", {}).get("codigo") or "?"
        modalidad      = lb.get("modalidad") or lb.get("plan", {}).get("modalidad") or "semanal"
        cuota_monto    = lb.get("cuota_monto") or lb.get("plan", {}).get("cuota_valor") or 0
        cuota_inicial  = lb.get("plan", {}).get("cuota_inicial", 0) or 0
        num_cuotas_db  = (
            lb.get("num_cuotas")
            or lb.get("plan", {}).get("total_cuotas")
            or len(lb.get("cuotas", []))
            or 0
        )
        valor_total_db = lb.get("valor_total", 0) or 0
        estado         = lb.get("estado", "?")
        fecha_entrega  = lb.get("fecha_entrega", "")
        total_pagado   = lb.get("total_pagado", 0) or 0
        saldo_capital  = lb.get("saldo_capital", 0) or lb.get("saldo_pendiente", 0) or 0

        # Valores correctos según tabla
        num_cuotas_ok_val  = get_num_cuotas(plan_codigo, modalidad)
        valor_total_ok_val = (
            get_valor_total(plan_codigo, modalidad, cuota_monto, cuota_inicial)
            if num_cuotas_ok_val is not None else None
        )

        cuotas_ok  = num_cuotas_ok_val is not None and num_cuotas_db == num_cuotas_ok_val
        total_ok   = valor_total_ok_val is not None and abs(valor_total_db - valor_total_ok_val) <= 1
        diferencia = (
            round(valor_total_db - valor_total_ok_val)
            if valor_total_ok_val is not None else "N/A"
        )

        # ¿Tiene cuotas futuras pagadas?
        cuotas_fut = sum(
            1 for c in lb.get("cuotas", [])
            if c.get("estado") == "pagada"
            and (c.get("fecha", "") or "") > hoy_str
            and not (bool(c.get("referencia")) or bool(c.get("metodo_pago") and c.get("metodo_pago") not in ("", "seed", None)))
        )

        row_idx = ws_cred.max_row + 1
        ws_cred.append([
            loanbook_id,
            nombre,
            cedula,
            plan_codigo,
            modalidad,
            cuota_monto,
            cuota_inicial,
            num_cuotas_db,
            num_cuotas_ok_val if num_cuotas_ok_val is not None else "N/A",
            "✓" if cuotas_ok else "✗",
            valor_total_db,
            valor_total_ok_val if valor_total_ok_val is not None else "N/A",
            "✓" if total_ok else "✗",
            diferencia,
            estado,
            fecha_entrega or "",
            total_pagado,
            saldo_capital,
            cuotas_fut if cuotas_fut > 0 else "",
        ])

        row = ws_cred[row_idx]

        # Resaltar num_cuotas
        row[7].fill = _VERDE_FILL if cuotas_ok else _ROJO_FILL  # col H (DB)
        row[8].fill = _VERDE_FILL if cuotas_ok else _ROJO_FILL  # col I (tabla)
        row[9].fill = _VERDE_FILL if cuotas_ok else _ROJO_FILL  # col J (ok)

        # Resaltar valor_total
        row[10].fill = _VERDE_FILL if total_ok else _ROJO_FILL  # col K (DB)
        row[11].fill = _VERDE_FILL if total_ok else _ROJO_FILL  # col L (tabla)
        row[12].fill = _VERDE_FILL if total_ok else _ROJO_FILL  # col M (ok)

        # Resaltar cuotas futuras pagadas
        if cuotas_fut > 0:
            row[18].fill = _ROJO_FILL  # col S

    _autofit(ws_cred)
    ws_cred.freeze_panes = "A2"

    # ═══════════════════════════════════════════
    # HOJA 2 — Cuotas
    # ═══════════════════════════════════════════
    ws_cuotas = wb.create_sheet("Cuotas")

    cols_cuotas = [
        "loanbook_id",
        "Cliente",
        "# Cuota",
        "Monto",
        "Estado",
        "Fecha cuota",
        "Fecha pago",
        "Referencia",
        "Método pago",
        "Es corrupta",
        "Motivo corrupción",
    ]
    _header_row(ws_cuotas, cols_cuotas)

    for lb in loanbooks:
        loanbook_id = lb.get("loanbook_id", "?")
        nombre      = lb.get("cliente", {}).get("nombre", "?")
        cuotas      = lb.get("cuotas", [])

        for c in cuotas:
            es_corrupta, motivo = _cuota_corrupta(c, hoy_str)
            row_idx = ws_cuotas.max_row + 1
            ws_cuotas.append([
                loanbook_id,
                nombre,
                c.get("numero"),
                c.get("monto"),
                c.get("estado"),
                c.get("fecha", ""),
                c.get("fecha_pago", "") or "",
                c.get("referencia", "") or "",
                c.get("metodo_pago", "") or "",
                "✗ Sí" if es_corrupta else "✓ No",
                motivo,
            ])

            if es_corrupta:
                for cell in ws_cuotas[row_idx]:
                    cell.fill = _ROJO_FILL

    _autofit(ws_cuotas)
    ws_cuotas.freeze_panes = "A2"

    # Serializar a bytes
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
