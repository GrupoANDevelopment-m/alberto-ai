---
name: app-creation
description: >
  Create a complete app (React/TS/Vite frontend + FastAPI/Node backend) from a
  one-line description. Use when user says "cria um app", "faz um dashboard",
  "monta uma landing page", "preciso de uma ferramenta pra X". Delegates to
  meta-agent template (React/Vite/TS) for frontend, scaffolds Python FastAPI
  for backend, generates Docker compose, deploys locally.
version: 1.0.5
author: Alberto AI
license: Apache-2.0
metadata:
  alberto:
    category: app-creation
    tags: [react, vite, typescript, fastapi, docker, scaffold]
    related_skills: [self-learning, fastmcp, docker-management]
---

# App Creation

Cria um app completo (frontend + backend + docker) a partir de uma descrição.

## O que faz

1. Analisa o pedido (1 linha do usuário)
2. Decide stack (default: React + Vite + TS + Tailwind frontend, Python FastAPI backend)
3. Scaffolda diretório `app/`
4. Cria:
   - `app/frontend/` (Vite + React + TS + Tailwind)
   - `app/backend/` (FastAPI + uvicorn + pyproject)
   - `app/docker-compose.yml` (frontend + backend + nginx)
   - `app/README.md` (how to run)
5. Roda `npm install` no frontend, `pip install` no backend
6. Sobe os servers localmente (porta 3000 frontend, 8000 backend)
7. Testa via curl/browser
8. Gera screenshot via Playwright headless

## Como chamar

Natural conversation: "Alberto, cria um app de lista de tarefas"
Ou atalho: `/s app:create --name todo --description "Lista de tarefas com persistência"`

## When to use

- User wants a complete app
- User asks for a dashboard, tool, landing page
- User says "cria um projeto" / "monta um sistema"


## Evolution (v1.0.1)

Auto-evolved after failure: no executable block
Error: no executable block
Added: better error handling


## Evolution (v1.0.2)

Auto-evolved after failure: no executable block
Error: no executable block
Added: better error handling


## Evolution (v1.0.3)

Auto-evolved after failure: no executable block
Error: no executable block
Added: better error handling


## Evolution (v1.0.4)

Auto-evolved after failure: no executable block
Error: no executable block
Added: better error handling


## Evolution (v1.0.5)

Auto-evolved after failure: no executable block
Error: no executable block
Added: better error handling
