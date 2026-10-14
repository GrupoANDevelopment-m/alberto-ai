"""Smart Router v2 — chooses the right engine/tool based on user intent.

Replaces the simple heuristic `_supports_function_calling()` with a real
intent classifier that decides:
- MiMo vs Hermes vs AIOX vs NemoClaw
- Which skill to invoke (if any)
- Whether to spawn a subagent
- Whether the task needs research / coding / deployment / security

Source of patterns: AIOX squad triggers + Hermes tool keywords.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class RouteDecision:
    engine: str  # mimo | hermes | aiox | nemoclaw
    tool_hint: Optional[str] = None  # which tool to invoke first
    skill_hint: Optional[str] = None  # which skill to load
    squad_hint: Optional[str] = None  # which squad to activate
    needs_research: bool = False
    needs_code: bool = False
    needs_deploy: bool = False
    needs_security: bool = False
    confidence: float = 0.0
    reasoning: str = ""


# Pattern → (engine, tool, skill, squad) routing rules
ROUTING_RULES: List[Dict[str, Any]] = [
    # === App creation ===
    {
        "patterns": [r"\b(crie?|criar|fazer|build)\s+(?:um|uma|o|a)\s+(?:app|aplica[cç][aã]o|projeto|sistema)\b",
                     r"\bapp\s*[-_ ]?creator\b", r"\bapp\s+create\b"],
        "engine": "mimo",
        "tool_hint": "alberto_cli",
        "skill_hint": "app_creator",
        "needs_code": True,
        "reasoning": "App creation request → use MiMo app_creator skill",
    },
    # === Code execution ===
    {
        "patterns": [r"\b(rode?|execute|roda[r]?)\s+(?:o|esse|este)?\s*(?:c[oó]digo|script|python|bash|shell)\b",
                     r"\bpython3?\s+-c\b", r"```(?:python|bash|sh)\n"],
        "engine": "mimo",
        "tool_hint": "bash",
        "needs_code": True,
        "reasoning": "Code execution request → use MiMo bash tool",
    },
    # === Web browsing ===
    {
        "patterns": [r"\b(abrir?|acesse?|fetch|navega[r]?|v[ae]\s+(?:a|para)\s+)?https?://",
                     r"\b(pegue?|busque?|pesquise?|procure?)\s+(?:no|na)?\s*(?:site|p[aá]gina|web|internet)"],
        "engine": "hermes",
        "tool_hint": "browser",
        "needs_research": True,
        "reasoning": "Web access request → use Hermes browser tool",
    },
    # === Web search ===
    {
        "patterns": [r"\b(busque?|pesquise?|procure?|search|google por)\s+(.+)",
                     r"\bo que [eé]\s+(.+)", r"\bdefini[cç][aã]o de (.+)"],
        "engine": "mimo",
        "tool_hint": "websearch",
        "needs_research": True,
        "reasoning": "Research request → use MiMo websearch tool",
    },
    # === File ops ===
    {
        "patterns": [r"\b(crie?|escreva?|salva[r]?|save|write)\s+(?:o\s+)?(?:arquivo|file)\b"],
        "engine": "mimo",
        "tool_hint": "write",
        "needs_code": True,
        "reasoning": "File write → use MiMo write tool",
    },
    {
        "patterns": [r"\b(leia?|read|abre[r]?|mostra[r]?|conte[uú]do\s+de)\s+(?:o\s+)?(?:arquivo|file)\b"],
        "engine": "mimo",
        "tool_hint": "read",
        "needs_code": True,
        "reasoning": "File read → use MiMo read tool",
    },
    # === Memory ===
    {
        "patterns": [r"\b(lembra?|lembre|memorize|anote|grava[r]?)\s+(?:que|de)\b",
                     r"\bmeu\s+nome\s+[eé]\b", r"\bsou\s+(?:o|a)\s+\w+"],
        "engine": "mimo",
        "tool_hint": "memory_set",
        "reasoning": "Memory operation → use MiMo memory tool",
    },
    # === Self-heal ===
    {
        "patterns": [r"\b(cur[ae]|heal|conserta?|repara[r]?)\b", r"\berro\s+de?\s+importa[cç][aã]o\b",
                     r"\bno\s+module\s+named\b", r"\bself.?heal"],
        "engine": "mimo",
        "tool_hint": "heal_attempt",
        "reasoning": "Self-heal request → use MiMo healer",
    },
    # === Squad / workflow ===
    {
        "patterns": [r"\bsquad\s+(\w+)", r"\bworkflow\s+(\w+)", r"\busa[r]?\s+(?:o|a)\s+squad\b"],
        "engine": "mimo",
        "squad_hint": "engineering",
        "reasoning": "Squad request → activate squad",
    },
    # === Skill invocation ===
    {
        "patterns": [r"\bskill\s+(\w+)", r"\binvo[ck][aã]\s+skill\b"],
        "engine": "mimo",
        "tool_hint": "skill",
        "reasoning": "Skill invocation → use MiMo skill tool",
    },
    # === Security test ===
    {
        "patterns": [r"\b(security|seguran[cç]a)\s+test", r"\bpen[ -]test", r"\bosv\b",
                     r"\bvulnerab\w+", r"\bXSS\b", r"\bcsrf\b"],
        "engine": "hermes",
        "tool_hint": "osv",
        "needs_security": True,
        "reasoning": "Security testing → use Hermes osv + MiMo tools",
    },
    # === Deploy ===
    {
        "patterns": [r"\b(deploy|publicar|subir)\b", r"\bvercel\b", r"\bdocker\b",
                     r"\bkubernetes\b", r"\bk8s\b"],
        "engine": "mimo",
        "needs_deploy": True,
        "reasoning": "Deployment → use MiMo app_creator + NemoClaw sandbox",
    },
    # === Plan mode ===
    {
        "patterns": [r"\b(plano|plan|spec|design|arquitetura)\s+", r"\bmake\s+plan\b"],
        "engine": "mimo",
        "tool_hint": "plan",
        "squad_hint": "engineering",
        "reasoning": "Planning task → enter plan mode + engineering squad",
    },
]


def route_intent(text: str) -> RouteDecision:
    """Route by the strongest matching intent while preserving multi-step needs.

    Specificity selects the primary route; flags from all matched rules are
    merged so compound requests (for example, research + code) do not lose
    secondary requirements merely because one rule matched first.
    """
    text_lower = text.lower().strip()
    if not text_lower:
        return RouteDecision(
            engine="mimo",
            confidence=0.0,
            reasoning="Empty request → ask for clarification before tool execution",
        )

    matches: List[tuple] = []
    for rule_index, rule in enumerate(ROUTING_RULES):
        matched_patterns = [pat for pat in rule["patterns"] if re.search(pat, text_lower)]
        if not matched_patterns:
            continue
        # Regex length after removing common metacharacters approximates how
        # constrained the trigger is; this is a ranking heuristic, not a
        # calibrated probability.
        specificity = max(
            len(re.sub(r"[\\\\^$.*+?{}()\\[\\]|]", "", pat))
            for pat in matched_patterns
        )
        matches.append((specificity, len(matched_patterns), -rule_index, rule, matched_patterns))

    if not matches:
        return RouteDecision(
            engine="mimo",
            confidence=0.5,
            reasoning="No specific pattern matched → default chat mode",
        )

    matches.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    _, _, _, primary, primary_patterns = matches[0]

    # Preserve secondary needs from every detected intent. The primary engine
    # and first tool hint still identify the safest initial step.
    needs_research = any(item[3].get("needs_research", False) for item in matches)
    needs_code = any(item[3].get("needs_code", False) for item in matches)
    needs_deploy = any(item[3].get("needs_deploy", False) for item in matches)
    needs_security = any(item[3].get("needs_security", False) for item in matches)

    specificity = matches[0][0]
    runner_up = matches[1][0] if len(matches) > 1 else 0
    # Keep confidence conservative when multiple similarly specific routes
    # compete. It is a routing heuristic, not a probability of task success.
    if len(matches) > 1 and specificity - runner_up < 8:
        confidence = 0.6
    elif specificity >= 18:
        confidence = 0.9
    else:
        confidence = 0.7

    reasoning = primary["reasoning"]
    if len(matches) > 1:
        labels = [item[3]["reasoning"].split(" → ")[0] for item in matches]
        reasoning += " | combined intents: " + ", ".join(dict.fromkeys(labels))
    if needs_code and re.search(r"\b(test|tests?|spec)\b", text_lower):
        reasoning += " | validation/testing requirement detected"

    return RouteDecision(
        engine=primary["engine"],
        tool_hint=primary.get("tool_hint"),
        skill_hint=primary.get("skill_hint"),
        squad_hint=primary.get("squad_hint"),
        needs_research=needs_research,
        needs_code=needs_code,
        needs_deploy=needs_deploy,
        needs_security=needs_security,
        confidence=confidence,
        reasoning=reasoning,
    )


def build_route_prompt(decision: RouteDecision) -> str:
    """Build a system prompt addition based on the route decision.

    This gets injected into the LLM context so it knows what to do.
    """
    parts = [
        f"\n## Smart Router Decision",
        f"Engine: **{decision.engine}**",
        f"Tool hint: {decision.tool_hint or '(none)'}",
        f"Skill hint: {decision.skill_hint or '(none)'}",
        f"Squad hint: {decision.squad_hint or '(none)'}",
        f"Needs: research={decision.needs_research}, code={decision.needs_code}, "
        f"deploy={decision.needs_deploy}, security={decision.needs_security}",
        f"Reasoning: {decision.reasoning}",
        "\nUse this guidance to pick the right tool/skill for the user's request.",
    ]
    return "\n".join(parts)
