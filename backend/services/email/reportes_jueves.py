"""
services/email/reportes_jueves.py — Builder del reporte HTML cobranza jueves.

Genera HTML inline-styled (compatible con clientes email Gmail/Outlook) con:
- Header con métrica clave: cartera total, saldo en mora
- Distribución por sub-bucket Phase 7
- Top 5 urgentes con datos accionables
- Footer con próximas acciones programadas

Diseño: minimalista, móvil-first, sin imágenes externas (todo embedded).
"""
from __future__ import annotations
from datetime import date
from core.datetime_utils import today_bogota


def _fmt_cop(monto: float | int) -> str:
    return f"${int(monto):,}".replace(",", ".")


def _fmt_pct(p: float) -> str:
    return f"{p*100:.1f}%"


def construir_html_reporte(analisis: dict) -> str:
    """Construye HTML del reporte semanal de cartera.

    Args:
        analisis: output de cartera_revisor.analizar_cartera()

    Returns:
        str: HTML self-contained con styles inline.
    """
    fecha = analisis.get("fecha_corte", today_bogota().isoformat())
    cartera_total = analisis.get("cartera_total", 0)
    saldo_mora = analisis.get("saldo_en_mora", 0)
    n_mora = analisis.get("n_en_mora", 0)
    total_creditos = analisis.get("total_creditos", 0)
    pct_mora = analisis.get("pct_cartera_en_mora", 0)
    recuperabilidad = analisis.get("expectativa_recuperabilidad_cop", 0)
    perdida_esperada = analisis.get("perdida_esperada_cop", 0)
    distribucion = analisis.get("distribucion", {})
    top5 = analisis.get("top_5_urgentes", [])

    # Filas distribución
    filas_dist = []
    for bucket, d in distribucion.items():
        if d["count"] == 0 and bucket != "Current":
            continue
        filas_dist.append(f"""
        <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">
                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#{_color(bucket)};margin-right:8px;"></span>
                <strong>{bucket}</strong>
            </td>
            <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">{d['count']}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">{_fmt_cop(d['saldo'])}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;color:#6b7280;">{_fmt_pct(d['pct'])}</td>
        </tr>""")

    # Filas top 5
    filas_top5 = []
    for i, c in enumerate(top5, 1):
        bucket = c["sub_bucket"]
        filas_top5.append(f"""
        <tr style="background:{'#f9fafb' if i%2==0 else '#fff'};">
            <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-weight:600;">{i}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;">
                {c['cliente_nombre'][:30]}<br>
                <small style="color:#6b7280;">CC {c['cliente_cedula']} · {c['cliente_telefono']}</small>
            </td>
            <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">
                <strong>{_fmt_cop(c['saldo_pendiente'])}</strong><br>
                <small style="color:#6b7280;">{c['cuotas_pagadas']}/{c['cuotas_total']} cuotas</small>
            </td>
            <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;text-align:center;">
                <span style="background:#{_color(bucket)};color:white;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:600;">{bucket}</span><br>
                <small style="color:#6b7280;">DPD {c['dpd']}</small>
            </td>
        </tr>""")

    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f6f3f2;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;color:#1f2937;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;margin:24px auto;background:white;border-radius:12px;overflow:hidden;">
  <tr><td style="background:#006e2a;color:white;padding:24px 32px;">
    <h1 style="margin:0;font-size:24px;">Reporte Semanal Cobranza</h1>
    <p style="margin:8px 0 0;opacity:0.9;">RODDOS S.A.S. · Jueves {fecha}</p>
  </td></tr>

  <tr><td style="padding:24px 32px;">
    <h2 style="margin:0 0 16px;font-size:18px;">📊 Snapshot</h2>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td style="padding:12px;background:#f6f3f2;border-radius:8px;">
          <div style="color:#6b7280;font-size:12px;">CARTERA TOTAL</div>
          <div style="font-size:22px;font-weight:600;">{_fmt_cop(cartera_total)}</div>
          <div style="color:#6b7280;font-size:11px;">{total_creditos} créditos activos</div>
        </td>
        <td style="width:8px;"></td>
        <td style="padding:12px;background:#fef2f2;border-radius:8px;">
          <div style="color:#dc2626;font-size:12px;">EN MORA</div>
          <div style="font-size:22px;font-weight:600;color:#dc2626;">{_fmt_cop(saldo_mora)}</div>
          <div style="color:#6b7280;font-size:11px;">{n_mora} clientes · {_fmt_pct(pct_mora)} cartera</div>
        </td>
      </tr>
      <tr><td colspan="3" style="height:12px;"></td></tr>
      <tr>
        <td style="padding:12px;background:#ecfdf5;border-radius:8px;">
          <div style="color:#10b981;font-size:12px;">RECUPERABILIDAD ESPERADA</div>
          <div style="font-size:18px;font-weight:600;color:#10b981;">{_fmt_cop(recuperabilidad)}</div>
        </td>
        <td style="width:8px;"></td>
        <td style="padding:12px;background:#fff7ed;border-radius:8px;">
          <div style="color:#ea580c;font-size:12px;">PÉRDIDA ESPERADA</div>
          <div style="font-size:18px;font-weight:600;color:#ea580c;">{_fmt_cop(perdida_esperada)}</div>
        </td>
      </tr>
    </table>
  </td></tr>

  <tr><td style="padding:0 32px 24px;">
    <h2 style="margin:0 0 12px;font-size:18px;">🎯 Distribución por Sub-bucket</h2>
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
      <thead><tr style="background:#f9fafb;">
        <th style="padding:8px 12px;text-align:left;font-size:12px;color:#6b7280;text-transform:uppercase;">Bucket</th>
        <th style="padding:8px 12px;text-align:right;font-size:12px;color:#6b7280;text-transform:uppercase;">Clientes</th>
        <th style="padding:8px 12px;text-align:right;font-size:12px;color:#6b7280;text-transform:uppercase;">Saldo</th>
        <th style="padding:8px 12px;text-align:right;font-size:12px;color:#6b7280;text-transform:uppercase;">%</th>
      </tr></thead>
      <tbody>{''.join(filas_dist)}</tbody>
    </table>
  </td></tr>

  <tr><td style="padding:0 32px 24px;">
    <h2 style="margin:0 0 12px;font-size:18px;">🚨 Top 5 a Presionar Hoy</h2>
    {('<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;font-size:13px;"><thead><tr style="background:#f9fafb;"><th style="padding:8px 12px;text-align:left;">#</th><th style="padding:8px 12px;text-align:left;">Cliente</th><th style="padding:8px 12px;text-align:right;">Saldo</th><th style="padding:8px 12px;text-align:center;">Estado</th></tr></thead><tbody>' + ''.join(filas_top5) + '</tbody></table>') if top5 else '<p style="color:#10b981;text-align:center;padding:24px;background:#ecfdf5;border-radius:8px;"><strong>🎉 Cero clientes en mora — semana limpia.</strong></p>'}
  </td></tr>

  <tr><td style="padding:24px 32px;background:#f9fafb;color:#6b7280;font-size:12px;border-top:1px solid #e5e7eb;">
    <p style="margin:0 0 8px;">Este reporte se genera automáticamente cada jueves 8:00 AM Bogotá.</p>
    <p style="margin:0;">Para detalles ver <a href="https://sismo.roddos.com/loanbook" style="color:#006e2a;">sismo.roddos.com/loanbook</a></p>
  </td></tr>
</table>
</body></html>"""


def _color(bucket: str) -> str:
    from services.cobranza.sub_buckets import COLOR_POR_BUCKET
    return COLOR_POR_BUCKET.get(bucket, "6b7280")


def construir_subject(analisis: dict) -> str:
    """Subject del email — informativo y ordenable por bandeja."""
    fecha = analisis.get("fecha_corte", today_bogota().isoformat())
    n_mora = analisis.get("n_en_mora", 0)
    saldo_mora = analisis.get("saldo_en_mora", 0)
    if n_mora == 0:
        return f"[RODDOS] ✅ Cartera al día — {fecha}"
    return f"[RODDOS] ⚠️ {n_mora} en mora · {_fmt_cop(saldo_mora)} — {fecha}"
