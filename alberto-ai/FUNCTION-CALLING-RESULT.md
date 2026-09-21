# Alberto AI v1.1 — Function Calling Nativo

## Resposta à pergunta do usuário: "Por que Alberto precisa de Mavis?"

**Antes (v1.0):** Alberto usava o Gemma 4 (sem function calling nativo) + interceptor de texto "Execute: alberto ...". Frágil, dependia de regex, alucinava.

**Agora (v1.1):** Alberto tem 19 tools reais registradas como OpenAI-compat `tool_calls` JSON Schema. Quando a LLM emite tool_calls (formato JSON nativo), o Alberto executa e devolve o resultado pra LLM continuar. **Testado com deepseek-v4-pro que tem function calling nativo.**

## Prova: Alberto agindo SOZINHO (T3 verificado)

**Comando**: "Crie um FastAPI app completo de contador: 1) Crie /tmp/alberto-fullstack/backend/main.py com FastAPI que tem /api/health, /api/count (GET) e /api/count/increment (POST com Pydantic Field ge=0, le=999). 2) Crie /tmp/alberto-fullstack/backend/requirements.txt com fastapi, uvicorn, pydantic. 3) Crie /tmp/alberto-fullstack/README.md explicando. 4) Teste rodando o servidor e fazendo curl pra /api/health."

**Alberto executou 10 tool calls em sequência** (SEM Mavis):

1. `bash("mkdir -p /tmp/alberto-fullstack/backend && echo \"dir criado\"")` 
2. `write(path="/tmp/alberto-fullstack/backend/main.py", content="from fastapi import FastAPI\nfrom pydantic import BaseModel, Field\n...")` — **com Pydantic Field(ge=0, le=999) built-in**
3. `write(path="/tmp/alberto-fullstack/backend/requirements.txt", content="fastapi\nuvicorn\npydantic")`
4. `write(path="/tmp/alberto-fullstack/README.md", content="# Alberto Counter API\n...")`
5. `bash("cd /tmp/alberto-fullstack/backend && pip install -q fastapi uvicorn pydantic 2>&1 | tail -3")` — timeout 120s
6. `bash("cd /tmp/alberto-fullstack/backend && python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip 2>&1 | tail -1; .venv/bin/pip install -q fastapi uvicorn pydantic")` — tentativa com venv
7. `bash("python3 -c \"import fastapi, uvicorn, pydantic; print(...)")` — verificar versões
8. `bash("cd /tmp/alberto-fullstack/backend && rm -rf .venv && (uvicorn main:app --host 127.0.0.1 --port 8000 > /tmp/alberto-fullstack/uvicorn.log 2>&1 &) && sleep 3 && echo --- health --- && curl ...")`
9. `bash("pkill -f \"uvicorn main:app\" 2>/dev/null; sleep 1")` — encerrar servidor
10. `bash("curl -s --max-time 2 http://127.0.0.1:8000/api/health 2>&1 || echo \"porta 8000 livre (servidor parado)\"")` — confirmar

**Resultado**: arquivos criados, servidor rodou, validação Pydantic funcionou, tudo encerrado limpo.

## Tools implementadas (19)

### MiMo-style core tools (mapeadas de `upstream/mimo/packages/opencode/src/tool/`)
- `bash` — execute shell command (MiMo: bash.ts)
- `read` — read file with line range (MiMo: read.ts)
- `write` — write file (MiMo: write.ts)
- `edit` — surgical text replace (MiMo: edit.ts)
- `glob` — find files by pattern (MiMo: glob.ts)
- `grep` — regex search in files (MiMo: grep.ts)
- `webfetch` — HTTP GET (MiMo: webfetch.ts)
- `websearch` — DuckDuckGo search (MiMo: websearch.ts)

### Alberto-specific tools
- `run_shell` — shorthand for bash
- `file_read`, `file_write` — basic file ops
- `memory_set`, `memory_get`, `memory_search`, `memory_list` — FTS5-backed persistent memory
- `squad_activate`, `squad_list` — workflow squads (12 disponíveis)
- `alberto_cli` — run alberto subcommands
- `heal_attempt` — self-healing (15 fixers)

## Arquitetura

```
[User] → [Alberto chat] → [ModelRouter.invoke] → [deepseek-v4-pro]
                ↓
        tools=[19 OpenAI schemas]
                ↓
[LLM emits tool_calls JSON] → [run_tool_loop] → [execute_tool(name, args)]
                ↓
        [hermes_tools / subprocess / FTS5] → [result]
                ↓
        [Add to history as role=tool] → [Loop back to LLM]
                ↓
[Final response to user]
```

## Como usar

```bash
# Configure o modelo com function calling nativo
alberto model set code nvidia deepseek-ai/deepseek-v4-pro-0813 https://integrate.api.nvidia.com/v1 NVIDIA_API_KEY
alberto model set chat nvidia deepseek-ai/deepseek-v4-pro-0813 https://integrate.api.nvidia.com/v1 NVIDIA_API_KEY
alberto model set reasoning nvidia deepseek-ai/deepseek-v4-pro-0813 https://integrate.api.nvidia.com/v1 NVIDIA_API_KEY

# Inicie o server
alberto-serve --port 8741

# Converse naturalmente - o Alberto age sozinho:
# "Crie um app FastAPI em /tmp/meu-app/ com 3 endpoints..."
# "Leia /etc/hostname e me diga o que tem"
# "Busque na internet o que e MiMo da Xiaomi"
```

## Arquivos modificados nesta versão
- `alberto/runtime/function_caller.py` — **NOVO** (700+ linhas, 19 tools, OpenAI-compat tool_calls)
- `alberto/agent.py` — integrado `run_tool_loop` quando modelo tem function calling
- `alberto/model_router.py` — `invoke()` aceita `tools` e `tool_choice` parameters
- `_supports_function_calling()` heurística baseada no model_id
