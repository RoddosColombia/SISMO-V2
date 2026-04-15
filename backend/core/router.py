"""
Intent router for SISMO V2.
Strategy: keyword + rules first (deterministic), LLM fallback for ambiguous (not in this phase).
Confidence threshold: 0.70 (per D-01).
"""
from __future__ import annotations
import re
from dataclasses import dataclass

CONFIDENCE_THRESHOLD = 0.70

KEYWORDS: dict[str, list[str]] = {
    'contador': [
        "gasto", "factura", "pagar", "registra", "causar", "nómina", "nomina",
        "arriendo", "arrendamiento", "extracto", "conciliación", "conciliacion",
        "journal", "asiento", "proveedor", "retención", "retencion", "iva",
        "cobro", "egreso", "ingreso no operacional", "cxc socio",
    ],
    'cfo': [
        "p&l", "pl", "estado de resultados", "semáforo", "semaforo", "flujo de caja",
        "utilidad", "pérdida", "perdida", "balance", "informe financiero",
        "análisis", "analisis", "proyección", "proyeccion", "alerta financiera",
        "rentabilidad", "flujo",
    ],
    'radar': [
        "cobranza", "mora", "cobrar", "cuota vencida", "deudor", "vencida",
        "gestión de cobro", "gestion de cobro", "recordatorio de pago",
        "pago pendiente", "contactar cliente",
    ],
    'loanbook': [
        "loanbook", "crédito", "credito", "entrega de moto", "cronograma",
        "cuotas del crédito", "moto entregada", "plan de pago",
        "saldo del crédito", "saldo del credito", "lb-",
        "mora", "apartar", "apartado", "liquidar", "liquidación", "liquidacion",
        "pago cuota", "pago de cuota", "inventario", "motos disponibles",
        "cartera", "dpd", "entrega", "registrar entrega",
    ],
}


@dataclass
class IntentResult:
    agent: str | None     # 'contador' | 'cfo' | 'radar' | 'loanbook' | None
    confidence: float     # 0.0 – 1.0
    clarification: str | None  # Spanish question when confidence < THRESHOLD


def route_intent(message: str) -> IntentResult:
    """
    Route user message to an agent using keyword scoring.

    Scoring:
      - Each keyword match = +1 point for that agent
      - Confidence = agent_score / total_keyword_matches (capped at 1.0)
      - If one agent has a clear majority (score >= 2x second-place), confidence = 0.90
      - If scores are tied or all zero, confidence = 0.0 (ambiguous)
      - If confidence < THRESHOLD (0.70), return clarification question (per D-02)

    Sticky session handling (per D-03): callers pass current_agent as hint;
    if message has 0 matches but current_agent is set, score it 0.60 (stay with agent).
    """
    text = message.lower()
    scores: dict[str, int] = {agent: 0 for agent in KEYWORDS}

    for agent, kws in KEYWORDS.items():
        for kw in kws:
            if kw in text:
                scores[agent] += 1

    total = sum(scores.values())
    if total == 0:
        return IntentResult(
            agent=None,
            confidence=0.0,
            clarification=(
                "¿Esto es un tema contable, de análisis financiero, "
                "de cobranza o de créditos? Puedo hacer una cosa a la vez."
            ),
        )

    sorted_agents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_agent, top_score = sorted_agents[0]
    second_score = sorted_agents[1][1] if len(sorted_agents) > 1 else 0

    # Clear winner: top score at least 2x second AND at least 1 match
    if top_score >= 2 and (second_score == 0 or top_score >= 2 * second_score):
        confidence = 0.90
    elif top_score > second_score:
        # Some advantage but not dominant
        confidence = 0.50 + (top_score - second_score) / (top_score + 1) * 0.40
    else:
        confidence = 0.40  # tied

    if confidence >= CONFIDENCE_THRESHOLD:
        return IntentResult(agent=top_agent, confidence=confidence, clarification=None)

    # Ambiguous — ask one clarification question (per D-02)
    return IntentResult(
        agent=None,
        confidence=confidence,
        clarification=(
            "¿Esto es un tema contable, de análisis financiero, "
            "de cobranza o de créditos? Puedo hacer una cosa a la vez."
        ),
    )


def route_with_sticky(message: str, current_agent: str | None) -> IntentResult:
    """
    Wrapper that implements sticky session (D-03).
    If current_agent is set and the new intent confidently targets a DIFFERENT agent,
    returns a special IntentResult with agent != current_agent and clarification asking to switch.
    Otherwise, stays with current_agent at 0.70+ confidence.
    """
    result = route_intent(message)
    if current_agent is None:
        return result

    if result.confidence >= CONFIDENCE_THRESHOLD and result.agent != current_agent:
        # High confidence for a different agent — ask to switch (per D-03)
        return IntentResult(
            agent=result.agent,
            confidence=result.confidence,
            clarification=(
                f"Esto parece un tema de {result.agent}. "
                f"¿Quieres que te transfiera? Estás hablando con {current_agent}."
            ),
        )

    # Low confidence or same agent — stay with current
    if result.confidence < CONFIDENCE_THRESHOLD and current_agent:
        return IntentResult(
            agent=current_agent,
            confidence=0.75,  # sticky boost
            clarification=None,
        )

    return result
