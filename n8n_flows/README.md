# 📦 n8n Flows Ready for Alberto AI

Alberto AI não vem com bots Discord/Telegram/Slack prontos — porque você precisa das suas próprias credenciais de bot (token) e nós não vamos hardcodar nada.

**Solução**: Workflows n8n prontos que você importa, cola seu token, e em 5 minutos está rodando.

Todos os templates abaixo vêm do repo [enescingoz/awesome-n8n-templates](https://github.com/enescingoz/awesome-n8n-templates) (25.7k stars, 280+ templates) ou [wassupjay/n8n-free-templates](https://github.com/wassupjay/n8n-free-templates) (200+ templates).

## 🔧 Setup (5 minutos)

```bash
# 1. Instalar n8n (auto-hospedado)
npm install -g n8n
n8n start
# Abre http://localhost:5678

# 2. Importar template
# Workflows → Import from File → escolhe o .json abaixo

# 3. Adicionar credenciais
# Cada node com ⚙️ vermelho → clicar → "Create New Credential"
# Cola seu token do Discord/Telegram/etc

# 4. Ativar
# Toggle "Active" no canto superior direito
```

## 📋 Templates Recomendados

### 💬 Discord
| Template | O que faz | Link |
|---|---|---|
| Discord AI-powered bot | Categoriza mensagens, roteia para departamentos | `discord/ai-router.json` |
| YouTube share on Discord | Posta vídeos novos com AI summary | `discord/youtube-share.json` |

### 📱 Telegram
| Template | O que faz | Link |
|---|---|---|
| Telegram voice+text bot | Whisper STT + GPT-4 reply | `telegram/voice-assistant.json` |
| Agentic Telegram AI bot | LangChain + memory + tools | `telegram/agentic-bot.json` |
| Telegram translate audio (55 langs) | Traduz mensagens de voz | `telegram/translate-audio.json` |

### 💼 Slack
| Template | O que faz | Link |
|---|---|---|
| Slack AI bot | Q&A bot com RAG | `slack/ai-bot.json` |
| Venafi Cloud Slack Cert Bot | Cert management via Slack | `slack/cert-bot.json` |

### 🎤 Voice (TTS/STT)
| Template | O que faz | Link |
|---|---|---|
| Telegram voice assistant | Whisper STT + GPT-4 + TTS | `voice/whisper-gpt.json` |

### 🎨 Image Gen
Alberto já tem `tool_generate_image` via NVIDIA. Para setup n8n:
| Template | O que faz | Link |
|---|---|---|
| Telegram image bot | Replicate/Stability AI image gen | `image_gen/replicate-bot.json` |

## 🔌 Como Conectar ao Alberto

Depois de ativar qualquer flow acima, pegue a **webhook URL** do nó "Webhook" e use o Alberto assim:

```python
# No seu workflow/script
import requests

WEBHOOK_URL = "http://localhost:5678/webhook/discord-bot"

requests.post(WEBHOOK_URL, json={
    "message": "Olá!",
    "user_id": "123",
    "channel": "general"
})
```

Ou, em qualquer workflow do Alberto, adicione um step "HTTP Request" apontando para a URL do n8n.

## 📚 Mais templates

- 280+ em https://github.com/enescingoz/awesome-n8n-templates
- 200+ em https://github.com/wassupjay/n8n-free-templates

Pesquise por "discord", "telegram", "slack" — vai encontrar dezenas prontos.

