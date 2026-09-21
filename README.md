# Alberto AI

**Integrated AI agent stack** combining 4 open-source projects additively (zero regression):

- 🛡️ **NVIDIA NemoClaw** — sandbox + secret scanner (36 patterns) + 18 protected paths + env leak detector
- ⚡ **Xiaomi MiMo** — FTS5 memory + 22 tools (bash/read/write/edit/multiedit/glob/grep/webfetch/websearch/apply_patch/change_directory/memory/task/plan/question/skill/workflow/actor/lsp/mcp_exa/codesearch/history)
- 🧠 **Nous Research Hermes** — 6 working tools (terminal, file, code_execution, memory, cron, browser fallback)
- 🔮 **AIoX** — 3 workflow YAMLs

## Features

- **Multi-engine, multi-model** — any OpenAI-compatible provider (NVIDIA, OpenAI, Anthropic, etc) via `POST /v1/chat/completions`
- **Smart router** — 10 intent-based routing rules + cost tracking
- **Function calling** — 32 tools with native `tool_calls` JSON support
- **3-tier fallback** — deepseek → gemma4 → kimi-k3
- **Vision** — diffusiongemma-26b-a4b-it with enable_thinking (PT-BR support)
- **Self-healing** — 9 fixers (disk/import/yaml/db/port/memory/lock/tls/rate_limit/5xx/permission)
- **Hermes+NemoClaw bridge** — safe machine access (security from NemoClaw, execution from Hermes)
- **Skill auto-invocation** — 10 keyword patterns (agent-reach, deploy-to-vercel, browser-skill-click, etc)
- **3D frontend** — Three.js + FastAPI + 30+ HTTP endpoints
- **Conversational** — natural chat in PT-BR (not command-dispatch)
- **Memory** — FTS5-backed persistent conversations

## Install

```bash
unzip Alberto-AI.zip
cd alberto-ai
pip install -e ".[dev]"

# Setup your model
alberto model set chat nvidia google/diffusiongemma-26b-a4b-it https://integrate.api.nvidia.com/v1 NVIDIA_API_KEY
alberto model set code nvidia google/diffusiongemma-26b-a4b-it https://integrate.api.nvidia.com/v1 NVIDIA_API_KEY

# Start server
alberto-serve --port 8741
```

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Alberto (Python)                                            │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Agent (tool_calls loop + interceptor fallback)        │  │
│  │ ├─ Smart Router v2 (10 intent rules)                  │  │
│  │ ├─ Model Router (OpenAI-compat, any provider)         │  │
│  │ ├─ Function Caller (32 tools)                         │  │
│  │ ├─ Self-Healing (9 fixers)                             │  │
│  │ ├─ Skill Engine (779 skills + 10 auto-invoke)         │  │
│  │ └─ Meta Controller (task routing)                     │  │
│  └────────────────────────────────────────────────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐         │
│  │ NemoClaw │ │ MiMo     │ │ Hermes   │ │ AIoX     │         │
│  │ security │ │ memory   │ │ exec     │ │ workflows│         │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘         │
└──────────────────────────────────────────────────────────────┘
```

## Versions

- **v1.0**: Base architecture (16 modules)
- **v1.1**: Real upstream integration (8344 files, 86 tools, 18 skills)
- **v1.2**: Function calling bridge (32 tools)
- **v1.3**: 3-tier fallback (deepseek → gemma4 → kimi)
- **v1.4**: Hermes + NemoClaw + AIoX integration (36 secret patterns, 18 protected paths, env leak detector)
- **v1.5**: Vision models (diffusiongemma PT-BR), skill auto-invocation, vision CLI

## License

Apache 2.0

## Credits

- NVIDIA NemoClaw — https://github.com/nvidia/nemoclaw
- Xiaomi MiMo — https://github.com/Xiaomi/mimo
- Nous Research Hermes — https://github.com/NousResearch/hermes
- AIoX — https://github.com/aiox/aiox
