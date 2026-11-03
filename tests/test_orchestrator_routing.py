from alberto.orchestrator import Orchestrator


def test_ordinary_conversation_routes_to_chat():
    strategy = Orchestrator().decide("Olá, como estás?")

    assert strategy.mode == "solo"
    assert strategy.engine == "mimo"
    assert strategy.task_routing == "chat"


def test_explicit_software_work_routes_to_code():
    orchestrator = Orchestrator()
    prompts = [
        "Implementa uma função Python para ordenar uma lista.",
        "Corrige este bug no código.",
        "Refatora este módulo.",
        "Run tests for this package.",
    ]

    for prompt in prompts:
        assert orchestrator.decide(prompt).task_routing == "code"


def test_comparison_routes_to_reasoning():
    strategy = Orchestrator().decide("Compare as vantagens e desvantagens destas opções.")

    assert strategy.mode == "speculative"
    assert strategy.task_routing == "reasoning"


def test_hermes_command_keeps_chat_task():
    strategy = Orchestrator().decide("Abre o navegador.", hermes_command="browser")

    assert strategy.engine == "hermes"
    assert strategy.task_routing == "chat"


def test_custom_default_task_is_preserved():
    strategy = Orchestrator(default_task="reasoning").decide("Olá.")

    assert strategy.task_routing == "reasoning"
