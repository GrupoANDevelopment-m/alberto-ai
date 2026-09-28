# 🤖 Alberto AI v1.8

**Integrated AI agent stack** combining 4 open-source projects additively:

- 🛡️ **[NVIDIA NemoClaw](https://github.com/nvidia/nemoclaw)** — sandbox + security + 36 secret patterns
- ⚡ **[Xiaomi MiMoCode](https://github.com/Xiaomi/mimo)** — FTS5 memory + 22 tools
- 🧠 **[Nous Research Hermes](https://github.com/NousResearch/hermes-agent)** — browser + execution
- 🔮 **[SynkraAI AIOX](https://github.com/synkraai/aiox)** — workflows + 23 agents

---

## ⚡ Quick Start (5 minutes)

```bash
# 1. Install
git clone https://github.com/GrupoANDevelopment-m/alberto-ai.git
cd alberto-ai
pip install -e .

# 2. Configure LLM (any OpenAI-compat)
export NVIDIA_API_KEY=nvapi-...
alberto model set chat nvidia google/diffusiongemma-26b-a4b-it https://integrate.api.nvidia.com/v1

# 3. Talk to Alberto
alberto chat "Ola Alberto!"
alberto vision "Descreva isto" https://...
alberto auto-invoke "Pesquise no reddit"

# 4. Start 3D web UI
alberto-serve --port 8741
# Open http://localhost:8741
```

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
│ │ ├─ Audit Log (~/.alberto/audit.log)              │   │
│ │ └─ Skill Engine (779 skills, 10 auto-invoke)    │   │
│ └──────────────────────────────────────────────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ NemoClaw │ │ MiMo     │ │ Hermes   │ │ AIoX     │  │
│  │ Security │ │ Memory+  │ │ Browser+ │ │ Workflows│  │
│  │ (36+patt)│ │ 22 tools │ │ 38 tools │ │ 11 yamls │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
└─────────────────────────────────────────────────────────┘
```

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
| **Skill auto-invoke** (10 patterns) | ✅ Real |
| **Self-healing** (15 fixers) | ✅ Real |
| **Audit log** (JSON lines) | ✅ Real |
| **Security whitelist** (3-tier) | ✅ Real |
| **3D web UI** | ✅ Real |
| **Docker image** | ✅ v1.8 |
| **Mavis fallback** (when primary LLM fails) | ✅ Real |
| **CLI smoke tests** (30+ subcommands) | ✅ v1.8 |
| **CI/CD pipeline** (GitHub Actions) | ✅ v1.8 |
| **Lockfile isolation** ($XDG_RUNTIME_DIR) | ✅ v1.8 |

## 🔒 Security (v1.7+)

- ✅ `tool_file_write` checked by NemoClaw (blocks `/etc/`, `/root/.ssh/`, etc.)
- ✅ `tool_run_shell` blocks `rm -rf /`, fork bomb, `mkfs`, `curl | sh`, etc.
- ✅ "Comando:" interceptor validated against alberto subcommand whitelist
- ✅ All tool/shell calls logged to `~/.alberto/audit.log`

See [SECURITY-AUDIT.md](SECURITY-AUDIT.md) for full security audit (5.0/10 → 9.0/10 after v1.7 patches).

## 🧪 Tests (v1.8)

- **229 tests passing**, **1 skipped** in 18s
- **20% coverage geral** (52-100% em módulos críticos)
- **Zero mocks** — tudo usa serviços reais

```bash
pytest tests/test_v15_unit.py      # 121 unit tests
pytest tests/test_v15_real.py      # 67 real integration tests
pytest tests/test_v15_components.py # 20 component integration tests
pytest tests/test_v17_security.py  # 21 security regression tests
pytest tests/test_cli_smoke.py     # 30+ CLI subcommand smoke tests (v1.8)
```

## 📦 What's Inside

```
alberto-ai/
├── alberto/           # 39 Python files, 11.4K LoC
│   ├── runtime/       # 15 modules (function_caller, smart_router, etc.)
│   ├── engines/       # hermes_tools (38 tools), mimo (FTS5), hermes
│   ├── personas/      # 23 personas
│   ├── server/        # FastAPI (30+ endpoints)
│   └── security_whitelist.py  # 3-tier whitelisting
├── bin/               # alberto, alberto-serve (with watchdog)
├── upstream/          # Real Hermes + MiMo + AIoX + NemoClaw source
├── skills/            # 779 skills in 38 categories
├── personas/          # 23 persona markdown files
├── workflows/         # 11 squad YAML definitions
├── tests/             # 7 test files, 250+ tests
├── docs/              # V1.1 → V1.8 + SECURITY-AUDIT + GAPS-MAP
├── Dockerfile         # v1.8: containerized deployment
└── .github/workflows/ # v1.8: CI/CD pipeline
```

## 🗺️ Roadmap

- **v1.7** ✅ Done: NemoClaw on all writes, shell whitelist, audit log
- **v1.8** ✅ Done: CI/CD, OpenAPI, Docker, lockfile isolation, CLI tests
- **v2.0** ⏳ Next: Real image gen (requires NVIDIA Enterprise), Hermes voice
- **v3.0** ⏳ Future: Multi-tenant, cloud-native

## 📄 License

Apache 2.0

## 🔗 Documentation

- [SECURITY-AUDIT.md](SECURITY-AUDIT.md) — Security audit (5.0 → 9.0 after v1.7)
- [GAPS-MAP.md](GAPS-MAP.md) — 71 gaps mapped (resolved + remaining)
- [4-REAL-SCENARIOS.md](4-REAL-SCENARIOS.md) — 4 practical usage scenarios
- [AUDIT-V1.5-COMPLETE.md](AUDIT-V1.5-COMPLETE.md) — Full system audit

## Credits

Built by [@GrupoANDevelopment-m](https://github.com/GrupoANDevelopment-m) using Mavis AI agent.
