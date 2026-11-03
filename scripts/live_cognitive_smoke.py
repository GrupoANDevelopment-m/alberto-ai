"""Real-provider cognitive smoke suite for Alberto AI."""
import json
import os
from pathlib import Path

from alberto import Alberto
from alberto.sandbox import LocalSandbox


def main() -> None:
    primary = os.environ["NVIDIA_API_KEY"]
    fallback = os.environ["NVIDIA_API_KEY_FALLBACK"]
    sandbox = LocalSandbox()
    config_path = sandbox.home() / ".mimo" / "model_config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "tasks": {
            "chat": {
                "provider": "nvidia",
                "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "credential_env": "NVIDIA_API_KEY",
                "options": {"chat_template_kwargs": {"thinking": True}, "reasoning_budget": 16384},
            },
            "reasoning": {
                "provider": "nvidia",
                "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "credential_env": "NVIDIA_API_KEY",
                "options": {"chat_template_kwargs": {"thinking": True}, "reasoning_budget": 16384},
            },
            "code": {
                "provider": "nvidia",
                "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "credential_env": "NVIDIA_API_KEY",
                "options": {"chat_template_kwargs": {"thinking": True}, "reasoning_budget": 16384},
            },
        },
        "fallback_chain": [{
            "provider": "nvidia",
            "model_id": "nvidia/nemotron-3.5-lightning-30b-a3b",
            "base_url": "https://integrate.api.nvidia.com/v1",
            "credential_env": "NVIDIA_API_KEY_FALLBACK",
            "options": {},
        }],
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    cases = [
        ("conversation", "Responde em português. Explica em duas frases a diferença entre memória de curto prazo e memória persistente num agente."),
        ("reasoning", "Um sistema recebe 120 pedidos por minuto e processa 90. Se a taxa se mantiver, quantos pedidos ficam por processar em 8 minutos? Explica o cálculo."),
        ("context", "Considera esta sequência: A depende de B; B depende de C. Qual é a ordem segura de execução e porquê?"),
        ("instruction", "Resume em três pontos os riscos de um agente autónomo executar comandos sem validação."),
    ]
    agent = Alberto(sandbox=sandbox)
    try:
        for label, prompt in cases:
            result = agent.chat(prompt)
            response = (result.get("response") or "").strip()
            strategy = result.get("strategy") or {}
            if not response or response.startswith("[sem modelo configurado") or response.startswith("[error"):
                raise AssertionError(f"{label}: resposta vazia/erro: {response[:300]}")
            if strategy.get("task_routing") != "chat":
                raise AssertionError(f"{label}: routing inesperado: {strategy}")
            print(json.dumps({
                "case": label,
                "routing": strategy.get("task_routing"),
                "engine": strategy.get("engine"),
                "response_chars": len(response),
                "response": response[:1200],
            }, ensure_ascii=False))
        print("COGNITIVE_SUITE=PASS")
    finally:
        agent.shutdown()


if __name__ == "__main__":
    main()
