from __future__ import annotations

import hashlib

import pytest

from agent_runtime.models import AgentRuntimeError
from agent_runtime.sessions import (
    DEFAULT_MAX_STRUCTURED_CONTEXT_BYTES,
    MAX_PRIVATE_CONTEXT_VALUE_CHARS,
    AgentSessionStore,
    sanitize_session_metadata,
)


STRUCTURED_KEYS = (
    "last_action_draft",
    "last_submitted_action",
    "last_read_only_evidence",
)


def _json_object_with_exact_size(size: int) -> str:
    prefix = '{"payload":"'
    suffix = '"}'
    assert size >= len(prefix) + len(suffix)
    return f"{prefix}{'x' * (size - len(prefix) - len(suffix))}{suffix}"


def _session(store: AgentSessionStore) -> str:
    return store.create(actor="operator", mode="read_only").id


def test_valid_maximum_sized_structured_json_round_trips_exactly():
    limit = DEFAULT_MAX_STRUCTURED_CONTEXT_BYTES
    store = AgentSessionStore()
    session_id = _session(store)
    value = _json_object_with_exact_size(limit)
    expected_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()

    stored = store.update_private_context(
        session_id,
        {key: value for key in STRUCTURED_KEYS},
    )

    for key in STRUCTURED_KEYS:
        assert stored[key] == value
        assert len(stored[key].encode("utf-8")) == limit
        assert hashlib.sha256(stored[key].encode("utf-8")).hexdigest() == expected_hash


def test_structured_json_one_byte_over_limit_is_rejected():
    limit = 1024
    store = AgentSessionStore(max_structured_context_bytes=limit)
    session_id = _session(store)
    value = _json_object_with_exact_size(limit + 1)

    with pytest.raises(
        AgentRuntimeError,
        match=r"last_action_draft exceeds the structured JSON limit of 1024 bytes",
    ):
        store.update_private_context(session_id, {"last_action_draft": value})

    assert store.get_private_context(session_id) == {}


def test_invalid_structured_json_is_rejected():
    store = AgentSessionStore()
    session_id = _session(store)

    with pytest.raises(
        AgentRuntimeError,
        match=r"last_submitted_action must contain valid JSON",
    ):
        store.update_private_context(
            session_id,
            {"last_submitted_action": '{"status":"submitted"'},
        )

    assert store.get_private_context(session_id) == {}


def test_rejected_structured_update_preserves_all_prior_state_atomically():
    store = AgentSessionStore(max_structured_context_bytes=128)
    session_id = _session(store)
    original_action = '{"draft_id":"act-original","steps":[]}'
    store.update_private_context(
        session_id,
        {
            "last_action_draft": original_action,
            "last_assistant_content": "original response",
        },
    )
    original_state = store.get_private_context(session_id)

    with pytest.raises(AgentRuntimeError):
        store.update_private_context(
            session_id,
            {
                "last_assistant_content": "must not be committed",
                "last_action_draft": _json_object_with_exact_size(129),
            },
        )

    assert store.get_private_context(session_id) == original_state


def test_ordinary_private_text_keeps_existing_bounded_behavior():
    store = AgentSessionStore()
    session_id = _session(store)
    value = f"  {'x' * (MAX_PRIVATE_CONTEXT_VALUE_CHARS + 100)}  "

    stored = store.update_private_context(
        session_id,
        {"last_assistant_content": value},
    )

    assert stored["last_assistant_content"] == "x" * MAX_PRIVATE_CONTEXT_VALUE_CHARS


def test_action_run_metadata_survives_public_session_sanitization():
    run_metadata = sanitize_session_metadata(
        {
            "last_domain": "action_run",
            "last_intent": "action_run_control",
            "last_response_mode": "status",
        }
    )
    summary_metadata = sanitize_session_metadata(
        {
            "last_domain": "action_run",
            "last_intent": "action_run",
        }
    )

    assert run_metadata == {
        "last_domain": "action_run",
        "last_intent": "action_run_control",
        "last_response_mode": "status",
    }
    assert summary_metadata == {
        "last_domain": "action_run",
        "last_intent": "action_run",
    }
