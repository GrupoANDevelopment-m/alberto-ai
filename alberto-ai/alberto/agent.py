"""
Alberto AI — main agent.

Bundles real upstream engines (MiMo, Hermes) with Alberto's chat layer.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import identity
from .sandbox import LocalSandbox, make_sandbox, SandboxProtocol
from .model_router import ModelRouter, ModelConfig
from .engines import MiMoEngine, HermesEngine
from .personas import load_catalog, SquadCatalog, PersonaRegistry
from .shortcuts import ShortcutStore, Shortcut
from .orchestrator import Orchestrator, Strategy
from .conversation import (
    Conversation, ConversationStore, ALBERTO_SYSTEM_PROMPT, ALBERTO_SYSTEM_PROMPT_CONST,
    build_messages, recall_memory, detect_intent, build_catalog_block,
)
from .tools_registry import invoke_tool
from .runtime.mcp import MCPClient
from .runtime.extensions import ExtensionInstaller
from .runtime.app_creator import AppCreator
from .runtime.skill_engine import list_skills, find_skill, show_skill, run_skill
from .runtime.researcher import Researcher
from .runtime.learner import Learner
from .runtime.tester import AppTester
from .runtime.meta_controller import MetaController, SkillManager
from .runtime.self_healing import SelfHealer
from .runtime.smart_router import SmartRouter
from .runtime.integration import (
    hermes_tool_exists, invoke_hermes_tool,
    list_aiox_workflows, run_aiox_workflow,
    nemoclaw_sandbox_status, maybe_use_nemoclaw,
    setup_fallback_chain, is_fallback_model, get_mavis_takeover_prompt,
)
from .upstream_bridge import (
    get_upstream_summary, list_upstream_hermes_tools, list_upstream_hermes_skills,
    list_upstream_squads,
)


class Alberto:
    """Top-level agent. Wires real MiMo + real Hermes + Alberto orchestration."""

    def __init__(self, *, sandbox: Optional[SandboxProtocol] = None,
                 config: Optional[ModelConfig] = None,
                 catalog_dir: Optional[Path] = None,
                 personas_dir: Optional[Path] = None):
        self.sandbox = sandbox or LocalSandbox()
        self.router = ModelRouter(self._load_or_init_config())
        self.mimo = MiMoEngine(self.sandbox, self.router)
        self.hermes = HermesEngine(self.sandbox, mimo=self.mimo)
        self.mimo.start()
        self.hermes.start()

        self.shortcuts = ShortcutStore(self.sandbox.home() / ".mimo" / "shortcuts.json")
        self.conversations = ConversationStore(self.sandbox.home() / ".mimo" / "conversations.json")
        # New runtime modules
        self.mcp = MCPClient()
        self.extensions = ExtensionInstaller()
        self.app_creator = AppCreator()
        self.researcher = Researcher(sandbox=self.sandbox)
        self.learner = Learner(self.sandbox, self.mimo)
        self.tester = None  # created on demand with app path
        self.meta = MetaController(self)
        self.skill_manager = self.meta.skill_manager
        self.healer = SelfHealer(self)
        self.smart_router = SmartRouter(self)

        base = Path(__file__).parent.parent
        # Load Alberto squads + real AIOX upstream squads
        self.alberto_squads = load_catalog(catalog_dir or base / "workflows")
        self.aiox_squads = load_catalog(base / "upstream" / "aiox" / "squads")
        # Merge: Alberto first, then AIOX
        self.catalog = SquadCatalog()
        for name, squad in self.alberto_squads.squads.items():
            self.catalog.squads[name] = squad
        for name, squad in self.aiox_squads.squads.items():
            if name not in self.catalog.squads:
                self.catalog.squads[name] = squad

        self.personas = PersonaRegistry()
        self.personas.load_dir(personas_dir or base / "personas")

        self.orchestrator = Orchestrator()

    @property
    def name(self) -> str:
        return identity.NAME

    @property
    def version(self) -> str:
        return identity.VERSION

    def banner(self) -> str:
        return identity.get_banner()

    def status(self) -> Dict:
        return {
            "name": self.name,
            "version": self.version,
            "sandbox": type(self.sandbox).__name__,
            "mimo": {
                "running": self.mimo.is_running(),
                "binary": self.mimo.binary,
                "memory_keys": len(self.mimo.memory_list()),
            },
            "hermes": {
                "running": self.hermes.is_running(),
                "available_tools": len(self.hermes.available_tools()),
                "available_skills": len(self.hermes.available_skills()),
            },
            "shortcuts": len(self.shortcuts.list()),
            "squads_alberto": self.alberto_squads.list(),
            "squads_aiox": self.aiox_squads.list(),
            "active_squad": self.catalog.active_squad,
            "models": self.router.list_tasks(),
            "upstream": get_upstream_summary(),
        }

    # ===== Chat (natural conversation) =====
    def chat(self, prompt: str, *, conversation_id: Optional[str] = None) -> Dict:
        """Natural conversation. Returns dict with response + strategy + tool calls.

        Args:
            prompt: user text
            conversation_id: optional existing conversation to continue

        Returns:
            {response, strategy, tool_calls, conversation_id, persona}
        """
        # Get or create conversation
        conv = None
        if conversation_id:
            conv = self.conversations.get(conversation_id)
        if conv is None:
            # Continue most recent active conversation if <10 min old
            conv = self.conversations.latest_active(max_age_seconds=600)
        if conv is None:
            conv = self.conversations.create()
        conv.persona = "alberto"
        conv.active_squad = self.catalog.active_squad
        conv.active_goal = self.mimo.goal_get()

        # Detect intent
        intent = detect_intent(prompt)
        tool_calls = []

        # Shortcut: /s <key> [args]
        if "shortcut" in intent:
            expansion = self.shortcuts.expand(intent["shortcut"], intent.get("shortcut_args", ""))
            if expansion is None:
                conv.add("user", prompt)
                response = f"Não tenho atalho `/{intent['shortcut']}` ainda. Use `alberto s add {intent['shortcut']} <expansão>` pra criar."
                conv.add("assistant", response)
                self.conversations.save(conv)
                return {"response": response, "strategy": None, "tool_calls": [],
                        "conversation_id": conv.id, "shortcut_expansion": None}
            conv.add("user", prompt)
            conv.add("assistant", f"🔗 atalho → `{expansion}`")
            self.conversations.save(conv)
            return {"response": f"🔗 `{expansion}`", "strategy": None, "tool_calls": [],
                    "conversation_id": conv.id, "shortcut_expansion": expansion}

        # Squad activation intent
        if "squad" in intent:
            try:
                self.squad_activate(intent["squad"])
                conv.active_squad = intent["squad"]
            except KeyError:
                pass

        # Tool intent: try to call the tool
        if "tool" in intent:
            tool_name = intent["tool"]
            try:
                # Extract args from text via simple heuristics
                if tool_name == "browser":
                    import re
                    m = re.search(r"https?://\S+", prompt)
                    if m:
                        result = invoke_tool(self, "browser", {"url": m.group(0)})
                        tool_calls.append({"tool": "browser", "result": result})
                elif tool_name == "code_execution":
                    import re
                    m = re.search(r"```(?:python)?\n(.*?)\n```", prompt, re.S)
                    if m:
                        result = invoke_tool(self, "code_execution", {"code": m.group(1)})
                        tool_calls.append({"tool": "code_execution", "result": result})
                elif tool_name in ("voice.tts",):
                    text = re.sub(r"^(fala|diz em voz alta|narra)[\s:]+", "", prompt, flags=re.I)
                    result = invoke_tool(self, "voice.tts", {"text": text})
                    tool_calls.append({"tool": "voice.tts", "result": result})
                elif tool_name in ("memory.set", "mimo_memory"):
                    # Extract structured fact from "lembra que ..." or "meu X é Y"
                    import re as _re
                    prompt_l = prompt.lower()
                    key, value = None, None
                    # Try common structured patterns first
                    patterns = [
                        # "meu nome é X" / "me chamo X"
                        (r"(?:meu\s+nome\s+[eé]|me\s+chamo|sou\s+o)\s+([A-ZÀ-Úa-zà-ú][\w\s'-]{1,30})", "user.nome"),
                        # "meu email é X"
                        (r"meu\s+email\s+[eé]\s+([\w\.\-+]+@[\w\.\-]+\.\w+)", "user.email"),
                        # "trabalho com X" / "uso X" / "programo em X" / "minha linguagem é X"
                        (r"(?:trabalho\s+com|uso|programo\s+em|minha\s+linguagem\s+[eé]|minhas\s+linguagens?\s+[eéa-z]*)\s+([\w\+\#\s,\-]{2,40})", "user.stack"),
                        # "sou engenheiro/developer/..." (profession)
                        (r"sou\s+(\w[\w\s/-]{2,30}?)(?:\s+e\s+trabalho|\s*[\.\,]|$)", "user.profissao"),
                        # "tenho X anos" / "minha idade é X"
                        (r"(?:tenho|minha\s+idade\s+[eé])\s+(\d{1,2})\s+anos?", "user.idade"),
                        # "mor em X" / "minha cidade é X"
                        (r"(?:moro\s+em|minha\s+cidade\s+[eé])\s+([\w\s]{2,30})", "user.cidade"),
                        # "lembra que meu X é Y"
                        (r"lembra\s+que\s+(?:meu|minha|o|a)\s+([\w]{2,30}?)\s+[eé]\s+(.+?)(?:\.|$)", None),
                        # generic: "lembra que <sentence>" -> user.note
                        (r"lembra\s+que\s+(.+?)(?:\.|$)", "user.note"),
                    ]
                    for pat, k in patterns:
                        m = _re.search(pat, prompt, _re.I)
                        if m:
                            if k is None:
                                key = "user." + m.group(1).lower().strip()
                                value = m.group(2).strip()
                            elif k == "user.nome":
                                value = m.group(1).strip().rstrip(".,;:")
                                # Capture only first 1-3 words
                                value = " ".join(value.split()[:3])
                                key = k
                            elif k == "user.stack":
                                value = m.group(1).strip().rstrip(".,;")
                                key = k
                            else:
                                value = m.group(1).strip().rstrip(".,;:")
                                key = k
                            break
                    if key is None:
                        key = "user.note"
                        value = prompt
                    # Clean value
                    value = value.strip().rstrip(".")[:200]
                    result = invoke_tool(self, "mimo_memory", {"action": "set", "key": key, "value": value, "tags": "user"})
                    tool_calls.append({"tool": "mimo_memory", "result": result, "key": key, "value": value})
            except Exception as e:
                tool_calls.append({"tool": tool_name, "error": str(e)})

        # Strategy decision (after potential squad activation)
        strat = self.orchestrator.decide(prompt, active_squad=self.catalog.active_squad)

        # Pull memory context
        memory_context = recall_memory(self, prompt)

        # Build REAL system prompt with real catalog (kills hallucinations about what I have)
        persona = ALBERTO_SYSTEM_PROMPT(self) if callable(ALBERTO_SYSTEM_PROMPT) else ALBERTO_SYSTEM_PROMPT_CONST
        catalog_block = build_catalog_block(self)

        # Add user turn BEFORE building messages
        conv.add("user", prompt)
        messages = build_messages(conv, persona_prompt=persona,
                                  memory_context=memory_context,
                                  catalog_block=catalog_block)

        # Generate response
        try:
            # Smart Router v2: analyze user intent and inject routing decision
            from .runtime.smart_router_v2 import route_intent, build_route_prompt
            route = route_intent(prompt)
            route_ctx = build_route_prompt(route)

            # Skill auto-invocation: detect if prompt matches a known skill
            from .runtime.skill_engine import auto_invoke_skill
            skill_match = auto_invoke_skill(prompt)
            if skill_match:
                route_ctx += f"\n\n## Skill Auto-Invocation\nA skill matches your request: `{skill_match['skill']}` ({skill_match['description']}). Consider calling the `skill` tool with `name={skill_match['skill']}`."

            # Prepend Hermes/AIOX/NemoClaw context to system prompt
            integration_ctx = self._build_integration_context()
            if integration_ctx:
                # Insert before the last user message
                messages_with_ctx = messages[:-1] + [
                    {"role": "system", "content": integration_ctx}
                ] + messages[-1:]
                messages = messages_with_ctx

            # Add smart router decision
            messages = messages + [{"role": "system", "content": route_ctx}]

            # Detect if we're on fallback model (gemma4) — needs Mavis takeover
            on_fallback = is_fallback_model(self)
            if on_fallback:
                mavis_ctx = get_mavis_takeover_prompt()
                messages = messages + [{"role": "system", "content": mavis_ctx}]

            if strat.mode == "squad" and strat.squad:
                # Squad mode: run the pipeline, but also include the LLM-generated summary as natural response
                squad_result = self.run_squad(strat.squad, prompt)
                squad_text = self._format_squad_result(squad_result)
                response_text = squad_text
            elif strat.mode == "speculative":
                mm = self.mimo.max_mode(prompt)
                response_text = self._format_max_mode(mm)
            else:
                # Solo: call router with native function calling
                from .runtime.function_caller import run_tool_loop
                # Only use tool loop for "code" task AND primary model supports FC
                # On fallback (gemma4), we use plain chat + text-based Execute: interceptor
                if strat.task_routing == "code" and self._supports_function_calling() and not on_fallback:
                    fc_result = run_tool_loop(self, messages, task="code",
                                              max_iterations=8, max_tokens=2048,
                                              temperature=0.7)
                    response_text = fc_result["final_content"] or "[no content]"
                    # Surface tool calls to the rest of the pipeline
                    for tc in fc_result.get("tool_calls", []):
                        tool_calls.append({
                            "tool": tc.get("function", {}).get("name", "?"),
                            "args": tc.get("function", {}).get("arguments", "{}"),
                            "auto": True,
                        })
                else:
                    # Fallback or no-FC model: plain chat, Mavis will handle Execute: lines
                    resp = self.router.invoke(strat.task_routing, messages,
                                              max_tokens=2048, temperature=0.7)
                    response_text = resp["choices"][0]["message"]["content"]
                    if on_fallback:
                        response_text = f"⚠️ MAVIS FALLBACK MODE (gemma4)\n\n{response_text}"
        except Exception as e:
            response_text = f"[sem modelo configurado pra task={strat.task_routing}: {e}]"

        # If we made a tool call, weave it into the response
        if tool_calls:
            tool_section = "\n\n".join(
                f"**[{tc['tool']}]** " + json.dumps(tc.get('result', tc.get('error', '')), default=str, ensure_ascii=False)[:500]
                for tc in tool_calls
            )
            response_text = f"{response_text}\n\n{tool_section}" if response_text else tool_section

        # Anti-hallucination: if response says "vou executar" / "executando" /
        # contains a code block, BUT no tool_calls were made AND no "Comando: alberto ..."
        # line was emitted, try to extract and execute a real alberto CLI command.
        exec_result = None
        if not tool_calls:
            import re as _re_exec
            m = _re_exec.search(
                r"(?:Comando|Execute|Rodar|Run|Bash|Shell):\s*`?alberto\s+([^\n`]+)`?"
                r"|`alberto\s+([^\n`]+)`",
                response_text
            )
            if m:
                cmd_str = (m.group(1) or m.group(2) or "").strip()
                cmd = "alberto " + cmd_str
                # Ensure subprocess has alberto on PATH
                import os as _os_agent
                env = _os_agent.environ.copy()
                base_dir = str(Path(__file__).parent.parent)
                existing_pp = env.get("PYTHONPATH", "")
                if base_dir not in existing_pp:
                    env["PYTHONPATH"] = f"{base_dir}:{existing_pp}" if existing_pp else base_dir
                # If alberto CLI binary missing, fallback to python3 -m alberto.cli
                import shutil as _shutil
                if not _shutil.which("alberto"):
                    # Use the full path
                    cmd = f"{sys.executable} -m alberto.cli " + cmd_str
                try:
                    r = subprocess.run(cmd, shell=True, capture_output=True,
                                      text=True, timeout=30, env=env)
                    out = (r.stdout or "") + (r.stderr or "")
                    exec_result = {"cmd": cmd, "rc": r.returncode, "output": out[:1500]}
                    tool_calls.append({"tool": "alberto_cli", "result": exec_result})
                    response_text = (response_text + "\n\n"
                                    f"**Execução automática** (`{cmd}`):\n"
                                    f"```\n{out[:1500]}\n```")
                except subprocess.TimeoutExpired:
                    response_text += f"\n\n**Execução automática** timeout após 30s"
                except Exception as e:
                    response_text += f"\n\n**Execução automática** falhou: {e}"

        conv.add("assistant", response_text)
        self.conversations.save(conv)

        return {
            "response": response_text,
            "strategy": {"mode": strat.mode, "engine": strat.engine,
                         "squad": strat.squad, "task_routing": strat.task_routing,
                         "reason": strat.reason},
            "tool_calls": tool_calls,
            "conversation_id": conv.id,
            "executed": exec_result,
        }

    def _format_squad_result(self, result: Dict) -> str:
        lines = [f"⚡ Squad `{result.get('squad', '?')}` executou:\n"]
        for k, v in result.get("outputs", {}).items():
            if v is None:
                content = "(vazio)"
            elif isinstance(v, str):
                content = v
            else:
                content = json.dumps(v, default=str, ensure_ascii=False)
            lines.append(f"### {k}\n{content[:1500]}\n")
        return "\n".join(lines)

    def _format_max_mode(self, result: Dict) -> str:
        winner = result.get("winner", {})
        return winner.get("content", "[max mode: no winner]")

    # ===== Squad execution =====
    def run_squad(self, squad_name: str, prompt: str) -> Dict:
        squad = self.catalog.get(squad_name)
        if squad is None:
            return {"error": f"unknown squad: {squad_name}"}
        outputs: Dict[str, Optional[str]] = {}
        for step in squad.workflow:
            persona = squad.personas.get(step.persona) or self.personas.get(step.persona)
            sys_prompt = (persona.system_prompt if persona and hasattr(persona, 'system_prompt') else None) or f"You are {step.persona}."
            task_text = step.task
            try:
                if "{" in step.task:
                    task_text = step.task.format(**{k: (v or "")[:500] for k, v in outputs.items()})
            except (KeyError, IndexError, ValueError):
                task_text = step.task
            full = (
                f"{sys_prompt}\n\n---\n\nTask: {task_text}\n\n"
                f"User request: {prompt}\n\nPrevious outputs:\n"
                + "\n".join(f"[{k}]: {v[:500]}" for k, v in outputs.items())
            )
            try:
                resp = self.router.invoke("code", [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": full},
                ], max_tokens=2048, temperature=0.4)
                # Defensive: handle None or unexpected response shape
                if resp is None:
                    content = f"[step {step.persona}: empty response]"
                elif isinstance(resp, dict):
                    choices = resp.get("choices") or []
                    if choices and isinstance(choices, list):
                        msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
                        content = msg.get("content") or f"[step {step.persona}: no content in response]"
                    else:
                        content = f"[step {step.persona}: no choices in response]"
                else:
                    content = str(resp)[:500]
            except Exception as e:
                content = f"[error in step {step.persona}: {e}]"
            if step.output_to:
                outputs[step.output_to] = content
            else:
                outputs[f"_step_{step.persona}"] = content
        return {"squad": squad_name, "outputs": outputs}

    # ===== Shortcuts =====
    def shortcut_expand(self, key: str, args: str = "") -> Optional[str]:
        return self.shortcuts.expand(key, args)

    # ===== Memory facade =====
    def memory_set(self, key: str, value: str, tags: Optional[str] = None) -> None:
        self.mimo.memory_set(key, value, tags=tags)
    def memory_get(self, key: str) -> Optional[str]:
        return self.mimo.memory_get(key)
    def memory_search(self, query: str, limit: int = 10) -> List[Dict]:
        return self.mimo.memory_search(query, limit=limit)
    def memory_list(self) -> List[Dict]:
        return self.mimo.memory_list()
    def memory_delete(self, key: str) -> bool:
        return self.mimo.memory_delete(key)

    # ===== Model facade =====
    def model_set(self, task: str, *, provider: str, model_id: str,
                  base_url: str, credential_env: str, **options) -> None:
        from .model_router import ModelSpec
        self.router.set_task(task, ModelSpec(
            provider=provider, model_id=model_id,
            base_url=base_url, credential_env=credential_env,
            options=options or {},
        ))

    def model_test(self, task: str) -> Dict[str, str]:
        return self.router.render_env(task)

    def model_list(self) -> List[str]:
        return self.router.list_tasks()

    # ===== Squad facade =====
    def squad_list(self) -> List[str]:
        return self.catalog.list()

    def squad_activate(self, name: str) -> None:
        self.catalog.activate(name)

    def squad_hibernate(self) -> None:
        self.catalog.hibernate()

    def squad_describe(self, name: str) -> Optional[Dict]:
        s = self.catalog.get(name)
        if s is None:
            return None
        return {
            "name": s.name,
            "description": s.description,
            "personas": list(s.personas.keys()),
            "workflow": [{"persona": w.persona, "task": w.task, "output_to": w.output_to}
                         for w in s.workflow],
            "triggers": s.triggers,
            "source": "alberto" if name in self.alberto_squads.squads else "aiox",
        }

    def _load_or_init_config(self):
        """Load saved ModelConfig or create new."""
        from .model_router import ModelConfig
        cfg_path = self.sandbox.home() / ".mimo" / "model_config.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text())
                return ModelConfig.from_dict(data)
            except Exception:
                pass
        return ModelConfig(tasks={}, fallback_chain=[])

    def _supports_function_calling(self) -> bool:
        """Return True if the current code-task model has known function calling support.

        We use a heuristic: known models (deepseek-v4-pro, gpt-4, claude, minimax-m3, etc)
        support it. Unknown models default to False to avoid sending 'tools' that get ignored.
        """
        try:
            spec = self.router.config.resolve("code")
            if spec is None:
                return False
            mid = (spec.model_id or "").lower()
            # Known FC-capable models
            fc_indicators = [
                "deepseek", "gpt-4", "gpt-3.5", "claude", "minimax-m3",
                "glm", "qwen", "llama-3.1", "llama-3.2", "llama-3.3",
                "mistral-large", "command-r", "nemotron",
            ]
            return any(ind in mid for ind in fc_indicators)
        except Exception:
            return False

    def multimodal_chat(self, text: str, image_url: str, model: str = None) -> Dict[str, Any]:
        """Multimodal chat with vision model (default: diffusiongemma with thinking).

        Supported models:
        - google/diffusiongemma-26b-a4b-it (default, with enable_thinking)
        - meta/llama-3.2-90b-vision-instruct
        - moonshotai/kimi-k3 (max reasoning)

        Returns dict with content, thinking, model, usage.
        """
        from .runtime.integration import call_vision
        return call_vision(self, text, image_url, model=model)

    def _build_integration_context(self) -> str:
        """Build context block describing real Hermes/AIOX/NemoClaw integration status."""
        try:
            # Hermes tools count
            hermes_count = sum(1 for n in dir(__import__("alberto.engines.hermes_tools", fromlist=["x"]))
                             if n.startswith("tool_"))
            # AIOX workflows
            aiox_wfs = list_aiox_workflows()
            # NemoClaw status
            nc_status = nemoclaw_sandbox_status()
            # Hermes tools the LLM can invoke
            hermes_uses = [
                "browser (web browsing via Hermes stealth browser)",
                "code_execution (Python sandbox via UDS RPC)",
                "terminal (shell commands)",
                "file (read/write/list/exists)",
                "memory (persistent agent memory)",
                "skill (load + run Hermes skills)",
                "telegram/slack/discord/email/sms (messaging)",
                "voice_tts/voice_stt (speech in/out)",
                "image_gen/video_gen (multimodal)",
                "x_search (X/Twitter search)",
                "computer_use (desktop automation)",
            ]
            hermes_text = "\n".join(f"  - {u}" for u in hermes_uses)

            return (
                f"\n## Engines wired in\n"
                f"- **MiMo** (always-on): FTS5 memory, goal/judge, compose, subagent, snapshot, worktree. "
                f"22 core tools (bash, read, write, edit, multiedit, glob, grep, webfetch, websearch, "
                f"apply_patch, change_directory, memory, task, plan, question, skill, workflow, actor, "
                f"lsp, mcp_exa, codesearch, history) all registered as OpenAI tool_calls.\n"
                f"- **Hermes** (opt-in): {hermes_count} tools real (Python implementations). "
                f"When you need any of these, the system invokes hermes_tools directly:\n{hermes_text}\n"
                f"- **AIOX** (opt-in): claude-code-mastery squad loaded with {len(aiox_wfs)} workflows. "
                f"Run with `Comando: alberto aiox run <workflow>`.\n"
                f"- **NemoClaw** (sandbox): {nc_status['fallback']} active. "
                f"Docker {'available' if nc_status['docker_available'] else 'NOT available (using LocalSandbox)'}. "
                f"NemoClaw source at `{nc_status['source_path']}`.\n"
            )
        except Exception as e:
            return f"\n## Engines: (error building context: {e})\n"

    def _save_config(self):
        try:
            cfg_path = self.sandbox.home() / ".mimo" / "model_config.json"
            cfg_path.write_text(json.dumps(self.router.config.to_dict(), indent=2))
        except Exception:
            pass

    def shutdown(self) -> None:
        self._save_config()
        self.mimo.stop()
        self.hermes.stop()
        if hasattr(self.sandbox, "cleanup"):
            self.sandbox.cleanup()