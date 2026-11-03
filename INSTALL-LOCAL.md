# Alberto AI — instalação local e preparação para execução real

Este guia prepara o repositório para execução local. Não executa testes cognitivos, não simula respostas e não inclui chaves API.

## 1. Requisitos

- Linux ou macOS (Windows: usar WSL2)
- Python 3.11 ou superior
- Git
- Acesso à Internet para instalar dependências e contactar o provider
- Chaves NVIDIA válidas para o modelo principal e fallback

O repositório contém os componentes de runtime e os catálogos de skills. Os ficheiros `SKILL.md` são instruções/catalogação; não significam que cada dependência opcional de cada skill esteja instalada.

## 2. Clonar e instalar num ambiente isolado

```bash
git clone https://github.com/GrupoANDevelopment-m/alberto-ai.git
cd alberto-ai
bash install_deps.sh
source .venv/bin/activate
```

O instalador cria `.venv/` e instala o projeto em modo editável. Não usa `sudo`, não altera o Python do sistema e não usa `--break-system-packages` nem `--no-deps`.

Se já tens o repositório clonado, entra na pasta e executa apenas:

```bash
bash install_deps.sh
```

## 3. Verificar a instalação e as skills

```bash
python scripts/alberto_doctor.py
```

O diagnóstico mostra:
- diretório do repositório e Python ativo;
- quantidade de ficheiros `SKILL.md` em `skills/`;
- quantidade de ficheiros `SKILL.md` em `upstream/hermes/skills/`;
- quantidade que o runtime Alberto consegue descobrir;
- diretório de sandbox e localização do `model_config.json`;
- tarefas de modelo configuradas e presença das variáveis de credencial no processo.

No snapshot do repositório usado para preparar este guia foram encontrados **775 ficheiros `SKILL.md` em `skills/` e 72 em `upstream/hermes/skills/`**. O diagnóstico local é a autoridade para a instalação real; o total descoberto pelo runtime pode ser menor por deduplicação de nomes.

As skills estão no próprio clone, em `skills/` e `upstream/hermes/skills/`. O Alberto procura esses diretórios relativamente à raiz do repositório; não é necessário copiar as skills para uma pasta global. A instalação editável mantém os caminhos corretos.

## 4. Sandbox e configuração persistente

Por omissão, o sandbox local usa:

```
~/.local/share/alberto-ai/sandbox/
```

O ficheiro de configuração dos modelos fica em:

```
~/.local/share/alberto-ai/sandbox/home/.mimo/model_config.json
```

Para manter a localização anterior já usada no teu ambiente (`/workspace/alberto-sandbox/home/.mimo/model_config.json`), define a raiz do sandbox antes de iniciar o Alberto:

```bash
export ALBERTO_SANDBOX_DIR="/workspace/alberto-sandbox"
```

Também podes escolher outra raiz, por exemplo `$HOME/alberto-sandbox`. A configuração fica sempre em `$ALBERTO_SANDBOX_DIR/home/.mimo/model_config.json`.

## 5. Configurar NVIDIA e fallback

Define as chaves apenas no terminal, nunca num ficheiro versionado:

```bash
export NVIDIA_API_KEY="A_TUA_CHAVE_NVIDIA_PRINCIPAL"
export NVIDIA_API_KEY_FALLBACK="A_TUA_CHAVE_NVIDIA_FALLBACK"
python scripts/configure_nvidia.py
```

O script configura:
- `chat`, `reasoning` e `code` → `nvidia/nemotron-3-ultra-550b-a55b`;
- fallback → `nvidia/nemotron-3.5-lightning-30b-a3b`;
- endpoint OpenAI-compatible NVIDIA;
- variáveis de ambiente para as credenciais, sem gravar os respetivos valores no JSON.

As variáveis `export` só permanecem disponíveis nessa sessão de terminal. Para arranques posteriores, configura-as no gestor de ambiente/segredos do teu sistema; não as coloques no Git.

## 6. Verificar e iniciar

```bash
python scripts/alberto_doctor.py
alberto model list
alberto-serve --host 127.0.0.1 --port 8741
```

Abre `http://127.0.0.1:8741`. Mantém o terminal do servidor aberto. Para confirmar o estado do backend, consulta `http://127.0.0.1:8741/api/status`.

## 7. Fluxo esperado do chat

```
Browser / frontend
  → POST /api/chat (SSE)
  → FastAPI chat endpoint
  → Alberto.chat()
  → Orchestrator
  → ModelRouter (chat / reasoning / code)
  → NVIDIA primary, com fallback configurado
  → resposta SSE para a interface
```

O frontend mantém o `conversation_id` recebido pelo evento SSE `done` e reutiliza-o nas mensagens seguintes. Uma falha HTTP/SSE é apresentada como falha real; a interface não deve substituir uma falha por uma resposta de demonstração.

**Papéis dos componentes:** Alberto coordena o fluxo; ModelRouter seleciona o provider/modelo; MiMo mantém as funções próprias de memória e geração de aplicações; Hermes fornece ferramentas e navegação; CrewAI executa squads/equipas; NemoClaw fornece a camada de segurança e sandbox. CrewAI não coordena Hermes e MiMo.

## 8. Limites importantes

- O diagnóstico valida caminhos, catálogo e configuração local; não prova que todas as skills tenham todas as dependências externas opcionais.
- O arranque do servidor não prova que as chaves NVIDIA sejam válidas. A chamada real ao modelo só fica confirmada quando o chat recebe uma resposta do provider.
- O frontend e o endpoint usam SSE; confirma a resposta em `/api/chat` e os logs do servidor se o provider falhar.
- Não exponhas o servidor em interfaces públicas sem autenticação, TLS e regras de firewall adequadas.
