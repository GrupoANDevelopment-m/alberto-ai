"""Behavioral contracts for conversation state and intent/message assembly.

These tests assert observable outputs and persistence semantics rather than import/startup.
"""
import json

import pytest

from alberto.conversation import (
    Conversation,
    ConversationStore,
    Turn,
    build_messages,
    detect_intent,
    recall_memory,
)


def test_latest_active_selects_most_recent_turn_and_expires_old_conversations(tmp_path, monkeypatch):
    import alberto.conversation as module

    now = 10_000.0
    monkeypatch.setattr(module.time, "time", lambda: now)
    store = ConversationStore(tmp_path / "conversations.json")
    older = Conversation(id="older", started_at=now - 50, turns=[
        Turn(role="user", content="older turn", at=now - 30)
    ])
    newer = Conversation(id="newer", started_at=now - 60, turns=[
        Turn(role="user", content="newer turn", at=now - 5)
    ])
    expired = Conversation(id="expired", started_at=now - 500, turns=[
        Turn(role="user", content="expired turn", at=now - 500)
    ])
    store.save(older)
    store.save(newer)
    store.save(expired)

    assert store.latest_active(max_age_seconds=60).id == "newer"
    assert store.latest_active(max_age_seconds=4) is None
    assert store.latest_active(max_age_seconds=0) is None


def test_build_messages_preserves_system_context_order_and_turn_history():
    conversation = Conversation(
        id="conversation-contract",
        started_at=1.0,
        turns=[
            Turn(role="user", content="first request", at=2.0),
            Turn(role="assistant", content="first answer", at=3.0),
            Turn(role="user", content="follow-up", at=4.0),
        ],
    )

    messages = build_messages(
        conversation,
        persona_prompt="persona rules",
        catalog_block="actual catalog",
        memory_context="remembered fact",
    )

    assert messages == [
        {"role": "system", "content": "persona rules"},
        {"role": "system", "content": "actual catalog"},
        {"role": "system", "content": "## Memória relevante\nremembered fact"},
        {"role": "user", "content": "first request"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "follow-up"},
    ]


def test_build_messages_omits_empty_optional_context_without_losing_history():
    conversation = Conversation(
        id="conversation-empty-context",
        started_at=1.0,
        turns=[Turn(role="user", content="hello", at=2.0)],
    )

    assert build_messages(conversation, persona_prompt="base") == [
        {"role": "system", "content": "base"},
        {"role": "user", "content": "hello"},
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/s reviewer inspect this diff", {
            "shortcut": "reviewer", "shortcut_args": "inspect this diff"
        }),
        ("vamos usar engineering", {"squad": "engineering"}),
        ("ativa squad finance", {"squad": "finance"}),
        ("por favor abre o site https://example.com", {
            "tool": "browser", "tool_args_text": "por favor abre o site https://example.com"
        }),
        ("conversa normal sem comando", {}),
    ],
)
def test_detect_intent_returns_exact_structured_route(text, expected):
    assert detect_intent(text) == expected


def test_recall_memory_formats_hits_and_limits_values():
    class Memory:
        def memory_search(self, query, *, limit):
            assert query == "deploy"
            assert limit == 2
            return [
                {"key": "release", "value": "v1.2 " + ("x" * 400)},
                {"key": "environment", "value": "staging"},
            ]

    result = recall_memory(type("Agent", (), {"mimo": Memory()})(), "deploy", limit=2)

    assert result.startswith("- **release** = v1.2 ")
    assert len(result.splitlines()[0].split(" = ", 1)[1]) == 300
    assert "- **environment** = staging" in result


def test_recall_memory_fails_closed_to_empty_context_on_storage_error():
    class BrokenMemory:
        def memory_search(self, query, *, limit):
            raise OSError("database unavailable")

    agent = type("Agent", (), {"mimo": BrokenMemory()})()
    assert recall_memory(agent, "anything") == ""


def test_conversation_store_atomic_save_leaves_no_temporary_file(tmp_path):
    path = tmp_path / "state" / "conversations.json"
    store = ConversationStore(path)
    conversation = store.create()
    conversation.add("user", "persist me", meta={"origin": "contract-test"})
    store.save(conversation)

    assert path.exists()
    assert not path.with_suffix(".tmp").exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload[conversation.id]["turns"][0]["content"] == "persist me"
    assert payload[conversation.id]["turns"][0]["meta"] == {"origin": "contract-test"}
