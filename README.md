# 🤖 Alberto AI v1.8.4

**Alberto AI** is the central chat and orchestration layer. It integrates distinct runtimes and keeps their responsibilities separate:

- 🛡️ **[NVIDIA NemoClaw](https://github.com/nvidia/nemoclaw)** — sandbox and security controls
- ⚡ **[Xiaomi MiMoCode](https://github.com/Xiaomi/mimo)** — memory and application-generation capabilities
- 🧠 **[Nous Research Hermes](https://github.com/NousResearch/hermes-agent)** — tools, browser, execution and MCP
- 🤝 **CrewAI** — squad/team execution; it does not orchestrate Hermes and MiMo
- 🔀 **ModelRouter** — model/provider selection and fallback for Alberto Chat

Legacy AIOX workflow assets are kept as catalog material; they are not the central coordinator.

---

## ⚡ Quick Start — instalação local segura

Consulta primeiro o [guia completo de instalação local](INSTALL-LOCAL.md). O método recomendado usa Python 3.11+ e ambiente virtual; não instala dependências globalmente.

```bash
git clone https://github.com/GrupoANDevelopment-m/alberto-ai.git
cd alberto-ai
bash install_deps.sh
source .venv/bin/activate
python scripts/alberto_doctor.py
```

Configura o ModelRouter para NVIDIA (o script não guarda os valores das chaves):

```bash
export NVIDIA_API_KEY="A_TUA_CHAVE_PRINCIPAL"
export NVIDIA_API_KEY_FALLBACK="A_TUA_CHAVE_FALLBACK"
python scripts/configure_nvidia.py
alberto model list
alberto-serve --host 127.0.0.1 --port 8741
```

Abre `http://127.0.0.1:8741`. Para manter o sandbox numa localização diferente, define `ALBERTO_SANDBOX_DIR` antes de iniciar o servidor.

## 🧭 Arquitetura operacional pretendida

- **Alberto AI** — camada central de interpretação, orquestração e resposta no chat.
- **ModelRouter** — encaminha conversa, raciocínio e código para o provider/modelo configurado, com fallback.
- **MiMo** — memória e geração de aplicações; não substitui o motor LLM do chat principal.
- **Hermes** — ferramentas, browser, execução e integração MCP.
- **CrewAI** — execução de squads/equipas de agentes; não coordena Hermes e MiMo.
- **NemoClaw** — isolamento e controlos de segurança.

Fluxo do chat: frontend → `POST /api/chat` → `Alberto.chat()` → Orchestrator → ModelRouter → provider → resposta SSE. O frontend reutiliza o identificador da conversa e não apresenta respostas mock quando o backend falha.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Alberto CLI (alberto) + 3D Web UI (alberto-serve)      │
│ ┌──────────────────────────────────────────────────┐   │
│ │ Agent (run_tool_loop + interceptor fallback)    │   │
│ │ ├─ Smart Router v2 (10 intent rules)            │   │
│ │ ├─ Model Router (OpenAI-compat, no hardcoded)   │   │
│ │ ├─ Function Caller (32 tools)                   │   │
│ │ ├─ Security Whitelist (3-tier)                  │   │
│ │ ├─ Audit Log (~/.alberto/audit.log)             │   │
│ │ └─ Skill Engine (catalogs in skills/ + upstream/hermes/skills)    │   │
│ └──────────────────────────────────────────────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ NemoClaw │ │ MiMo     │ │ Hermes   │ │ CrewAI   │  │
│  │ Security │ │ Memory+  │ │ Browser+ │ │ Workflows│  │
│  │ Security │ │ Memory + │ │ Browser +│ │ Squad    │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│         37 personas · 15 workflows · 80 steps         │
└─────────────────────────────────────────────────────────┘
```

## 📋 What's Inside (v1.8.1)

### Workflow catalog · 80 documented steps · 37 personas

| Domain | Workflow | Steps | Personas |
|---|---|---|---|
| **Engineering** | engineering | 5 | pm, architect, dev, qa, devops |
| **ML** | data-ml, ml-ops | 5+5 | analyst, data_engineer, ml_engineer, mlops, sre, qa |
| **Content** | content | 5 | researcher, content, writer, editor, tech_writer |
| **Finance** | finance | 5 | finance, analyst, critic, pm, finance_recommender |
| **Growth** | growth | 6 | analyst, growth_analyst, growth, content, pm, analyst_readout |
| **Product** | product | 5 | ux_researcher, pm, ux_designer, data_analyst, tech_lead |
| **Research** | research | 5 | researcher, reviewer, analyst, writer, critic |
| **Sales** | sales | 5 | sales, pm, architect, finance, sales_closer |
| **Support** | support | 5 | support, product, dev, qa, support_closer |
| **Incident** | incident | 5 | oncall, sre, comms, pm, reviewer |
| **Hiring** | hiring 🆕 | 6 | recruiter, tech_lead, dev, pm |
| **Mentorship** | mentorship 🆕 | 6 | mentor, tech_lead, pm |
| **Sprint** | sprint-planning 🆕 | 6 | scrum_master, pm, tech_lead, dev, qa |
| **Security** | security-audit 🆕 | 6 | security, dev, qa |

### 39 Tools (function_caller.py)

| Category | Tools |
|---|---|
| File | `tool_file_read`, `tool_file_write`, `tool_file_append`, `tool_file_delete` |
| Shell | `tool_run_shell` (whitelisted), `tool_process` |
| Memory | `tool_memory_get`, `tool_memory_set`, `tool_memory_list`, `tool_memory_search` |
| Skills | `tool_skill_list`, `tool_skill_invoke` |
| Web | `tool_web_search` 🆕 (browser fallback) |
| Image | `tool_generate_image` (flux.1-dev) |
| Auto-invoke | `tool_auto_invoke` |
| Security | `tool_security_scan`, `tool_security_path_check` |
| Squad | `tool_squad_list`, `tool_squad_run` |

### 38 Hermes Tools (hermes_tools.py)

Browser (Playwright+Chromium), terminal, code_execution, file, vision, MCP, web fetch, etc — all with graceful fallback.

## 🎯 Features

| Capability | Status |
|---|---|
| **Natural chat** (PT-BR default) | ✅ Real |
| **Vision** (diffusiongemma + thinking) | ✅ Real |
| **Tool calling** (32 OpenAI-compat) | ✅ Real |
| **Function calling** (deepseek-v4) | ✅ Real |
| **Voice TTS/STT** | 🔑 Requer Magpie key |
| **Image generation** (flux.1-dev) | 🔑 Requer chave especial |
| **Browser automation** (Playwright+Chromium) | ✅ Real |
| **Web search** (browser fallback, sem API) | ✅ v1.8 |
| **Skill auto-invoke** (10 patterns) | ✅ Real |
| **Self-healing** (15 fixers) | ✅ Real |
| **Audit log** (JSON lines) | ✅ Real |
| **Security whitelist** (3-tier) | ✅ Real |
| **3D web UI** | ✅ Real |
| **Docker image** | ✅ v1.8 |
| **Mavis fallback** (when primary LLM fails) | ✅ Real |
| **CLI smoke tests** (9 subcommands) | ✅ v1.8 |
| **CI/CD pipeline** (GitHub Actions) | ✅ v1.8 |
| **Lockfile isolation** ($XDG_RUNTIME_DIR) | ✅ v1.8 |
| **Workflow consistency** (15×80×37) | ✅ v1.8.1 |

## 🔒 Security (v1.7+)

- ✅ `tool_file_write` checked by NemoClaw (blocks `/etc/`, `/root/.ssh/`, etc.)
- ✅ `tool_run_shell` blocks `rm -rf /`, fork bomb, `mkfs`, `curl | sh`, etc.
- ✅ "Comando:" interceptor validated against alberto subcommand whitelist
- ✅ All tool/shell calls logged to `~/.alberto/audit.log`

See [SECURITY-AUDIT.md](SECURITY-AUDIT.md) for full security audit (5.0/10 → 9.0/10 after v1.7 patches).

## 🧪 Tests (v1.8.1)

- **324 tests passing** in 60s
- **20% coverage geral** (52-100% em módulos críticos)
- **Zero mocks** — tudo usa serviços reais

```bash
pytest tests/test_v15_unit.py        # 121 unit tests
pytest tests/test_v15_real.py        # 67 real integration tests
pytest tests/test_v15_components.py  # 20 component integration tests
pytest tests/test_v17_security.py    # 21 security regression tests
pytest tests/test_v18_websearch.py   # 5 browser web search tests (v1.8)
pytest tests/test_v18_workflows.py   # 147 workflow consistency tests (v1.8.1)
pytest tests/test_cli_smoke.py       # 10 CLI subcommand smoke tests (v1.8)
```

## 📦 Repository Structure

```
alberto-ai/
├── alberto/                       # 53 Python files, 12K LoC
│   ├── runtime/                   # 15 modules (function_caller, smart_router, etc.)
│   ├── engines/                   # hermes_tools (38 tools), mimo (FTS5), hermes
│   ├── personas/                  # 37 personas, SquadCatalog
│   ├── server/                    # FastAPI (30+ endpoints, OpenAPI)
│   └── security_whitelist.py      # 3-tier whitelisting
├── bin/                           # alberto, alberto-serve (with watchdog)
├── upstream/                      # Real Hermes + MiMo + AIoX + NemoClaw
├── skills/                        # 775 SKILL.md files in this repository snapshot
├── personas/                      # 37 persona markdown files
├── workflows/                     # 15 squad YAML definitions
├── tests/                         # regression and component tests
├── docs/                          # V1.1 → V1.8 + SECURITY-AUDIT + GAPS-MAP
├── Dockerfile                     # v1.8: containerized deployment
└── .github/workflows/             # v1.8: CI/CD pipeline
```



## 📦 v1.8.2 — Real Upstream Integration (commit 1f374df)

**Bug fix**: I had real production code in `upstream/hermes/tools/` (87 Python files, 75218 LoC) and I rewrote them as stubs. v1.8.2 fixes this.

### What changed

Created `alberto/runtime/upstream_bridge.py` — a wrapper that:
- Loads 16 real Hermes tools from `upstream/hermes/tools/`
- Provides `real_*` functions that CALL the actual upstream code
- Replaces my stub implementations in `function_caller.py`

### Real upstream tools now used

| Alberto tool | Now uses |
|---|---|
| `tool_memory_set/get/search` | Hermes `memory_tool` + FTS5 SQLite |
| `tool_terminal` | Hermes `terminal_tool` (or subprocess fallback) |
| `tool_code_execution` | Hermes `code_execution_tool` PTC + UDS RPC |
| `tool_codesearch` | Hermes-style ripgrep + file type filters |
| `tool_lsp` | Hermes `path_security` + ripgrep for symbols |
| `tool_actor` | Hermes `tirith_security` + persistent shell |
| `tool_task` | Hermes `todo_tool` (TodoStore) |
| `tool_question` | Real stdin `input()` when interactive=True |
| `tool_plan` | LLM-based decomposition via router |
| `tool_history` | Real conversation store read |
| `tool_workflow` | Real squad execution with outputs |
| `tool_skill` | Real skill engine with list/show/search/run |

### Test totals

| Version | Tests passing |
|---|---|
| v1.7 (security) | 229 |
| v1.8 (workflows) | 324 |
| **v1.8.2 (upstream)** | **356** |

### Compat shims

Created minimal stubs in `upstream/hermes/`:
- `hermes_constants.py` — `get_hermes_home`, `apply_subprocess_home_env`
- `utils.py` — `atomic_replace`, `env_int`, `env_var_enabled`, etc
- `agent/file_safety.py`, `agent/redact.py`, `agent/skill_utils.py`
- `hermes_cli/config.py`, `hermes_cli/_subprocess_compat.py`
- `plugins/__init__.py`, `toolsets/__init__.py`

These let the upstream tools load without the full Hermes runtime.



## 📦 v1.8.3 — 25 Real Hermes Tools via model_tools.py (commit 4ff7a34)

Major upgrade: now using **REAL NousResearch hermes-agent** code via `model_tools.py`.

### What changed

- `upstream/hermes/model_tools.py` (996 LoC, real upstream) is now loaded
- `upstream/hermes/toolsets.py` (492 LoC, real) - toolset definitions
- `upstream/hermes/tools/arg_coercion.py` (real) - LLM arg coercion
- `alberto/runtime/upstream_bridge.py` rewritten with `handle_hermes_tool_call()`
- Compat shims in `upstream/hermes/{cron,plugins,toolsets,websockets}/`

### 25 production Hermes tools now real

| Tool | What |
|---|---|
| `terminal` | Real shell with NemoClaw security |
| `read_file` | Read with line numbers + safety check |
| `write_file` | Atomic write + lint check |
| `patch` | Find-and-replace edits |
| `search_files` | ripgrep content search |
| `browser_navigate/click/snapshot/type/scroll/press/console` | Real browser automation |
| `memory` | SQLite + FTS5 (with agent-loop interception) |
| `todo` | Real TodoStore |
| `skills_list/skill_view/skill_manage` | Real skills catalog |
| `clarify` | Real user question (when interactive) |
| `process`, `project_create/list/switch` | Background process + Projects |

Test totals: 324 → 379 → 396 passing

### n8n templates included (v1.8.3+)

For Discord/Telegram/Slack/Voice/Image integration without code:

```
n8n_flows/
├── README.md              ← 5-min setup guide
├── discord/ai-router.json
├── telegram/voice-assistant.json
├── slack/ai-bot.json
├── image_gen/nvidia-flux.json
└── voice/openai-tts.json
```

All templates work with **your** bot tokens. No mock, no stub. User imports the .json, adds credentials, activates. Real bot in 5 min.

### AIOX honest status

`upstream/aiox/README.md` documents the truth:
- AIOX upstream = 21 YAMLs + docs, **0 Python files**
- `@aiox/cli` does NOT exist on npm
- Alberto uses 15 own workflows + 25 Hermes tools instead
- Future options: DeerFlow, CrewAI, LangGraph, Agno

## 🗺️ Roadmap

- **v1.7** ✅ Done: NemoClaw on all writes, shell whitelist, audit log
- **v1.8** ✅ Done: CI/CD, OpenAPI, Docker, lockfile isolation, CLI tests, web search
- **v1.8.1** ✅ Done: 14 new personas, 4 new workflows, 6 workflow fixes, 147 tests
- **v2.0** ⏳ Next: Real image gen (requires NVIDIA Enterprise), Hermes voice
- **v3.0** ⏳ Future: Multi-tenant, cloud-native

## 📄 License

Apache 2.0

## 🔗 Documentation

- [SECURITY-AUDIT.md](SECURITY-AUDIT.md) — Security audit (5.0 → 9.0 after v1.7)
- [GAPS-MAP.md](GAPS-MAP.md) — 71 gaps mapped (resolved + remaining)
- [4-REAL-SCENARIOS.md](4-REAL-SCENARIOS.md) — 4 practical usage scenarios
- [AUDIT-V1.5-COMPLETE.md](AUDIT-V1.5-COMPLETE.md) — Full system audit
- [CHANGELOG-V1.8.md](CHANGELOG-V1.8.md) — v1.8 changes (8 gaps closed)

## Credits

Built by [@GrupoANDevelopment-m](https://github.com/GrupoANDevelopment-m) using Mavis AI agent.


## Local installation and readiness

See [INSTALL-LOCAL.md](INSTALL-LOCAL.md) for the supported installation path, NVIDIA configuration, persistent sandbox location, and the read-only diagnostic that counts the local and Hermes skill catalogs. The repository snapshot currently contains 775 local skill definitions plus 100 Hermes upstream skill definitions; the runtime diagnostic reports the actually discoverable count on the installed machine.
