from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from agent_runtime import (
    AgentRuntimeError,
    AgentSessionStore,
    AssistantConfig,
    AssistantContextAssembler,
    AssistantHistoryStore,
    InMemoryAuditSink,
    OpenAIResponsesAssistantAdapter,
    create_assistant_turn,
    create_mock_assistant_turn,
    load_default_assistant_config,
)
from agent_runtime.models import utc_now


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSISTANT_CONFIG_PATH = REPO_ROOT / "config" / "agent_assistant.yaml"


def _write_restricted_key(path: Path, value: str = "test-openai-key\n") -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_assistant_config_loads_default_public_context():
    config = load_default_assistant_config()

    assert config.version == 1
    assert config.provider == "mock"
    assert "simurgh.safety_policy" in config.default_context_resource_ids
    assert "simurgh.field_log_review" in config.default_context_resource_ids

    docs = AssistantContextAssembler(config=config).assemble()
    assert [doc.id for doc in docs] == list(config.default_context_resource_ids)
    assert all(doc.uri.startswith("mds://simurgh/context/") for doc in docs)
    assert all(doc.content_hash for doc in docs)


def test_assistant_config_allows_openai_provider_with_file_secret(monkeypatch, tmp_path):
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    config = load_default_assistant_config()

    assert config.provider == "openai"
    assert config.openai.model == "gpt-5.5"
    assert config.openai.read_api_key() == "test-openai-key"


def test_assistant_context_assembler_rejects_unknown_resource():
    config = load_default_assistant_config()

    with pytest.raises(KeyError):
        AssistantContextAssembler(config=config).assemble(("missing.resource",))


def test_assistant_config_rejects_invalid_shape():
    payload = yaml.safe_load(ASSISTANT_CONFIG_PATH.read_text(encoding="utf-8"))
    payload["default_context_resource_ids"] = []

    with pytest.raises(AgentRuntimeError, match="default_context_resource_ids"):
        AssistantConfig.from_mapping(payload, path=ASSISTANT_CONFIG_PATH)


def test_assistant_config_requires_provider_prompt_templates():
    payload = yaml.safe_load(ASSISTANT_CONFIG_PATH.read_text(encoding="utf-8"))
    payload["provider_input_template"] = "Operator message only: {message}"

    with pytest.raises(AgentRuntimeError, match="provider_input_template"):
        AssistantConfig.from_mapping(payload, path=ASSISTANT_CONFIG_PATH)


def test_assistant_config_rejects_configurable_openai_store():
    payload = yaml.safe_load(ASSISTANT_CONFIG_PATH.read_text(encoding="utf-8"))
    payload["providers"]["openai"]["store"] = True

    with pytest.raises(AgentRuntimeError, match="store is fixed false"):
        AssistantConfig.from_mapping(payload, path=ASSISTANT_CONFIG_PATH)


def test_mock_assistant_turn_requires_enabled_agent(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "false")
    with pytest.raises(PermissionError, match="disabled"):
        create_mock_assistant_turn(
            sessions=AgentSessionStore(),
            audit=InMemoryAuditSink(),
            actor="operator",
            message="Explain current Simurgh policy.",
        )


def test_mock_assistant_turn_hashes_prompt_and_detects_blocked_intent(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    record = create_mock_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="Can you launch the mission?",
        metadata={"source": "simurgh-dashboard"},
    )

    assert record.session.id.startswith("session-")
    assert record.turn.provider == "mock"
    assert "launch" in record.turn.blocked_intents
    assert "does not execute tools" in record.turn.content
    assert record.audit_event.payload_hash
    assert "launch the mission" not in json.dumps(record.audit_event.to_json_dict())
    assert record.audit_event.metadata["blocked_intent_count"] == 1


def test_openai_assistant_turn_builds_non_tool_responses_request(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        captured["api_key"] = api_key
        return {
            "id": "resp-test",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Advisory response."}],
                }
            ],
        }

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)

    record = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="Summarize the safety policy.",
        context_resource_ids=("simurgh.safety_policy",),
    )

    assert record.turn.provider == "openai"
    assert record.turn.model == "gpt-5.5"
    assert record.turn.adapter_version == "openai-responses-v1"
    assert record.turn.content == "Advisory response."
    assert captured["api_key"] == "test-openai-key"
    assert captured["tools"] == []
    assert captured["tool_choice"] == "none"
    assert captured["parallel_tool_calls"] is False
    assert captured["store"] is False
    assert "stream" not in captured
    assert "background" not in captured
    assert "file_ids" not in captured
    assert "messages" not in captured
    assert "conversation" not in captured
    assert "previous_response_id" not in captured
    assert "simurgh.safety_policy" in str(captured["input"])
    assert "No tool execution" in record.turn.safety_notes[0]
    assert audit.list_events()[0].metadata["provider"] == "openai"


def test_openai_assistant_turn_blocks_operational_intent_before_provider_call(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    def fail_post(self, payload, *, api_key):  # noqa: ANN001
        raise AssertionError("provider should not be called for blocked operational intent")

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fail_post)

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="Launch the mission now.",
    )

    assert record.turn.provider == "openai"
    assert "launch" in record.turn.blocked_intents
    assert "no provider request was made" in record.turn.content
    assert "No provider request was made" in record.turn.safety_notes[0]


@pytest.mark.parametrize(
    ("message", "expected_signal"),
    (
        ("Here is a customer ULog excerpt from the field test.", "ulog excerpt"),
        ("The customer .ulg flight log is pasted below.", "ULog artifact"),
        ("The customer flight log is pasted below.", "customer flight log artifact"),
        ("Attach the QGroundControl log from the customer flight.", "QGroundControl log artifact"),
        ("AIRFRAME-01 stopped streaming on 192.168.1.10.", "field vehicle label"),
        ("Private repo path git@github.com:customer/mds-private.git", "private repository path"),
        ("Ticket ID SAR-1042 includes the field notes.", "ticket identifier"),
        ("Serial SN:ABC123456 was visible in the screenshot.", "device serial identifier"),
        ("NetBird peer id peer_abcdef12345 is in the report.", "NetBird peer identifier"),
        ("Screenshot from the customer field test is attached.", "screenshot"),
        ("2026-05-19 17:32:15 field log line was pasted.", "exact timestamp"),
        ("Mission name: South Harbor Recovery should be redacted.", "mission name"),
        ("Customer identifier: CoastTeamAlpha should be private.", "customer or site identifier"),
        ("INFO mavlink-router forwarded packet details from a private field run", "pasted log body"),
        ("Authorization: Bearer mds_test_secret_12345 should not leave the GCS.", "secret assignment"),
        ("The api key is sk-test-redacted-12345.", "secret assignment"),
        ("The password is fieldtest12345.", "secret assignment"),
    ),
)
def test_openai_assistant_turn_blocks_sensitive_field_evidence_before_provider_call(
    monkeypatch,
    tmp_path,
    message,
    expected_signal,
):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    def fail_post(self, payload, *, api_key):  # noqa: ANN001
        raise AssertionError("provider should not be called for sensitive field-log input")

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fail_post)

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message=message,
    )

    assert record.turn.provider == "openai"
    assert expected_signal in record.turn.blocked_intents
    assert "no provider request was made" in record.turn.content
    assert "sensitive field evidence" in record.turn.content
    assert "No provider request was made" in record.turn.safety_notes[0]


def test_openai_assistant_turn_requires_api_key_file(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    with pytest.raises(AgentRuntimeError, match="MDS_AGENT_OPENAI_API_KEY_FILE"):
        create_assistant_turn(
            sessions=AgentSessionStore(),
            audit=InMemoryAuditSink(),
            actor="operator",
            message="Summarize the safety policy.",
        )


def test_openai_assistant_turn_rejects_relative_or_empty_api_key_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", "relative/key")

    with pytest.raises(AgentRuntimeError, match="absolute path"):
        create_assistant_turn(
            sessions=AgentSessionStore(),
            audit=InMemoryAuditSink(),
            actor="operator",
            message="Summarize the safety policy.",
        )

    empty_key = tmp_path / "empty_key"
    _write_restricted_key(empty_key, "")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(empty_key))

    with pytest.raises(AgentRuntimeError, match="empty"):
        create_assistant_turn(
            sessions=AgentSessionStore(),
            audit=InMemoryAuditSink(),
            actor="operator",
            message="Summarize the safety policy.",
        )

    loose_key = tmp_path / "loose_key"
    loose_key.write_text("test-openai-key\n", encoding="utf-8")
    loose_key.chmod(0o644)
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(loose_key))

    with pytest.raises(AgentRuntimeError, match="must not be readable"):
        create_assistant_turn(
            sessions=AgentSessionStore(),
            audit=InMemoryAuditSink(),
            actor="operator",
            message="Summarize the safety policy.",
        )


def test_openai_assistant_config_rejects_unpinned_base_url(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(_write_restricted_key(tmp_path / "openai_api_key")))
    monkeypatch.setenv("MDS_AGENT_OPENAI_BASE_URL", "https://example.invalid/v1")

    with pytest.raises(AgentRuntimeError, match="base_url is pinned"):
        load_default_assistant_config()


def test_openai_provider_prompt_template_is_config_driven(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    config_path = tmp_path / "agent_assistant.yaml"
    payload = yaml.safe_load(ASSISTANT_CONFIG_PATH.read_text(encoding="utf-8"))
    payload["provider"] = "openai"
    payload["provider_input_template"] = "CONFIG TEMPLATE\n{context_blocks}\nMESSAGE={message}"
    config_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    monkeypatch.setenv("MDS_AGENT_ASSISTANT_FILE", str(config_path))
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}]}

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)

    create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="Summarize.",
        context_resource_ids=("simurgh.safety_policy",),
    )

    assert str(captured["input"]).startswith("CONFIG TEMPLATE")
    assert "MESSAGE=Summarize." in str(captured["input"])


def test_openai_assistant_rejects_tool_outputs(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        return {
            "output": [
                {"type": "function_call", "name": "unsafe", "arguments": "{}"},
                {"type": "message", "content": [{"type": "output_text", "text": "Do something"}]},
            ]
        }

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)

    with pytest.raises(AgentRuntimeError, match="non-text output"):
        create_assistant_turn(
            sessions=AgentSessionStore(),
            audit=InMemoryAuditSink(),
            actor="operator",
            message="Summarize.",
        )


def test_assistant_history_store_persists_bounded_transcript_without_audit_leak(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()
    history_path = tmp_path / "assistant_turns.jsonl"
    history = AssistantHistoryStore(history_path, max_records=1)

    first = create_mock_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="First private prompt",
    )
    second = create_mock_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="Second private prompt",
    )
    history.append_turn(record=first, message="First private prompt")
    stored = history.append_turn(record=second, message="Second private prompt")

    reloaded = AssistantHistoryStore(history_path, max_records=1).list_records(actor="operator")
    assert [record.id for record in reloaded] == [stored.id]
    assert reloaded[0].message == ""
    assert reloaded[0].content == ""
    assert reloaded[0].message_hash
    assert "Second private prompt" not in json.dumps(second.audit_event.to_json_dict())
    assert "Second private prompt" not in history_path.read_text(encoding="utf-8")
    assert history_path.stat().st_mode & 0o777 == 0o600


def test_assistant_session_metadata_keeps_only_safe_source(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    sessions = AgentSessionStore()

    record = create_mock_assistant_turn(
        sessions=sessions,
        audit=InMemoryAuditSink(),
        actor="operator",
        message="Summarize safety policy.",
        metadata={
            "source": "simurgh-dashboard",
            "raw_prompt": "AIRFRAME-01 stopped streaming on 192.168.1.10",
            "notes": "customer field evidence",
        },
    )

    assert record.session.metadata == {"channel": "assistant", "source": "simurgh-dashboard"}


def test_assistant_session_metadata_rejects_sensitive_source_value(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")

    record = create_mock_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="Summarize safety policy.",
        metadata={"source": "AIRFRAME-01"},
    )

    assert record.session.metadata == {"channel": "assistant"}


def test_assistant_history_store_applies_age_retention(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()
    history_path = tmp_path / "assistant_turns.jsonl"
    history = AssistantHistoryStore(history_path, max_age_days=1, max_records=10)

    old_turn = create_mock_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="Old private prompt",
    )
    current_turn = create_mock_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="Current private prompt",
    )
    old_record = history.append_turn(record=old_turn, message="Old private prompt")
    history._records = [replace(old_record, created_at=(utc_now() - timedelta(days=2)).isoformat())]
    history._write_records()

    current_record = history.append_turn(record=current_turn, message="Current private prompt")

    reloaded = AssistantHistoryStore(history_path, max_age_days=1, max_records=10).list_records(actor="operator")
    assert [record.id for record in reloaded] == [current_record.id]
    assert "Old private prompt" not in history_path.read_text(encoding="utf-8")


def test_assistant_history_store_compacts_retention_on_reload(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()
    history_path = tmp_path / "assistant_turns.jsonl"
    history = AssistantHistoryStore(history_path, max_age_days=1, max_records=10)

    stale_turn = create_mock_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="Reload stale prompt",
    )
    current_turn = create_mock_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="Reload current prompt",
    )
    stale_record = history.append_turn(record=stale_turn, message="Reload stale prompt")
    current_record = history.append_turn(record=current_turn, message="Reload current prompt")
    history._records = [
        replace(stale_record, created_at=(utc_now() - timedelta(days=2)).isoformat()),
        current_record,
    ]
    history._write_records()

    reloaded = AssistantHistoryStore(history_path, max_age_days=1, max_records=10)

    assert [record.id for record in reloaded.list_records(actor="operator")] == [current_record.id]
    contents = history_path.read_text(encoding="utf-8")
    assert "Reload current prompt" not in contents
    assert "Reload stale prompt" not in contents


def test_assistant_history_store_rejects_corrupt_history_file(tmp_path):
    history_path = tmp_path / "assistant_turns.jsonl"
    history_path.write_text("{not json}\n", encoding="utf-8")

    with pytest.raises(AgentRuntimeError, match="invalid record"):
        AssistantHistoryStore(history_path)


def test_mock_assistant_turn_can_use_existing_session(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()
    session = sessions.create(actor="operator", mode="read_only")

    record = create_mock_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=session.id,
        message="Summarize the safety policy.",
        context_resource_ids=("simurgh.safety_policy",),
    )

    assert record.session.id == session.id
    assert [doc.id for doc in record.turn.context_documents] == ["simurgh.safety_policy"]


def test_mock_assistant_turn_rejects_cross_actor_session_reuse(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()
    session = sessions.create(actor="operator-a", mode="read_only")

    with pytest.raises(PermissionError, match="different actor"):
        create_mock_assistant_turn(
            sessions=sessions,
            audit=audit,
            actor="operator-b",
            session_id=session.id,
            message="Summarize the safety policy.",
        )


def test_mock_assistant_turn_rejects_closed_session(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()
    session = sessions.create(actor="operator", mode="read_only")
    sessions.close(session.id)

    with pytest.raises(AgentRuntimeError, match="session is closed"):
        create_mock_assistant_turn(
            sessions=sessions,
            audit=audit,
            actor="operator",
            session_id=session.id,
            message="Summarize the safety policy.",
        )
