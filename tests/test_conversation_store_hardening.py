"""Hardening tests for persisted conversation state and bounded LLM history."""
import json

import pytest

from alberto.conversation import Conversation, ConversationStore, Turn


def test_history_for_llm_zero_limit_is_empty_and_negative_limit_rejected():
    conversation = Conversation(
        id="conv-test",
        started_at=1.0,
        turns=[
            Turn(role="user", content="first", at=1.0),
            Turn(role="assistant", content="second", at=2.0),
        ],
    )

    assert conversation.history_for_llm(max_turns=0) == []
    assert conversation.history_for_llm(max_turns=1) == [
        {"role": "assistant", "content": "second"}
    ]
    with pytest.raises(ValueError, match="non-negative integer"):
        conversation.history_for_llm(max_turns=-1)
    with pytest.raises(ValueError, match="non-negative integer"):
        conversation.history_for_llm(max_turns=True)


def test_conversation_store_round_trips_turns_and_metadata(tmp_path):
    path = tmp_path / "state" / "conversations.json"
    store = ConversationStore(path)
    conversation = store.create(persona="analyst")
    conversation.add("user", "inspect repository", meta={"source": "test"})
    conversation.add("assistant", "ready", tool="repo.inspect")
    store.save(conversation)

    loaded = ConversationStore(path).get(conversation.id)

    assert loaded is not None
    assert loaded.persona == "analyst"
    assert loaded.history_for_llm() == [
        {"role": "user", "content": "inspect repository"},
        {"role": "assistant", "content": "ready"},
    ]
    assert loaded.turns[0].meta == {"source": "test"}
    assert loaded.turns[1].tool == "repo.inspect"


@pytest.mark.parametrize("payload", ["{not-json", "[]", "null", "42"])
def test_conversation_store_ignores_invalid_top_level_payload(tmp_path, payload):
    path = tmp_path / "conversations.json"
    path.write_text(payload, encoding="utf-8")

    store = ConversationStore(path)

    assert store.list() == []


def test_conversation_store_skips_malformed_records_and_turns(tmp_path):
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps({
        "broken-record": "not-an-object",
        "usable": {
            "started_at": "bad timestamp",
            "persona": 12,
            "turns": [
                {"role": "user", "content": "keep me", "at": 1.0},
                {"role": [], "content": "bad role"},
                "not-a-turn",
                {"role": "assistant", "content": "keep me too", "meta": "bad metadata"},
            ],
            "active_squad": [],
        },
    }), encoding="utf-8")

    store = ConversationStore(path)
    conversation = store.get("usable")

    assert conversation is not None
    assert conversation.persona == "alberto"
    assert conversation.active_squad is None
    assert len(conversation.turns) == 2
    assert conversation.turns[1].meta == {}
    assert conversation.history_for_llm() == [
        {"role": "user", "content": "keep me"},
        {"role": "assistant", "content": "keep me too"},
    ]
