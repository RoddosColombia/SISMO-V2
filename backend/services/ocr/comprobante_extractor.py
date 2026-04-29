"""
services/ocr/comprobante_extractor.py — Extrae datos estructurados de
comprobantes de transferencia colombianos via Claude Vision.

Flujo:
  1. Recibe URL del archivo (imagen JPG/PNG o PDF).
  2. Descarga binario.
  3. Llama Anthropic claude-haiku-4-5 con visión.
  4. Prompt estructurado pide JSON con banco, monto, fecha, referencia, beneficiario.
  5. Valida beneficiario = RODDOS S.A.S. (NIT 901XXXXXXX o cuenta conocida).
  6. Devuelve dict normalizado o {"error": "..."}.

Costo aprox: $0.001 USD por comprobante (haiku 4.5).
Latencia: ~1-3s por imagen.

Sprint B8 (2026-04-28) — Cierre del bucle pago WhatsApp → causación automática.
"""
from __future__ import annotations
import base64
import json
import logging
import os
import re

import httpx
from anthropic import AsyncAnthropic

logger = logging.getLogger("ocr.comprobante")

# Cuentas de RODDOS para validar beneficiario
RODDOS_CUENTAS_VALIDAS = {
    "10082602029": "Bancolombia 2029",
    "10082602540": "Bancolombia 2540",
    "0210": "BBVA 0210",
    "0212": "BBVA 0212",
    "482": "Davivienda 482",
}
RODDOS_NIT = "901XXXXXXX"  # ajustar al NIT real de RODDOS S.A.S.

# Bancos colombianos validos (para normalizar nombres)
BANCOS_VALIDOS = {
    "bancolombia", "bbva", "davivienda", "banco de bogota", "banco bogota",
    "av villas", "popular", "occidente", "agrario", "nequi", "daviplata",
    "global66", "global 66", "movii", "rappipay", "lulo", "tpaga",
    "banco de la republica", "scotiabank", "itau", "gnb sudameris",
    "colpatria",
}

PROMPT_EXTRACCION = """Eres un extractor experto de comprobantes de transferencia bancaria colombianos.

Recibirás una imagen o PDF de un comprobante de pago. Tu tarea es extraer EXACTAMENTE estos datos como JSON válido:

{
  "banco_origen": "Bancolombia | BBVA | Davivienda | Nequi | Daviplata | Global66 | ...",
  "monto_cop": <numero entero sin separadores, en COP>,
  "fecha": "YYYY-MM-DD",
  "hora": "HH:MM" o null si no es visible,
  "referencia": "<numero o codigo de transaccion>",
  "beneficiario_nombre": "RODDOS S.A.S. o similar",
  "beneficiario_cuenta": "<numero de cuenta destino, sin guiones>" o null,
  "tipo_transferencia": "PSE | Transferencia | Pago QR | Nequi | Daviplata | Otro",
  "confianza": <0.0 a 1.0>
}

REGLAS:
- Si no puedes leer un campo crítico (monto, fecha, banco), responde:
  {"error": "no_legible", "campo_faltante": "<nombre>", "confianza": <num>}
- Si la imagen NO es un comprobante de transferencia, responde:
  {"error": "no_es_comprobante", "confianza": 0.0}
- monto_cop debe ser numero entero (179900, no "179.900" o "$179.900")
- fecha en formato ISO (2026-04-29, no "29/04/2026")
- confianza alta (>= 0.9) solo si todos los campos son legibles claramente

RESPONDE EXCLUSIVAMENTE EL JSON. No agregues explicaciones, comentarios ni markdown.
"""


def _normalize_banco(banco: str) -> str:
    """Normaliza nombre del banco para match con BANCOS_VALIDOS."""
    if not banco:
        return ""
    b = banco.lower().strip()
    # Remueve "S.A." y similares
    b = re.sub(r"\s*s\.?\s*a\.?\s*$", "", b)
    return b


async def _descargar_archivo(url: str, timeout: float = 20.0) -> tuple[bytes, str]:
    """Descarga el archivo desde URL. Retorna (bytes, content_type)."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        return resp.content, ctype


async def extraer_comprobante(media_url: str, media_type: str = "") -> dict:
    """Extrae datos estructurados del comprobante.

    Args:
        media_url: URL pública del archivo (de Mercately CDN).
        media_type: opcional, MIME type. Si no, se detecta del response.

    Returns:
        Dict con datos extraídos + validación. Estructura típica:
        {
          "success": True,
          "banco_origen": "Bancolombia",
          "monto_cop": 179900,
          "fecha": "2026-04-29",
          "hora": "14:32",
          "referencia": "12345678",
          "beneficiario_nombre": "RODDOS S.A.S.",
          "beneficiario_cuenta": "10082602029",
          "tipo_transferencia": "Transferencia",
          "confianza": 0.95,
          "validacion": {"beneficiario_es_roddos": True, "banco_reconocido": True},
          "raw_llm": "<respuesta cruda>",
        }

        En caso de error:
        {"success": False, "error": "no_legible|no_es_comprobante|http|timeout|...",
         "details": "..."}
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "ANTHROPIC_API_KEY no configurada"}

    # 1. Descargar archivo
    try:
        contenido, ctype_real = await _descargar_archivo(media_url)
    except Exception as exc:
        logger.error("descarga comprobante falló url=%s: %s", media_url, exc)
        return {"success": False, "error": "descarga_fallo", "details": str(exc)}

    media_type_final = (media_type or ctype_real or "image/jpeg").split(";")[0].strip()
    if not (media_type_final.startswith("image/") or media_type_final == "application/pdf"):
        return {"success": False, "error": "tipo_no_soportado",
                "details": f"media_type={media_type_final}"}

    # 2. Encodear base64 para Anthropic Vision
    b64 = base64.standard_b64encode(contenido).decode("ascii")

    # 3. Llamar Claude Vision
    client = AsyncAnthropic(api_key=api_key)
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image" if media_type_final.startswith("image/") else "document",
                        "source": {
                            "type": "base64",
                            "media_type": media_type_final,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": PROMPT_EXTRACCION},
                ],
            }],
        )
    except Exception as exc:
        logger.error("Anthropic Vision call falló: %s", exc)
        return {"success": False, "error": "anthropic_call_fallo", "details": str(exc)}

    # 4. Parse JSON de la respuesta
    raw = response.content[0].text if response.content else ""
    raw = raw.strip()
    # A veces el modelo envuelve en ```json ... ```
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("LLM no devolvió JSON valido raw=%r", raw[:200])
        return {"success": False, "error": "json_invalido",
                "details": str(exc), "raw_llm": raw[:500]}

    if "error" in data:
        return {"success": False, "error": data["error"],
                "confianza": data.get("confianza", 0),
                "raw_llm": raw[:500]}

    # 5. Validaciones
    banco = _normalize_banco(data.get("banco_origen", ""))
    banco_reconocido = any(b in banco for b in BANCOS_VALIDOS)

    beneficiario = (data.get("beneficiario_nombre", "") or "").lower()
    cuenta = data.get("beneficiario_cuenta", "") or ""
    cuenta_clean = "".join(ch for ch in cuenta if ch.isdigit())
    beneficiario_es_roddos = (
        "roddos" in beneficiario
        or any(c in cuenta_clean for c in RODDOS_CUENTAS_VALIDAS)
    )

    monto = data.get("monto_cop", 0) or 0
    fecha = data.get("fecha", "")
    confianza = float(data.get("confianza", 0) or 0)

    return {
        "success":              True,
        "banco_origen":         data.get("banco_origen", ""),
        "monto_cop":            int(monto) if monto else 0,
        "fecha":                fecha,
        "hora":                 data.get("hora"),
        "referencia":           str(data.get("referencia", "")),
        "beneficiario_nombre":  data.get("beneficiario_nombre", ""),
        "beneficiario_cuenta":  cuenta,
        "tipo_transferencia":   data.get("tipo_transferencia", ""),
        "confianza":            confianza,
        "validacion": {
            "banco_reconocido":         banco_reconocido,
            "beneficiario_es_roddos":   beneficiario_es_roddos,
            "monto_valido":             monto > 0,
            "fecha_valida":             bool(fecha and len(fecha) >= 10),
        },
        "raw_llm": raw[:500],
    }
