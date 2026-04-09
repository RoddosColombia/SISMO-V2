"""
test_router_integration.py — Verifies FOUND-01 (router) and FOUND-02 (system prompts).

Acceptance criteria from SISMO_V2_Fase0_Fase1.md C1 and C2:
  C1: Prompt claro -> despacho correcto >= 0.70; ambiguo -> clarificacion
  C2: Cada agente recibe su system prompt diferenciado
"""
import pytest
from core.router import route_intent, route_with_sticky, CONFIDENCE_THRESHOLD
from agents.prompts import SYSTEM_PROMPTS


# -- FOUND-01: Router confidence threshold -----------------------------------------------

class TestRouterConfidenceThreshold:
    def test_threshold_is_point_seven(self):
        assert CONFIDENCE_THRESHOLD == 0.70

    def test_gasto_routes_to_contador(self):
        r = route_intent("registra este gasto de arriendo")
        assert r.agent == 'contador', f"Expected contador, got {r.agent} (confidence: {r.confidence})"
        assert r.confidence >= 0.70

    def test_pl_routes_to_cfo(self):
        r = route_intent("cual es el p&l del mes de marzo")
        assert r.agent == 'cfo', f"Expected cfo, got {r.agent} (confidence: {r.confidence})"
        assert r.confidence >= 0.70

    def test_cobranza_routes_to_radar(self):
        r = route_intent("que clientes estan en mora hoy para cobranza")
        assert r.agent == 'radar', f"Expected radar, got {r.agent} (confidence: {r.confidence})"
        assert r.confidence >= 0.70

    def test_loanbook_routes_to_loanbook_agent(self):
        r = route_intent("como va el loanbook LB-0042 y el credito")
        assert r.agent == 'loanbook', f"Expected loanbook, got {r.agent} (confidence: {r.confidence})"
        assert r.confidence >= 0.70

    def test_ambiguous_message_triggers_clarification(self):
        r = route_intent("revisa esto")
        assert r.agent is None, f"Expected None for ambiguous, got {r.agent}"
        assert r.clarification is not None
        assert len(r.clarification) > 10

    def test_clarification_is_single_question(self):
        r = route_intent("no se que hacer con esto")
        # Must be a question, not an action
        assert r.clarification is not None
        assert "?" in r.clarification

    def test_multi_intent_returns_clarification_or_dispatch(self):
        """D-02: Multi-intent messages (tied scores) trigger clarification, never crash."""
        r = route_intent("registra el gasto Y dame el p&l")
        # Tied contador+cfo -> clarification returned
        # Either clarification OR a single agent dispatched (if one keyword dominiates)
        assert r.agent is not None or r.clarification is not None


class TestStickySession:
    def test_sticky_stays_with_current_agent_on_ambiguous(self):
        """D-03: Low-confidence message stays with current agent."""
        r = route_with_sticky("revisa esto", current_agent="contador")
        assert r.agent == 'contador'
        assert r.confidence >= 0.70

    def test_sticky_asks_to_switch_on_high_confidence_different_agent(self):
        """D-03: High-confidence for different agent generates switch question."""
        r = route_with_sticky("que clientes estan en mora hoy para cobranza", current_agent="contador")
        # Either routes to radar with clarification about switch, or stays with contador
        # The key: if it routes to radar, there should be a clarification about switching
        if r.agent == 'radar':
            assert r.clarification is not None, "Switch should generate clarification question"

    def test_no_current_agent_routes_normally(self):
        r = route_with_sticky("registra este gasto de arriendo", current_agent=None)
        assert r.agent == 'contador'


# -- FOUND-02: Differentiated system prompts ----------------------------------------

class TestSystemPrompts:
    def test_four_agents_have_prompts(self):
        assert set(SYSTEM_PROMPTS.keys()) == {'contador', 'cfo', 'radar', 'loanbook'}

    def test_contador_prompt_has_identity(self):
        assert "Agente Contador" in SYSTEM_PROMPTS['contador']
        assert "RODDOS" in SYSTEM_PROMPTS['contador']

    def test_cfo_prompt_has_identity(self):
        assert "CFO" in SYSTEM_PROMPTS['cfo']

    def test_radar_prompt_has_identity(self):
        assert "RADAR" in SYSTEM_PROMPTS['radar']

    def test_loanbook_prompt_has_identity(self):
        assert "Loanbook" in SYSTEM_PROMPTS['loanbook']

    def test_cfo_cannot_write_to_alegra_in_prompt(self):
        """Prompt must explicitly prohibit CFO from making Alegra writes."""
        assert "NUNCA hacer POST a Alegra" in SYSTEM_PROMPTS['cfo']

    def test_radar_cannot_write_to_alegra_in_prompt(self):
        assert "NUNCA hacer POST a Alegra" in SYSTEM_PROMPTS['radar']

    def test_loanbook_cannot_write_to_alegra_in_prompt(self):
        assert "NUNCA hacer POST a Alegra" in SYSTEM_PROMPTS['loanbook']

    def test_prompts_are_substantive(self):
        """Each prompt must be full text, not a stub."""
        for agent, prompt in SYSTEM_PROMPTS.items():
            assert len(prompt) > 500, (
                f"Prompt for {agent} is too short ({len(prompt)} chars) "
                "-- load verbatim from SISMO_V2_System_Prompts.md"
            )

    def test_contador_has_retention_rates(self):
        """Contador prompt must include retenciones rules."""
        assert "ReteFuente" in SYSTEM_PROMPTS['contador']
        assert "ReteICA" in SYSTEM_PROMPTS['contador']
        assert "0.414%" in SYSTEM_PROMPTS['contador']

    def test_contador_has_auteco_rule(self):
        """Autoretenedor rule must be in Contador prompt."""
        assert (
            "860024781" in SYSTEM_PROMPTS['contador']
            or "autoretenedor" in SYSTEM_PROMPTS['contador'].lower()
        )
