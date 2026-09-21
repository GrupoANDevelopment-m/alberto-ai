"""
Alberto AI — conversation layer.

Natural chat (not command dispatch). Maintains:
  - Conversation history (real, not stub)
  - Persona (the system prompt that shapes Alberto's voice)
  - Memory integration (he remembers across sessions)
  - Active squad (multi-stage workflow when one is active)
  - Active goal (judge verifies completion)
  - Tools (he can call real upstream tools when appropriate)

The conversation is "natural" because:
  - User types in pt-BR/EN freely, no /commands
  - Alberto responds as a person (with the persona's voice)
  - He remembers prior turns in the same session
  - He pulls from FTS5 memory for context
  - He calls tools (browser, code, TTS, etc.) when the user asks
  - He can activate a squad mid-conversation if the user wants
"""
from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

from .upstream_bridge import list_upstream_hermes_tools, list_upstream_hermes_skills
from .tools_registry import invoke_tool


@dataclass
class Turn:
    role: str           # "user" | "assistant" | "tool" | "system"
    content: str
    at: float = field(default_factory=time.time)
    tool: Optional[str] = None
    meta: Dict = field(default_factory=dict)


@dataclass
class Conversation:
    """A real conversation. Persists to disk."""
    id: str
    started_at: float
    turns: List[Turn] = field(default_factory=list)
    persona: str = "alberto"
    active_squad: Optional[str] = None
    active_goal: Optional[str] = None

    def add(self, role: str, content: str, **kwargs) -> Turn:
        t = Turn(role=role, content=content, **kwargs)
        self.turns.append(t)
        return t

    def last_at(self) -> float:
        return self.turns[-1].at if self.turns else self.started_at

    def history_for_llm(self, *, max_turns: int = 20) -> List[Dict[str, str]]:
        out = []
        for t in self.turns[-max_turns:]:
            out.append({"role": t.role, "content": t.content})
        return out


class ConversationStore:
    """Persists conversations to JSON. Survives restarts."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Conversation] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        for cid, c in raw.items():
            self._data[cid] = Conversation(
                id=cid,
                started_at=c.get("started_at", time.time()),
                turns=[Turn(**t) for t in c.get("turns", [])],
                persona=c.get("persona", "alberto"),
                active_squad=c.get("active_squad"),
                active_goal=c.get("active_goal"),
            )

    def _save(self) -> None:
        payload = {}
        for cid, c in self._data.items():
            payload[cid] = {
                "started_at": c.started_at,
                "persona": c.persona,
                "active_squad": c.active_squad,
                "active_goal": c.active_goal,
                "turns": [{"role": t.role, "content": t.content,
                           "at": t.at, "tool": t.tool, "meta": t.meta}
                          for t in c.turns],
            }
        tmp = self._path.with_suffix(".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        import os
        os.replace(tmp, self._path)

    def create(self, *, persona: str = "alberto") -> Conversation:
        cid = f"conv-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}"
        c = Conversation(id=cid, started_at=time.time(), persona=persona)
        self._data[cid] = c
        self._save()
        return c

    def get(self, cid: str) -> Optional[Conversation]:
        return self._data.get(cid)

    def save(self, c: Conversation) -> None:
        self._data[c.id] = c
        self._save()

    def list(self) -> List[str]:
        return sorted(self._data.keys())

    def latest_active(self, max_age_seconds: float = 600) -> Optional["Conversation"]:
        """Return most recently updated conversation if younger than max_age_seconds."""
        if not self._data:
            return None
        now = time.time()
        best = None
        best_at = 0.0
        for c in self._data.values():
            at = c.last_at() if hasattr(c, "last_at") else c.started_at
            if (now - at) <= max_age_seconds and at > best_at:
                best = c
                best_at = at
        return best


# ===== Alberto's voice =====
# Built dynamically so the LLM actually knows what it has. NO hardcoded counts —
# pulled from the real catalog at call time.
def ALBERTO_SYSTEM_PROMPT(alberto=None) -> str:
    """Return Alberto's system prompt with REAL counts of skills/tools/personas.

    Why dynamic: the LLM hallucinates "I have 779 skills" because it doesn't know
    how many. We inject the real numbers and a sample of names.
    """
    base = """Você é Alberto, um agente de IA brasileiro criado para ajudar com tarefas de coding, análise e operação.

Personalidade:
- Pragmático, direto, sem enrolação
- Português brasileiro por padrão, inglês quando o usuário preferir
- Humor seco, nunca no prejuízo do usuário
- Fala como um colega de trabalho competente, não como um robô
- **NUNCA invente ações que você não pode executar.** Se o usuário pedir algo que exija uma tool, diga exatamente qual tool e qual comando. Não finja que executou.

Princípios:
1. Aditivo, nunca substitui
2. Configurável pelo usuário, nunca assumido por você
3. Opt-in por padrão
4. OpenAI-compat como protocolo universal
5. Estado persistente é sagrado
6. **Honestidade radical** — se você não tem a tool ou não tem certeza, diz. Não alucine.

Estilo de resposta:
- Respostas naturais, em conversa — não em formato de comando
- Seja breve por padrão, detalhado quando a pergunta pede
- Cite a fonte quando usar memória ou tools
- Se não sabe, diz que não sabe
- Sempre em pt-BR a menos que o usuário use outro idioma
- **Não escreva blocos "tool_call" no JSON** — você não tem function calling habilitado nesta interface. Em vez disso, diga ao usuário: "Execute: alberto <subcommand> <args>"

Quando o usuário quiser ativar squad / mudar config / usar tool, faça naturalmente, sem exigir sintaxe especial. Ele também pode usar atalhos: /s <key> [args].

IMPORTANTE sobre memória: a camada de conversation já grava automaticamente fatos como "meu nome é X", "trabalho com Y", "moro em Z" antes de você ver. Não tente gravar de novo — apenas confirme ao usuário e use a memória já existente.
"""
    if alberto is None:
        return base

    # Inject REAL catalog snapshot so the LLM knows exactly what it has
    try:
        n_skills = len(alberto.hermes.available_skills())
        n_tools = len(alberto.hermes.available_tools())
        n_squads_alberto = len(alberto.alberto_squads.list())
        n_squads_aiox = len(alberto.aiox_squads.list())
        n_personas = len(alberto.personas.list())
        sample_skills = ", ".join(s["name"] for s in alberto.hermes.available_skills()[:15])
        sample_tools = ", ".join(t["name"] for t in alberto.hermes.available_tools()[:15])
        sample_squads = ", ".join(alberto.catalog.list()[:12])
        catalog_block = f"""

## Seu catálogo real (verificado agora)

- **Skills carregadas**: {n_skills} (amostra: {sample_skills})
- **Tools disponíveis**: {n_tools} (amostra: {sample_tools})
- **Squads Alberto**: {n_squads_alberto} | **Squads AIoX**: {n_squads_aiox} | **Total squads**: {n_squads_alberto + n_squads_aiox}
- **Personas**: {n_personas}
- **Active squad**: {alberto.catalog.active_squad or "(nenhum)"}
- **Goal atual**: {alberto.mimo.goal_get() or "(nenhum)"}

Comandos CLI que você PODE pedir ao usuário executar (ou que você executa via shell quando tiver tools):
- `alberto app create <name> "<description>" --output <path>` — cria app full-stack
- `alberto app test <path>` — roda smoke + curl tests no app criado
- `alberto heal attempt "<erro>"` — tenta auto-cura
- `alberto heal log` — vê histórico de curas
- `alberto skill list` / `alberto skill show <name>` / `alberto skill run <name>` — skills
- `alberto squad list` / `alberto squad activate <name>` — squads
- `alberto memory list|get|set|search` — memória persistente FTS5
- `alberto model set chat|code|reasoning <provider> <model_id> <base_url> <cred_env>` — configura modelos
- `alberto router list|test|rank` — smart router multi-modelo
- `alberto researcher "<query>"` — pesquisa multi-fonte
- `alberto meta plan "<objetivo>"` — planeja subtarefas via skill manager
- `alberto learn lesson|overcome|profile` — grava lessons learned
- `alberto autonomy start|tick|stop` — loop autônomo 24/7
- `alberto mcp add|list|call` — MCP servers
- `alberto tester smoke|perf|e2e` — testes automatizados

Sobre function calling: você NÃO emite tool_calls nesta interface. Em vez disso, termine a resposta com a linha "Comando: alberto <cmd> ..." quando o usuário precisar executar algo, e o sistema intercepta e executa automaticamente.
"""
        return base + catalog_block
    except Exception:
        return base


# Keep module-level constant for backward compat (some imports use ALBERTO_SYSTEM_PROMPT directly)
ALBERTO_SYSTEM_PROMPT_CONST = """Você é Alberto, um agente de IA brasileiro criado para ajudar com tarefas de coding, análise e operação.
Personalidade: pragmático, direto, sem enrolação. pt-BR padrão. Humor seco.
Princípios: aditivo, opt-in, OpenAI-compat, estado persistente, honestidade radical.
NUNCA invente ações. Se não tem a tool, diz. Se precisa executar, termine com "Comando: alberto <cmd>".
"""


def build_messages(conversation: Conversation, *, persona_prompt: str,
                    memory_context: str = "", catalog_block: str = "") -> List[Dict[str, str]]:
    """Build the messages list for the LLM.

    Order:
      1. system: Alberto's voice + persona overlay
      2. system: catalog block (real skills/tools/squads)
      3. system: memory context (if any)
      4. conversation history
    """
    msgs = [{"role": "system", "content": persona_prompt}]
    if catalog_block:
        msgs.append({"role": "system", "content": catalog_block})
    if memory_context:
        msgs.append({"role": "system", "content": f"## Memória relevante\n{memory_context}"})
    msgs.extend(conversation.history_for_llm())
    return msgs


def recall_memory(alberto, query: str, *, limit: int = 5) -> str:
    """Pull relevant memory context for the current turn."""
    try:
        hits = alberto.mimo.memory_search(query, limit=limit)
    except Exception:
        return ""
    if not hits:
        return ""
    lines = []
    for h in hits:
        lines.append(f"- **{h['key']}** = {h['value'][:300]}")
    return "\n".join(lines)


def build_catalog_block(alberto) -> str:
    """Build the catalog block to inject into system prompt."""
    try:
        n_skills = len(alberto.hermes.available_skills())
        n_tools = len(alberto.hermes.available_tools())
        n_squads = len(alberto.catalog.list())
        n_personas = len(alberto.personas.list())
        sample_skills = ", ".join(s.get("name", "?") for s in alberto.hermes.available_skills()[:20])
        sample_tools = ", ".join(t.get("name", "?") for t in alberto.hermes.available_tools()[:20])
        sample_squads = ", ".join(alberto.catalog.list()[:15])
        return (
            f"## Seu catálogo REAL (verificado agora)\n"
            f"- Skills: {n_skills} (ex: {sample_skills})\n"
            f"- Tools: {n_tools} (ex: {sample_tools})\n"
            f"- Squads: {n_squads} (ex: {sample_squads})\n"
            f"- Personas: {n_personas}\n"
            f"- Active squad: {alberto.catalog.active_squad or '(nenhum)'}\n"
            f"- Goal: {alberto.mimo.goal_get() or '(nenhum)'}\n"
        )
    except Exception as e:
        return f"## Catálogo: (erro ao carregar: {e})"


# ===== Intent detection (lightweight) =====

import re

def detect_intent(text: str) -> Dict[str, Any]:
    """Detect user intent from natural text.

    Returns dict with optional keys:
      - squad: name if user wants to activate a squad
      - tool: name if user wants to invoke a tool
      - shortcut: key if user typed /s <key>
      - goal: text if user set a new goal
    """
    t = text.strip()
    out: Dict[str, Any] = {}

    # Shortcut: /s <key> [args]
    m = re.match(r"^/s\s+(\S+)(?:\s+(.*))?$", t, re.S)
    if m:
        out["shortcut"] = m.group(1)
        out["shortcut_args"] = (m.group(2) or "").strip()
        return out

    # Squad activation
    known_squads = {
        "engineering", "research", "product", "incident", "data-ml",
        "growth", "finance", "support", "ml-ops", "content", "sales",
        "claude-code-mastery",
    }
    m = re.search(
        r"\b(usar?|ativa[r]?|vamos\s+usar?|manda)\s+(?:o\s+|a\s+|squad\s+)?(\S+)$",
        t, re.I
    )
    if m and m.group(2).lower() in known_squads:
        out["squad"] = m.group(2).lower()
        return out

    # Tool intent (heuristic)
    tool_keywords = {
        "browser": ["abrir", "fetch", "acessar", "pegar página", "site"],
        "code_execution": ["roda[r]? (?:o )?código", "executa[r]? (?:o )?python", "roda esse script"],
        "voice.tts": ["fala", "diz em voz alta", "narração", "tts"],
        "voice.stt": ["transcreve", "ouvir", "stt", "que tá falando"],
        "image.gen": ["gera[r]? (?:uma )?imagem", "desenha[r]?", "cria[r]? (?:um )?(?:desenho|foto)"],
        "video.gen": ["gera[r]? (?:um )?vídeo", "animação"],
        "x_search": ["busca[r]? no x", "twitter", "tweet"],
        # Memory.set — "lembra que", "anota", "guarda isso", AND implicit statements
        "memory.set": [
            r"lembra\s+que",
            r"anota\s+que",
            r"guarda\s+(?:que\s+)?isso",
            r"memoriza\s+isso",
            r"\bmeu\s+nome\s+[eé]\s+",   # "meu nome é X"
            r"\bme\s+chamo\s+",           # "me chamo X"
            r"\bmeu\s+email\s+[eé]\s+",   # "meu email é X"
            r"\btrabalho\s+com\s+\w+",    # "trabalho com X"
            r"\bminha?\s+stack\s+[eé]\s+", # "minha stack é X"
            r"\bminha?\s+linguagem\s+[eé]\s+",
            r"\bprogramo\s+em\s+",        # "programo em X"
            r"\bsou\s+(?:o|a)\s+\w+",     # "sou o/a X"
            r"\btenho\s+\d+\s+anos",      # "tenho 30 anos"
            r"\bmoro\s+em\s+",            # "moro em X"
            r"\bminha?\s+idade\s+[eé]\s+",
            r"\bminha?\s+cidade\s+[eé]\s+",
        ],
        "memory.get": [
            r"o\s+que\s+(?:você|eu)\s+(?:lembra|sei)\s+sobre",
            r"qual\s+(?:era|é)\s+(?:o|a|meu|minha)",
            r"\bvocê\s+lembra\b",
            r"\bme\s+lembra\b",
        ],
        "snapshot": ["checkpoint", "snapshot", "salva (?:o )?estado"],
    }
    for tool_name, kws in tool_keywords.items():
        for kw in kws:
            if re.search(rf"\b{kw}\b", t, re.I):
                out["tool"] = tool_name
                out["tool_args_text"] = t
                return out

    return out