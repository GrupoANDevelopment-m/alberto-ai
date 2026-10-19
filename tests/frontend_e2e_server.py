"""Deterministic HTTP backend used only by browser-level frontend contract tests."""
from __future__ import annotations

import argparse
from types import SimpleNamespace

import uvicorn

from alberto.server.app import create_app


class Memory:
    def __init__(self):
        self.items = {}

    def list(self):
        return [{"key": key, "value": value, "tags": tags} for key, (value, tags) in self.items.items()]

    def set(self, key, value, tags=None):
        self.items[key] = (value, tags or "")

    def get(self, key):
        item = self.items.get(key)
        return item[0] if item else None

    def search(self, query, limit=10):
        query = query.lower()
        return [item for item in self.list() if query in item["key"].lower() or query in item["value"].lower()][:limit]

    def delete(self, key):
        return self.items.pop(key, None) is not None


class Shortcuts:
    def __init__(self):
        self.items = {}

    def list(self):
        return self.items

    def add(self, key, expansion):
        value = SimpleNamespace(key=key, expansion=expansion, use_count=0, created_at="test")
        self.items[key] = value
        return value

    def remove(self, key):
        return self.items.pop(key, None) is not None

    def expand(self, key, args=""):
        value = self.items.get(key)
        return value.expansion.replace("{{args}}", args) if value else None


class FakeAlberto:
    def __init__(self):
        self.memory = Memory()
        self.shortcuts = Shortcuts()
        self.catalog = SimpleNamespace(active_squad=None, squads={"engineering": object(), "research": object()})
        self.orchestrator = SimpleNamespace(decide=lambda prompt, active_squad=None: SimpleNamespace(
            mode="squad" if active_squad else "solo",
            reason="browser E2E test",
            engine="mimo",
            squad=active_squad,
            task_routing="chat",
        ))
        self.router = SimpleNamespace(resolve=lambda task: SimpleNamespace(
            provider="test", model_id=f"test-{task}", base_url="http://test.invalid/v1"
        ))
        self.mimo = SimpleNamespace(is_running=lambda: True, memory_list=self.memory.list)
        self.hermes = SimpleNamespace(
            is_running=lambda: False, available_tools=lambda: [], available_skills=lambda: [],
            start=lambda: None, stop=lambda: None, browser=lambda url: f"visited {url}",
            code_execution=lambda code, language="python": {"ok": True, "output": code},
        )
        self._models = {}

    def status(self):
        return {
            "name": "Alberto AI E2E",
            "version": "test",
            "sandbox": "TestSandbox",
            "mimo": {"running": True, "memory_keys": len(self.memory.items)},
            "hermes": {"running": False, "available_tools": 0, "available_skills": 0},
            "shortcuts": len(self.shortcuts.items),
            "squads_alberto": ["engineering", "research"],
            "squads_aiox": [],
            "active_squad": self.catalog.active_squad,
            "models": list(self._models),
        }

    def memory_list(self):
        return self.memory.list()

    def memory_set(self, key, value, tags=None):
        self.memory.set(key, value, tags)

    def memory_get(self, key):
        return self.memory.get(key)

    def memory_search(self, query, limit=10):
        return self.memory.search(query, limit)

    def memory_delete(self, key):
        return self.memory.delete(key)

    def squad_list(self):
        return ["engineering", "research"]

    def squad_describe(self, name):
        return {"name": name} if name in self.catalog.squads else None

    def squad_activate(self, name):
        if name not in self.catalog.squads:
            raise KeyError(name)
        self.catalog.active_squad = name

    def squad_hibernate(self):
        self.catalog.active_squad = None

    def run_squad(self, name, prompt):
        return {"ok": True, "name": name, "prompt": prompt}

    def model_list(self):
        return list(self._models)

    def model_set(self, task, provider, model_id, base_url, credential_env, **kwargs):
        self._models[task] = SimpleNamespace(provider=provider, model_id=model_id, base_url=base_url)

    def model_test(self, task):
        if task not in self._models:
            return {}
        return {"LLM_MODEL": self._models[task].model_id, "OPENAI_API_KEY": ""}

    def chat(self, prompt, conversation_id=None):
        return {
            "response": f"E2E backend reply: {prompt}",
            "strategy": {"mode": "solo", "engine": "mimo", "task_routing": "chat"},
            "tool_calls": [],
            "conversation_id": conversation_id or "e2e-conversation-1",
        }


agent = FakeAlberto()
app = create_app(alberto=agent)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="error")
