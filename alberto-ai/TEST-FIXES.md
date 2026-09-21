# Alberto AI — Correções aplicadas (v1.0.1)

## Problemas resolvidos nesta versão

### 1. Alucinações sobre catálogo
- **Antes**: Alberto dizia "vou ativar Hermes" / "vou executar" mas nada acontecia
- **Agora**: System prompt dinâmico injetado com catálogo REAL (779 skills, 86 tools, 12 squads, 23 personas)
- LLM sabe exatamente o que tem antes de falar

### 2. Falta de auto-execução
- **Antes**: LLM respondia com texto, usuário tinha que copiar/colar
- **Agora**: Interceptor captura "Execute: alberto ..." e roda automaticamente
- Mostra output real no chat

### 3. Server crashes
- **Antes**: yaml/fastapi sumiam, server crashava, sem auto-recovery
- **Agora**: Self-healing com 15 fixers (yaml_missing, import_error, server_crash, port_in_use, etc.)
- Watchdog respawna server, preflight instala deps com mirror fallback

### 4. LLM não consulta memória
- **Antes**: Alberto esquecia o que usuário disse
- **Agora**: recall_memory() puxa contexto relevante em cada turno
- Verificado: Alberto lembrou "João trabalha com Python e Rust"

### 5. Subprocess sem PATH
- **Antes**: `alberto: not found` no Execute
- **Agora**: agent.py força PYTHONPATH e fallback pra `python3 -m alberto.cli`

## Arquivos modificados
- `alberto/conversation.py` — system prompt dinâmico com catálogo real
- `alberto/agent.py` — interceptor de Comando/Execute + memory recall
- `alberto/runtime/self_healing.py` — 15 fixers (era 6)
- `bin/alberto-serve` — wrapper com preflight + watchdog
- `setup.py` — entry point alberto-serve

## Como instalar
```bash
unzip Alberto-AI.zip && cd alberto-ai
pip install -e ".[dev]"
# Use alberto-serve para auto-recovery
alberto-serve --port 8741
```
