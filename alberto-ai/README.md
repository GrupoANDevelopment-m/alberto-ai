# Alberto AI

**Alberto** — agente de IA brasileiro que combina 4 projetos open-source
(NVIDIA NemoClaw + Xiaomi MiMo + Nous Research Hermes + AIoX) de forma
**aditiva** (zero regressão). Multi-engine, multi-model (qualquer provedor
OpenAI-compat), sistema de atalhos, opt-in squads/personas, frontend 3D, conversa
natural, testes reais com LLM real, e skill engine de 178 skills.

## Quick start

```bash
unzip Alberto-AI.zip
cd alberto-ai
pip install -e ".[dev]"

# Configure seu modelo (qualquer provedor OpenAI-compat)
alberto model set chat nvidia z-ai/glm-5.2 https://integrate.api.nvidia.com/v1 NVIDIA_API_KEY
alberto model set code nvidia z-ai/glm-5.2 https://integrate.api.nvidia.com/v1 NVIDIA_API_KEY

# Sobe o server com frontend 3D
alberto serve --port 8741
# → http://127.0.0.1:8741

# Conversa natural
alberto chat "Oi Alberto, me ajuda a implementar um validador de CPF"

# Outras formas
alberto ask "implementa uma função que conta palavras únicas"
alberto memory set user.nome Carlos
alberto skill list          # 178 skills
alberto app create todo "Lista de tarefas"  # cria app completo
alberto mcp add echo python3 /path/to/mcp-server.py
alberto loop --tick 60     # roda 24/7
```

## Comandos

| Comando | O que faz |
|---|---|
| `alberto chat "<msg>"` | Conversa natural com LLM |
| `alberto ask "<task>"` | Despacha via orchestrator (decide solo/squad) |
| `alberto memory {set,get,search,list}` | Memória FTS5 persistente |
| `alberto model {list,set,test}` | Config de modelos por task |
| `alberto squad {list,activate,run,hibernate}` | 12 squads Alberto + 1 AIOX |
| `alberto s {list,add,show,use}` | Atalhos JSON-backed |
| `alberto skill {list,show,run,run-all,commands}` | 178 skills com código real |
| `alberto mcp {list,add,connect,call,disconnect}` | MCP servers |
| `alberto install {list,install,create-skill,...}` | Extensões/skills dinâmicas |
| `alberto app create <name> <desc>` | Cria app React+Vite+FastAPI+Docker |
| `alberto loop [--tick 60] [--max N]` | 24/7 autonomy loop |
| `alberto serve [--port 8741]` | Sobe HTTP server + frontend |
| `alberto tool <name> '<args_json>'` | Invoca tool direto |

## Arquitetura (6+1 layers, aditiva)

```
NemoClaw (24 presets, blueprint, shields)
  + MiMo (memory FTS5, sessions, compose, max_mode, subagent, snapshot)
    + Hermes (78 tools: browser, code_exec, terminal, vision, voice, channels, github, security)
      + AIoX (1 squad upstream + 23 personas)
        + ModelRouter (OpenAI-compat, NO defaults, NO hardcoded)
          + ShortcutStore (JSON-backed, {{args}} substitution)
            + Orchestrator (decide: solo / squad / speculative)
```

## Testes

```bash
pytest tests/                   # 101 testes offline
python3 -m alberto.cli skill list    # 178 skills
python3 -m alberto.cli app create demo "Demo app"  # cria app real
```

## License

Apache 2.0. Intern use only.

## Créditos

- NVIDIA NemoClaw (Apache 2.0)
- Xiaomi MiMo (USE_RESTRICTIONS.md — internal use OK)
- Nous Research Hermes (MIT)
- AIoX (varies)
