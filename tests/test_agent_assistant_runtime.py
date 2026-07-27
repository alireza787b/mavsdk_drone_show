from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

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
from agent_runtime.evidence import ReadOnlyEvidenceBundle
from agent_runtime.assistant import (
    _previous_evidence_followup_fallback_turn,
    _semantic_rewrite_from_payload,
    redact_sensitive_input_for_provider,
    rewrite_operator_message_with_provider,
)
from agent_runtime.mds_read_tools import provider_read_intent_contracts
from agent_runtime.models import utc_now


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSISTANT_CONFIG_PATH = REPO_ROOT / "config" / "agent_assistant.yaml"


def _write_restricted_key(path: Path, value: str = "test-openai-key\n") -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


class _PublicCommandTrackerStub:
    def __init__(self, *, recent=(), active=(), stats=None):  # noqa: ANN001
        self.recent = list(recent)
        self.active = list(active)
        self.stats = dict(stats or {})
        self.calls: list[str] = []

    async def get_recent(self, *, limit=20, **_kwargs):  # noqa: ANN001
        self.calls.append("recent")
        return self.recent[:limit]

    async def get_active_commands(self):
        self.calls.append("active")
        return list(self.active)

    async def get_statistics(self):
        self.calls.append("statistics")
        return dict(self.stats)


def _fleet_summary_test_deps() -> SimpleNamespace:
    """Keep fleet-answer tests independent from the developer's active config."""

    return SimpleNamespace(
        load_config=lambda: [
            {
                "hw_id": 1,
                "pos_id": 1,
                "callsign": "SCOUT",
                "ip": "192.0.2.33",
                "mavlink_port": 14550,
            }
        ],
        get_all_drone_positions=lambda: [],
        load_swarm=lambda: [],
    )


def test_assistant_config_loads_default_public_context():
    config = load_default_assistant_config()

    assert config.version == 1
    assert config.provider == "mock"
    assert "semantic-understanding layer" in config.semantic_routing_instructions
    assert "simurgh.safety_policy" in config.default_context_resource_ids
    assert "simurgh.field_log_review" in config.default_context_resource_ids

    docs = AssistantContextAssembler(config=config).assemble()
    assert [doc.id for doc in docs] == list(config.default_context_resource_ids)
    assert all(doc.uri.startswith("mds://simurgh/context/") for doc in docs)
    assert all(doc.content_hash for doc in docs)


def test_previous_evidence_provider_fallback_uses_operator_language():
    turn = _previous_evidence_followup_fallback_turn(
        config=load_default_assistant_config(),
        followup_kind="assess_previous_evidence",
        previous_answer="Drone 1 telemetry was healthy.",
        context_documents=(),
    )

    assert "evidence already checked" in turn.content.casefold()
    assert "read-only simurgh answer" not in turn.content.casefold()


def test_assistant_config_allows_openai_provider_with_file_secret(monkeypatch, tmp_path):
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    monkeypatch.delenv("MDS_AGENT_OPENAI_MODEL", raising=False)

    config = load_default_assistant_config()

    assert config.provider == "openai"
    assert config.openai.model == "gpt-5.6-sol"
    assert config.openai.web_search.enabled is False
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
    assert "clarify the target or intended sequence" in record.turn.content
    assert "Provider:" not in record.turn.content
    assert "Loaded context resources" not in record.turn.content
    assert record.audit_event.payload_hash
    assert "launch the mission" not in json.dumps(record.audit_event.to_json_dict())
    assert record.audit_event.metadata["blocked_intent_count"] == 1


def test_openai_assistant_turn_builds_non_tool_responses_request(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    monkeypatch.delenv("MDS_AGENT_OPENAI_MODEL", raising=False)
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
    assert record.turn.model == "gpt-5.6-sol"
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


def test_openai_response_parser_accepts_reasoning_items(monkeypatch, tmp_path):
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    adapter = OpenAIResponsesAssistantAdapter(config=load_default_assistant_config())

    text = adapter._extract_response_text(
        {
            "output": [
                {"type": "reasoning", "summary": []},
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Reasoned answer."}],
                },
            ],
        }
    )

    assert text == "Reasoned answer."


def test_openai_response_parser_preserves_web_search_citation_sources(monkeypatch, tmp_path):
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    adapter = OpenAIResponsesAssistantAdapter(config=load_default_assistant_config())

    text = adapter._extract_response_text(
        {
            "output": [
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {"type": "search", "query": "weather today"},
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Public weather answer.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.com/weather",
                                    "title": "Example Weather",
                                }
                            ],
                        }
                    ],
                },
            ],
        }
    )

    assert "Public weather answer." in text
    assert "Sources:" in text
    assert "[Example Weather](https://example.com/weather)" in text


def test_openai_response_parser_falls_back_to_web_search_call_sources(monkeypatch, tmp_path):
    adapter = OpenAIResponsesAssistantAdapter(config=load_default_assistant_config())

    text = adapter._extract_response_text(
        {
            "output": [
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {
                        "type": "search",
                        "sources": [
                            {
                                "url": "https://example.com/weather",
                                "title": "Example Weather",
                            }
                        ],
                    },
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Public weather answer.",
                            "annotations": [],
                        }
                    ],
                },
            ],
        }
    )

    assert "Public weather answer." in text
    assert "Sources:" in text
    assert "[Example Weather](https://example.com/weather)" in text


def test_openai_assistant_turn_uses_web_search_only_for_public_general_queries(monkeypatch, tmp_path):
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    monkeypatch.setenv("MDS_AGENT_WEB_SEARCH_ENABLED", "true")
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        return {
            "output": [
                {"type": "web_search_call", "status": "completed", "action": {"type": "search"}},
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Use a local aviation weather source before flight.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.com/weather",
                                    "title": "Example Weather",
                                }
                            ],
                        }
                    ],
                },
            ]
        }

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="how is the weather today in Taipei?",
    )

    assert record.turn.provider == "openai"
    assert record.audit_event.metadata["web_search_enabled"] is True
    assert captured["tools"] == [
        {
            "type": "web_search",
            "search_context_size": "medium",
            "external_web_access": True,
        }
    ]
    assert captured["include"] == ["web_search_call.action.sources"]
    assert captured["tool_choice"] == "required"
    assert "Public web-search source requirements" in captured["input"]
    assert "Do not invent URLs" in captured["input"]
    assert record.turn.provider_tools == {
        "web_search_requested": True,
        "web_search_returned": True,
        "citation_count": 1,
        "source_status": "citations_returned",
    }
    assert "Sources:" in record.turn.content
    assert "https://example.com/weather" in record.turn.content


def test_openai_assistant_turn_uses_web_search_for_public_px4_release_lookup(monkeypatch, tmp_path):
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    monkeypatch.setenv("MDS_AGENT_WEB_SEARCH_ENABLED", "true")
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        captured["api_key"] = api_key
        return {
            "output": [
                {"type": "web_search_call", "status": "completed", "action": {"type": "search"}},
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "PX4 current release should be verified from the official PX4 release page before operational planning.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://github.com/PX4/PX4-Autopilot/releases",
                                    "title": "PX4 Autopilot releases",
                                }
                            ],
                        }
                    ],
                },
            ]
        }

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="What is the latest stable PX4 Autopilot release? Verify it online and cite the source.",
    )

    assert record.turn.provider == "openai"
    assert captured["api_key"] == "test-openai-key"
    assert captured["tool_choice"] == "required"
    assert captured["tools"] == [
        {
            "type": "web_search",
            "search_context_size": "medium",
            "external_web_access": True,
        }
    ]
    assert "Public web-search source requirements" in captured["input"]
    assert record.audit_event.metadata["web_search_enabled"] is True
    assert record.turn.provider_tools["web_search_returned"] is True
    assert "PX4 Autopilot releases" in record.turn.content


def test_openai_web_search_does_not_steal_mds_fleet_queries(monkeypatch, tmp_path):
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    monkeypatch.setenv("MDS_AGENT_WEB_SEARCH_ENABLED", "true")

    def fail_post(self, payload, *, api_key):  # noqa: ANN001
        raise AssertionError("web/provider should not be called for local fleet state")

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fail_post)

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="How many drones do we have configured?",
    )

    assert record.turn.provider == "mds-tools"
    assert record.audit_event.metadata["tool_intent"] == "fleet_summary"
    assert record.audit_event.metadata["web_search_enabled"] is False


def test_openai_web_search_does_not_answer_local_installed_px4_state(monkeypatch, tmp_path):
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    monkeypatch.setenv("MDS_AGENT_WEB_SEARCH_ENABLED", "true")

    def fail_post(self, payload, *, api_key):  # noqa: ANN001
        raise AssertionError("public web/provider should not answer local installed PX4 state")

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fail_post)

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="what PX4 version are our drones running on?",
    )

    assert record.turn.provider == "mds-tools"
    assert record.audit_event.metadata["web_search_enabled"] is False
    assert "web-search" not in record.turn.content.lower()


def test_assistant_turn_answers_mds_fleet_prompt_with_local_tools(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="How many drones do we have configured?",
    )

    assert record.turn.provider == "mds-tools"
    assert record.turn.model == "local-read-only"
    assert "configured drone" in record.turn.content.lower()
    assert "No direct drone API" in record.turn.safety_notes[1]
    assert record.audit_event.metadata["tool_intent"] == "fleet_summary"


def test_assistant_turn_does_not_reuse_fleet_topic_for_general_distance_question(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="How many drones do we have configured?",
    )
    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="How many kilometers is that from Tehran to New York?",
    )

    assert first.audit_event.metadata["tool_intent"] == "fleet_summary"
    assert followup.turn.provider == "mds-tools"
    assert followup.audit_event.metadata["tool_intent"] == "public_geography"
    assert followup.audit_event.metadata["query_domain"] == "general"
    assert "9,855 km" in followup.turn.content
    assert "Fleet status from GCS configuration" not in followup.turn.content


def test_assistant_turn_does_not_route_geography_flight_math_to_swarm_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="What is lat and long of Damavand peak and if I want to create a flight around it at 10 distance around how long would be the flight",
    )

    assert record.turn.provider == "mds-tools"
    assert record.audit_event.metadata["tool_intent"] == "public_geography"
    assert record.audit_event.metadata["query_domain"] == "general"
    assert "35.9555" in record.turn.content
    assert "52.1101" in record.turn.content
    assert "62.8 km" in record.turn.content
    assert "Configured/planned swarm geometry" not in record.turn.content


def test_assistant_turn_rebinds_public_geography_followup_after_swarm_topic(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="What formation swarm is defined right now?",
    )
    assert first.audit_event.metadata["tool_intent"] == "swarm_topology"
    assert first.session.metadata["last_domain"] == "swarm"

    damavand = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="What is the lat long altitude of damavand peak",
    )
    assert damavand.audit_event.metadata["tool_intent"] == "public_geography"
    assert damavand.session.metadata["last_domain"] == "public_geography"
    assert "WGS84 decimal degrees" in damavand.turn.content
    assert "5,609 m" in damavand.turn.content
    assert "Configured/planned swarm geometry" not in damavand.turn.content

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="Yes meter and wgs84",
    )
    assert followup.audit_event.metadata["tool_intent"] == "public_geography"
    assert followup.session.metadata["last_domain"] == "public_geography"
    assert "Mount Damavand peak" in followup.turn.content
    assert "WGS84 decimal degrees" in followup.turn.content
    assert "Configured/planned swarm geometry" not in followup.turn.content


def test_assistant_turn_returns_bounded_provider_failure_for_public_lookup(monkeypatch, tmp_path):
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    monkeypatch.setenv("MDS_AGENT_WEB_SEARCH_ENABLED", "true")

    def fail_post(self, payload, *, api_key):  # noqa: ANN001
        raise AgentRuntimeError("network error")

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fail_post)

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="What is the latest weather today in Taipei?",
    )

    assert record.turn.provider == "mds-tools"
    assert "network error" not in record.turn.content.lower()
    assert "external provider was unavailable" in record.turn.content.lower()
    assert "verified local mds result" in record.turn.content.lower()
    assert record.audit_event.metadata["web_search_enabled"] is True


def test_assistant_turn_answers_capability_catalog_from_registry(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_MCP_ENABLED", "false")

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="What MCP tools and API capabilities can Simurgh expose?",
    )

    assert record.turn.provider == "mds-tools"
    assert "curated registry and policy layer" in record.turn.content
    assert "tools/list" in record.turn.content
    assert "MCP endpoint: disabled" in record.turn.content
    assert "mds.fleet.telemetry.read" in record.turn.content
    assert record.audit_event.metadata["tool_intent"] == "capability_catalog"


def test_assistant_turn_reports_configured_mcp_endpoint_without_placeholder(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_MCP_ENABLED", "true")
    monkeypatch.setenv("MDS_MCP_RESOURCE_URL", "https://gcs.example.test/api/v1/simurgh/mcp")

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="If I want to connect n8n to Simurgh MCP what address and considerations should I use?",
    )

    assert record.turn.provider == "mds-tools"
    assert "https://gcs.example.test/api/v1/simurgh/mcp" in record.turn.content
    assert "configured by `MDS_MCP_RESOURCE_URL`" in record.turn.content
    assert "<gcs-host>" not in record.turn.content
    assert "never to a drone IP" in record.turn.content
    assert record.audit_event.metadata["tool_intent"] == "capability_catalog"


@pytest.mark.parametrize(
    ("message", "expected_phrases", "forbidden_phrases"),
    (
        (
            "what read-only APIs/tools can Simurgh use for SITL status?",
            ("Approved MDS capabilities for SITL", "mds.sitl.policy.read", "mds.sitl.instances.read", "GET /api/v1/system/sitl/instances"),
            ("Current safe menu preview", "mds.fleet.telemetry.read"),
        ),
        (
            "what can you inspect about SAR and QuickScout mission status?",
            ("QuickScout/SAR missions", "mds.sar.missions.read", "mds.sar.mission.status.read", "mission_id"),
            ("Current safe menu preview", "mds.fleet.telemetry.read"),
        ),
        (
            "can n8n use the same MCP menu for fleet telemetry and board sidecar status?",
            ("fleet telemetry, boards, and sidecars", "mds.fleet.telemetry.read", "mds.fleet.sidecars.read", "tools/list"),
            ("Current safe menu preview", "Plan SAR mission"),
        ),
    ),
)
def test_assistant_turn_answers_domain_tool_capabilities_from_registry(
    monkeypatch,
    message,
    expected_phrases,
    forbidden_phrases,
):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message=message,
    )

    assert record.turn.provider == "mds-tools"
    assert record.turn.model == "local-read-only"
    assert record.audit_event.metadata["tool_intent"] == "registry_domain_tool_summary"
    assert record.audit_event.metadata["response_mode"] == "capability"
    assert "Dashboard chat and external MCP clients use the same approved capability menu" in record.turn.content
    assert "No route, configuration, upload, mission, or drone action was executed" in record.turn.content
    for phrase in expected_phrases:
        assert phrase in record.turn.content
    for phrase in forbidden_phrases:
        assert phrase not in record.turn.content




@pytest.mark.parametrize(
    ("message", "expected_intent", "required_phrases", "forbidden_phrases"),
    (
        (
            "can you give me link to the doc so where I can read about how to setup new board and setup its env and keys",
            "board_setup_help",
            ("/fleet-enrollment", "/api/v1/simurgh/context/mds.init_setup/markdown", "/environments"),
            ("Connectivity from GCS state",),
        ),
        (
            "can you give me link to read about creating sitl demo?",
            "sitl_help",
            ("app/linux_dashboard_start.sh --sitl", "/sitl-control", "/api/v1/simurgh/context/mds.advanced_sitl/markdown"),
            ("Connectivity from GCS state",),
        ),
        (
            "what runtime we are now? if I want to change to sitl what should I do if not currently?",
            "sitl_help",
            ("Current GCS mode", "--prod --sitl", "No drone command was sent"),
            ("Simurgh Operator mock assistant",),
        ),
        (
            "can you check log and see what warning we have in backend?",
            "backend_log_summary",
            ("Backend warning/error summary", "/logs", "/api/v1/simurgh/context/mds.logging_system/markdown"),
            ("I can’t inspect backend logs directly here",),
        ),
        (
            "if I want to send drone 1 to takeoff 5 m then wait 10s then 6m north then return, can you do that? do you have the tools? what actions APIs you gonna use if I allow you and disable the circuit brake?",
            "action_capability",
            ("can draft", "mds.flight.command.execute", "Operator confirmation", "Circuit breaker"),
            ("cannot execute", "future approved action wrapper", "Simurgh Operator mock assistant is active"),
        ),
        (
            "What's the difference of quick scoute and swarm trajectory mode",
            "mission_mode_comparison",
            ("QuickScout and Swarm Trajectory are different", "PX4 Mission-style", "Mission Type 4", "/api/v1/simurgh/context/mds.quickscout/markdown", "/api/v1/simurgh/context/mds.mission_planning_workspace/markdown"),
            ("Configured/planned swarm geometry", "Cluster roots/leaders", "Loaded show state"),
        ),
        (
            "what is swarm formation planned now?",
            "swarm_topology",
            ("Configured/planned swarm geometry", "/swarm-design", "/api/v1/simurgh/context/mds.swarm_trajectory/markdown"),
            ("Loaded show state",),
        ),
        (
            "what are different modes of drone show and their different launch modes?",
            "show_modes_help",
            (
                "Drone Show has two workflow families",
                "Normal Drone Show / SkyBrush ZIP",
                "Custom CSV Drone Show",
                "GLOBAL with Auto Global Launch Corrector",
                "LOCAL mode",
                "/api/v1/simurgh/context/mds.drone_show/markdown",
            ),
            ("Blocked intent signals", "Loaded show state", "SkyBrush show upload workflow"),
        ),
        (
            "what drone show is planned now? how long it will take?",
            "show_summary",
            ("Loaded show state", "operator-selected package", "/manage-drone-show", "/swarm-trajectory"),
            ("Connectivity from GCS state",),
        ),
        (
            "Whay drone show is uploaded now and how long it takes?",
            "show_summary",
            ("Loaded show state", "operator-selected package", "/manage-drone-show"),
            ("SkyBrush show upload workflow", "Upload the SkyBrush ZIP"),
        ),
        (
            "is there a drone show uploaded and ready?",
            "show_summary",
            ("Loaded show state", "Readiness signals", "Uploaded/loaded does not by itself mean fly-ready"),
            ("I can’t confirm readiness", "SkyBrush show upload workflow"),
        ),
        (
            "what is the scout drone IP?",
            "fleet_summary",
            (),
            ("I can’t see or provide", "private network details"),
        ),
        (
            "if I want to add a third drone now, what workflow must be done?",
            "add_drone_workflow",
            ("Add-drone workflow", "Fleet Enrollment", "Environment registry", "No drone command, config write"),
            ("Fleet status from GCS configuration", "This is a read-only dashboard answer"),
        ),
        (
            "How to upload skybrush drone show",
            "show_upload_help",
            ("SkyBrush show upload workflow", "/manage-drone-show", "POST /api/v1/shows/skybrush/import", "/api/v1/simurgh/context/mds.drone_show/markdown"),
            ("Loaded show state", "Connectivity from GCS state"),
        ),
        (
            "if I want to build new drone 3 on a raspberry pi what should I do? do we have docs so give me link to read or any script?",
            "companion_setup_help",
            ("tools/install_mds_node.sh", "tools/install_companion.sh", "/api/v1/simurgh/context/mds.init_setup/markdown", "/fleet-enrollment"),
            ("Useful MDS references", "generic checklist"),
        ),
        (
            "I mean for setup new companion computer what should I do?",
            "companion_setup_help",
            ("node bootstrap path", "tools/mds_node_init.sh", "Raspberry Pi services", "No drone command was sent"),
            ("Install only approved software",),
        ),
        (
            "Is the swarm mission ready for a field test before turning on and flying?",
            "swarm_readiness",
            ("Smart Swarm readiness from current GCS evidence", "Saved topology", "Before turning aircraft on or flying", "/swarm-design"),
            ("Read-only registry check for one SAR mission status", "mission_id=ready", "mission_id=reay"),
        ),
        (
            "Combien de drones sont configurés maintenant ?",
            "fleet_summary",
            ("Fleet status from GCS configuration", "configured drone"),
            ("Provider answer", "I can’t see"),
        ),
        (
            "Quel est l'adresse IP du drone scout ?",
            "fleet_summary",
            (),
            ("private network details", "I can’t see"),
        ),
    ),
)
def test_assistant_turn_answers_pm_followup_prompts_with_local_mds_tools(
    monkeypatch,
    message,
    expected_intent,
    required_phrases,
    forbidden_phrases,
):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message=message,
        deps=_fleet_summary_test_deps() if expected_intent == "fleet_summary" else None,
    )

    assert record.turn.provider == "mds-tools"
    assert record.turn.model == "local-read-only"
    assert record.audit_event.metadata["tool_intent"] == expected_intent
    for phrase in required_phrases:
        assert phrase in record.turn.content
    for phrase in forbidden_phrases:
        assert phrase not in record.turn.content
    if "ip" in message.lower() and "scout" in message.lower():
        content_lower = record.turn.content.lower()
        assert "scout" in content_lower
        assert "192.0.2.33" in content_lower


@pytest.mark.parametrize(
    ("actor_role", "required_phrase", "forbidden_phrase"),
    [
        ("viewer", "No guarded GCS actions are available", "can draft"),
        ("operator", "can draft", "Create SITL instance"),
        ("admin", "can draft", "No guarded GCS actions are available"),
    ],
)
def test_assistant_action_capability_is_filtered_by_actor_role(
    monkeypatch,
    actor_role,
    required_phrase,
    forbidden_phrase,
):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_MODE", "sitl")

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor=f"{actor_role}-user",
        actor_role=actor_role,
        message=(
            "if I want to send drone 1 to takeoff 5 m then wait 10s then 6m "
            "north then return, can you do that? do you have the tools? what "
            "actions APIs you gonna use if I allow you and disable the circuit brake?"
        ),
    )

    assert record.audit_event.metadata["tool_intent"] == "action_capability"
    assert required_phrase in record.turn.content
    assert forbidden_phrase not in record.turn.content


def test_assistant_turn_uses_session_topic_for_ambiguous_show_followup(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="what drone show is planned now?",
    )
    assert first.audit_event.metadata["tool_intent"] == "show_summary"
    assert first.session.metadata["last_domain"] == "drone_show"

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="is there any uploaded?",
    )

    assert followup.turn.provider == "mds-tools"
    assert followup.audit_event.metadata["tool_intent"] == "show_summary"
    assert "Loaded show state" in followup.turn.content
    assert "I can’t see uploads from here" not in followup.turn.content


def test_assistant_turn_interprets_show_followup_from_session_context(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="is there a drone show uploaded and ready?",
    )

    assert first.turn.provider == "mds-tools"
    assert first.audit_event.metadata["tool_intent"] == "show_summary"
    assert first.audit_event.metadata["response_mode"] == "status"
    assert first.session.metadata["last_domain"] == "drone_show"

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="what does it mean? you cant keep history?",
    )

    assert followup.turn.provider == "mds-tools"
    assert followup.audit_event.metadata["tool_intent"] == "show_summary"
    assert followup.audit_event.metadata["response_mode"] == "interpret"
    assert "I can keep short chat context" in followup.turn.content
    assert "How to read the current drone-show state" in followup.turn.content
    assert "Uploaded/loaded means show files exist" in followup.turn.content
    assert "Loaded show state from GCS show-management files" not in followup.turn.content


def test_assistant_turn_interprets_log_followup_from_session_context(monkeypatch):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools

    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    def fake_recent_warning_events(self, **_kwargs):  # noqa: ANN001
        return (
            [
                {
                    "ts": "2026-05-26T08:51:00Z",
                    "level": "WARNING",
                    "source": "/var/log/mds-gcs.log",
                    "message": "08:51:00 WARNING [api] API GET /api/v1/commands/active -> 401 (0.001s)",
                },
                {
                    "ts": "2026-05-26T08:51:01Z",
                    "level": "WARNING",
                    "source": "/var/log/mds-gcs.log",
                    "message": "08:51:01 WARNING [api] API POST /api/v1/simurgh/assistant/turns -> 401 (0.001s)",
                },
            ],
            ["/var/log/mds-gcs.log"],
        )

    monkeypatch.setattr(MdsReadOnlyTools, "_recent_warning_events", fake_recent_warning_events)
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="check the latest logs and report anything operationally important",
    )

    assert first.turn.provider == "mds-tools"
    assert first.session.metadata["last_domain"] == "logs"
    assert first.audit_event.metadata["tool_intent"] == "backend_log_summary"
    assert first.audit_event.metadata["response_mode"] == "status"
    assert "HTTP authorization warnings" in first.turn.content

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="what does it mean?",
    )

    assert followup.turn.provider == "mds-tools"
    assert followup.audit_event.metadata["tool_intent"] == "backend_log_summary"
    assert followup.audit_event.metadata["response_mode"] == "interpret"
    assert "Operational interpretation of backend warnings" in followup.turn.content
    assert "HTTP authorization warnings" in followup.turn.content
    assert "not a MAVLink" in followup.turn.content
    assert "Most recent entries:" not in followup.turn.content


def test_assistant_turn_interprets_log_followup_without_repeating_table(monkeypatch):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools

    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    def fake_recent_warning_events(self, **_kwargs):  # noqa: ANN001
        return (
            [
                {
                    "ts": "03:17:15.633",
                    "level": "WARNING",
                    "source": "/var/log/mds-gcs.log",
                    "message": "03:17:15.633 WARNING [api] API GET /api/v1/commands/active -> 401 (0.001s)",
                },
                {
                    "ts": "03:19:09.908",
                    "level": "WARNING",
                    "source": "/var/log/mds-gcs.log",
                    "message": "03:19:09.908 WARNING [api] API POST /api/v1/simurgh/assistant/turns -> 401 (0.000s)",
                },
            ],
            ["/var/log/mds-gcs.log"],
        )

    monkeypatch.setattr(MdsReadOnlyTools, "_recent_warning_events", fake_recent_warning_events)
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="check latest logs tell me whats going on",
    )

    assert first.turn.provider == "mds-tools"
    assert first.session.metadata["last_domain"] == "logs"
    assert "Most recent entries:" in first.turn.content
    assert "03:17:15.633" in first.turn.content
    assert "time n/a" not in first.turn.content

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="does this mean something is wrong?",
    )

    assert followup.turn.provider == "mds-tools"
    assert followup.audit_event.metadata["tool_intent"] == "backend_log_summary"
    assert followup.audit_event.metadata["response_mode"] == "interpret"
    assert "Short answer: this does not look like a drone" in followup.turn.content
    assert "Fix priority: low for flight readiness" in followup.turn.content
    assert "Most recent entries:" not in followup.turn.content
    assert "time n/a" not in followup.turn.content


def test_assistant_turn_composes_previous_evidence_followup_with_openai(monkeypatch, tmp_path):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools

    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    def fake_recent_warning_events(self, **_kwargs):  # noqa: ANN001
        return (
            [
                {
                    "ts": "2026-05-26T08:51:00Z",
                    "level": "WARNING",
                    "source": "/var/log/mds-gcs.log",
                    "message": "08:51:00 WARNING [api] API GET /api/v1/commands/active -> 401 (0.001s)",
                }
            ],
            ["/var/log/mds-gcs.log"],
        )

    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        captured["api_key"] = api_key
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Short answer: no, that previous warning pattern is API authorization noise, not a MAVLink or flight-control fault. Check login/token polling only if an operator workflow is failing.",
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(MdsReadOnlyTools, "_recent_warning_events", fake_recent_warning_events)
    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="check latest logs tell me whats going on",
    )
    assert first.turn.provider == "mds-tools"
    assert first.audit_event.metadata["tool_intent"] == "backend_log_summary"
    assert first.audit_event.metadata["read_only_evidence"]["intent"] == "backend_log_summary"

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="does this mean something is wrong?",
        allow_provider_for_local_tools=True,
    )

    assert followup.turn.provider == "openai"
    assert followup.audit_event.metadata["tool_intent"] == "evidence_followup"
    assert followup.audit_event.metadata["response_mode"] == "followup"
    assert followup.audit_event.metadata["retrieved_context_count"] == 2
    assert followup.audit_event.metadata["provider_composed_from_previous_evidence"] is True
    assert "authorization noise" in followup.turn.content
    assert "Most recent entries:" not in followup.turn.content
    captured_input = str(captured["input"])
    assert captured["api_key"] == "test-openai-key"
    assert captured["tools"] == []
    assert captured["tool_choice"] == "none"
    assert "session.previous_assistant_answer" in captured_input
    assert "session.previous_read_only_mds_evidence" in captured_input
    assert "Previous read-only intent: backend_log_summary" in captured_input


def test_assistant_turn_composes_previous_evidence_source_followup_with_source_refs(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    evidence = ReadOnlyEvidenceBundle.from_answer(
        intent="registry_read_execution",
        response_mode="status",
        tool_ids=("mds.logs.sessions.read",),
        source="registry_read_only_mds",
        content=json.dumps({"sessions": [{"session_id": "s_20260527_174402"}]}),
        summary="GCS log sessions: one recent session was available.",
        source_refs=(
            {
                "tool_id": "mds.logs.sessions.read",
                "title": "Read log sessions",
                "source": "registry_read_only_mds",
                "route_method": "GET",
                "route_path": "/api/logs/sessions",
                "status_code": 200,
                "truncated": False,
                "docs": ("docs/guides/logging-system.md",),
            },
        ),
    ).public_metadata()
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        captured["api_key"] = api_key
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "I used the previous read-only registry evidence: tool `mds.logs.sessions.read`, API `GET /api/logs/sessions`, and docs `docs/guides/logging-system.md`. No fresh check was performed.",
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()
    session = sessions.create(actor="operator", mode="read_only", metadata={"last_domain": "logs"})
    sessions.update_private_context(
        session.id,
        {
            "last_assistant_content": "Latest read-only log summary: one recent GCS log session is available. No drone command was sent.",
            "last_domain": "logs",
            "last_intent": "registry_read_execution",
            "last_tool_intent": "registry_read_execution",
            "last_read_only_evidence": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
        },
    )

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=session.id,
        message="what API/source did you use and where can I check it?",
        allow_provider_for_local_tools=True,
    )

    assert followup.turn.provider == "openai"
    assert followup.audit_event.metadata["tool_intent"] == "evidence_followup"
    assert followup.audit_event.metadata["evidence_followup_kind"] == "source_previous_evidence"
    assert followup.audit_event.metadata["read_only_evidence"]["source_refs"][0]["route_path"] == "/api/logs/sessions"
    assert "mds.logs.sessions.read" in followup.turn.content
    captured_input = str(captured["input"])
    assert captured["api_key"] == "test-openai-key"
    assert "Conversation task: source_previous_evidence" in captured_input
    assert "source_refs" in captured_input
    assert "/api/logs/sessions" in captured_input
    assert "docs/guides/logging-system.md" in captured_input


def test_assistant_turn_composes_previous_evidence_field_brief(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    evidence = ReadOnlyEvidenceBundle.from_answer(
        intent="fleet_connectivity",
        response_mode="status",
        tool_ids=("mds.fleet.heartbeats.read",),
        content="Connectivity from GCS state: 0/2 drone(s) currently look live.",
        summary="Connectivity from GCS state: 0/2 drone(s) currently look live.",
    ).public_metadata()
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Field checklist: verify QGC vehicle list, confirm fresh heartbeat, keep this read-only, and do not treat stale presence as readiness.",
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()
    session = sessions.create(actor="operator", mode="read_only", metadata={"last_domain": "fleet"})
    sessions.update_private_context(
        session.id,
        {
            "last_assistant_content": "Connectivity from GCS state: 0/2 drone(s) currently look live. No drone command was sent.",
            "last_domain": "fleet",
            "last_intent": "fleet_connectivity",
            "last_tool_intent": "fleet_connectivity",
            "last_read_only_evidence": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
        },
    )

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=session.id,
        message="summarize this as field instructions for the team",
        allow_provider_for_local_tools=True,
    )

    assert followup.turn.provider == "openai"
    assert followup.audit_event.metadata["tool_intent"] == "evidence_followup"
    assert followup.audit_event.metadata["evidence_followup_kind"] == "field_brief_previous_evidence"
    assert "Field checklist" in followup.turn.content
    assert "Conversation task: field_brief_previous_evidence" in str(captured["input"])


def test_assistant_turn_blocks_action_even_when_source_followup_matches(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    evidence = ReadOnlyEvidenceBundle.from_answer(
        intent="registry_read_execution",
        response_mode="status",
        tool_ids=("mds.commands.active.read",),
        source="registry_read_only_mds",
        content=json.dumps({"commands": []}),
        summary="No active commands were reported.",
        source_refs=(
            {
                "tool_id": "mds.commands.active.read",
                "title": "Read active commands",
                "source": "registry_read_only_mds",
                "route_method": "GET",
                "route_path": "/api/v1/commands/active",
                "status_code": 200,
                "docs": ("docs/apis/gcs-api-server.md",),
            },
        ),
    ).public_metadata()

    def fail_post(self, payload, *, api_key):  # noqa: ANN001
        raise AssertionError("action-bearing source follow-up must be blocked before provider")

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fail_post)
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()
    session = sessions.create(actor="operator", mode="read_only", metadata={"last_domain": "commands"})
    sessions.update_private_context(
        session.id,
        {
            "last_assistant_content": "No active commands were reported. No drone command was sent.",
            "last_domain": "commands",
            "last_intent": "registry_read_execution",
            "last_tool_intent": "registry_read_execution",
            "last_read_only_evidence": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
        },
    )

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=session.id,
        message="show me the source and launch it now",
        allow_provider_for_local_tools=True,
    )

    assert followup.turn.provider == "openai"
    assert "launch" in followup.turn.blocked_intents
    assert followup.audit_event.metadata["tool_intent"] is None
    assert followup.audit_event.metadata["blocked_intent_count"] >= 1


def test_text_log_timestamp_parser_accepts_time_only_entries():
    from agent_runtime.mds_read_tools import _extract_log_timestamp

    assert _extract_log_timestamp("03:17:15.633 WARNING [api] API GET /x -> 401") == "03:17:15.633"
    assert _extract_log_timestamp("2026-05-27T03:17:15.633Z WARNING [api] API GET /x -> 401") == "2026-05-27T03:17:15.633Z"


def test_backend_log_summary_filters_routine_auth_polling_noise():
    from agent_runtime.mds_read_tools import _is_routine_auth_noise_event

    assert _is_routine_auth_noise_event(
        {
            "level": "WARNING",
            "message": "API GET /api/v1/commands/active -> 401 (0.001s)",
        }
    ) is True
    assert _is_routine_auth_noise_event(
        {
            "level": "WARNING",
            "message": "API GET /api/health -> 401 (0.001s)",
        }
    ) is True
    assert _is_routine_auth_noise_event(
        {
            "level": "WARNING",
            "message": "API GET / -> 401 (0.001s)",
        }
    ) is True
    assert _is_routine_auth_noise_event(
        {
            "level": "WARNING",
            "message": "API GET /api/v1/git/status -> 403 (0.001s)",
        }
    ) is True
    assert _is_routine_auth_noise_event(
        {
            "level": "WARNING",
            "message": "API POST /api/v1/simurgh/assistant/turns -> 401 (0.001s)",
        }
    ) is False
    assert _is_routine_auth_noise_event(
        {
            "level": "WARNING",
            "message": "API GET /api/v1/system/env/gcs -> 401 (0.001s)",
        }
    ) is False
    assert _is_routine_auth_noise_event(
        {
            "level": "ERROR",
            "message": "API GET /api/v1/commands/active -> 500 (0.001s)",
        }
    ) is False


def test_backend_log_summary_skips_stale_fallback_log_files(tmp_path):
    from agent_runtime.mds_read_tools import FALLBACK_LOG_STALE_GRACE_SECONDS, _include_fallback_log_file

    fallback = tmp_path / "mds-gcs.log"
    fallback.write_text("03:17:15 WARNING [api] stale\n", encoding="utf-8")
    fallback_mtime = 1_800_000_000.0
    os.utime(fallback, (fallback_mtime, fallback_mtime))

    assert _include_fallback_log_file(fallback, newest_session_mtime=None) is True
    assert _include_fallback_log_file(
        fallback,
        newest_session_mtime=fallback_mtime + FALLBACK_LOG_STALE_GRACE_SECONDS,
    ) is True
    assert _include_fallback_log_file(
        fallback,
        newest_session_mtime=fallback_mtime + FALLBACK_LOG_STALE_GRACE_SECONDS + 1,
    ) is False


def test_backend_log_summary_defaults_to_latest_session_files(tmp_path):
    from agent_runtime.mds_read_tools import _latest_session_log_candidates

    old_session = tmp_path / "s_old.jsonl"
    new_session = tmp_path / "s_new.jsonl"
    fallback = tmp_path / "mds-gcs.log"
    for path in (old_session, new_session, fallback):
        path.write_text("", encoding="utf-8")
    os.utime(old_session, (1_800_000_000.0, 1_800_000_000.0))
    os.utime(fallback, (1_800_000_050.0, 1_800_000_050.0))
    os.utime(new_session, (1_800_000_100.0, 1_800_000_100.0))

    assert _latest_session_log_candidates([old_session, new_session, fallback]) == [new_session]


def test_assistant_turn_routes_fleet_followup_from_session_context(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()
    deps = _fleet_summary_test_deps()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="How many drones do we have configured?",
        deps=deps,
    )

    assert first.turn.provider == "mds-tools"
    assert first.session.metadata["last_domain"] == "fleet"

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="and the scout IP?",
        deps=deps,
    )

    assert followup.turn.provider == "mds-tools"
    assert followup.audit_event.metadata["tool_intent"] == "fleet_summary"
    followup_content_lower = followup.turn.content.lower()
    assert "scout" in followup_content_lower
    assert (
        "i do not see a configured drone matching" in followup_content_lower
        or "scout drone from gcs configuration" in followup_content_lower
    )
    assert "private network details" not in followup.turn.content


def test_read_tools_route_boards_and_gps_followups_to_live_telemetry():
    from agent_runtime.mds_read_tools import answer_mds_read_only_question, classify_mds_read_intent

    now = time.time()
    deps = SimpleNamespace(
        load_config=lambda: [
            {
                "hw_id": 1,
                "pos_id": 1,
                "callsign": "SCOUT",
                "ip": "192.0.2.33",
                "mavlink_port": 14550,
            }
        ],
        get_all_drone_positions=lambda: [],
        load_swarm=lambda: [],
        get_all_heartbeats=lambda: {"1": {"timestamp": int(now * 1000), "ip": "192.0.2.33"}},
        telemetry_data_all_drones={
            "1": {
                "telemetry_available": True,
                "position_lat": 47.397742,
                "position_long": 8.545594,
                "relative_altitude_m": 8.4,
                "global_position_valid": True,
                "gps_fix_type": 3,
                "satellites_visible": 12,
                "timestamp": int(now * 1000),
            }
        },
        last_telemetry_time={"1": now},
        data_lock=None,
    )

    assert classify_mds_read_intent("what boards are connected now?") == "fleet_connectivity"
    assert classify_mds_read_intent("what drones are connected?") == "fleet_connectivity"
    assert classify_mds_read_intent("How many drones do we have configured? Are they all ready to fly") == "fleet_connectivity"
    assert (
        classify_mds_read_intent(
            "check if it was created and is ready to fly; report a preflight summary",
            conversation_topic="sitl",
        )
        == "fleet_connectivity"
    )
    assert (
        classify_mds_read_intent(
            "I do not have QGC now. Use the MDS telemetry you already have and check it yourself.",
            conversation_topic="logs",
        )
        == "fleet_connectivity"
    )

    answer = answer_mds_read_only_question(
        "what is their gps status and coordinate?",
        deps=deps,
        conversation_topic="fleet",
    )

    assert answer is not None
    assert answer.intent == "fleet_connectivity"
    assert "lat 47.3977420" in answer.content
    assert "47.3977420" in answer.content
    assert "8.4 m" in answer.content
    assert "Fleet status from GCS configuration" not in answer.content


def test_fleet_identity_matching_does_not_treat_domain_words_as_callsigns():
    from agent_runtime.mds_read_tools import answer_mds_read_only_question

    deps = SimpleNamespace(
        load_config=lambda: [
            {"hw_id": 1, "pos_id": 1, "callsign": "SITL-01"},
            {"hw_id": 2, "pos_id": 2, "callsign": "FIELD-02"},
        ],
        get_all_drone_positions=lambda: [],
        load_swarm=lambda: [],
    )

    compound = answer_mds_read_only_question(
        "How many drones are configured, and how many SITL instances are active?",
        deps=deps,
        intent_override="fleet_summary",
    )
    selected = answer_mds_read_only_question(
        "Show the configured drone SITL-01.",
        deps=deps,
        intent_override="fleet_summary",
    )

    assert compound is not None
    assert "2 configured drone(s)" in compound.content
    assert "configured drone matching" not in compound.content
    assert selected is not None
    assert "Sitl 01 drone from GCS configuration" in selected.content
    assert "Drone 2" not in selected.content


def test_compound_fleet_and_sitl_status_uses_both_runtime_sources():
    from agent_runtime.mds_read_tools import (
        answer_mds_read_only_question,
        build_mds_read_only_plan,
        classify_mds_read_intent,
    )

    service = SimpleNamespace(
        list_instances=lambda: {
            "instances": [
                {
                    "name": "drone-1",
                    "state": "running",
                    "image_ref": "mavsdk-drone-show-sitl:latest",
                }
            ],
            "total_instances": 1,
            "running_instance_count": 1,
            "docker": {"daemon_reachable": True},
        },
        build_policy=lambda: {"sim_mode": True, "read_only": False},
    )
    deps = SimpleNamespace(
        load_config=lambda: [
            {"hw_id": index, "callsign": f"DRONE-{index}"}
            for index in range(1, 5)
        ],
        sitl_control_service=service,
    )
    prompt = "How many drones do we have configured? How many SITL instances are active?"

    answer = answer_mds_read_only_question(prompt, deps=deps)
    plan = build_mds_read_only_plan(prompt)

    assert classify_mds_read_intent(prompt) == "fleet_sitl_summary"
    assert plan.intent == "fleet_sitl_summary"
    assert {
        "mds.config.fleet.read",
        "mds.sitl.instances.read",
        "mds.sitl.policy.read",
    }.issubset(plan.tool_ids)
    assert answer is not None
    assert answer.intent == "fleet_sitl_summary"
    assert "Configured drones: 4." in answer.content
    assert "SITL instances: 1 total, 1 active; Docker reachable: Yes." in answer.content
    assert "Active: drone-1 running" in answer.content
    assert "Simurgh runtime posture" not in answer.content
    assert "No action was executed" not in answer.content
    assert "No drone command was sent" not in answer.content


def test_read_tools_answer_sitl_status_from_local_control_service():
    from agent_runtime.mds_read_tools import answer_mds_read_only_question

    service = SimpleNamespace(
        list_instances=lambda: {
            "instances": [
                {
                    "name": "drone-1",
                    "state": "running",
                    "status": "running",
                    "image_ref": "mavsdk-drone-show-sitl:latest",
                    "git_sync_enabled": False,
                    "requirements_sync_enabled": False,
                }
            ],
            "total_instances": 1,
            "running_instance_count": 1,
            "docker": {"daemon_reachable": True},
        },
        build_policy=lambda: {
            "sim_mode": True,
            "read_only": False,
            "docker": {"daemon_reachable": True},
        },
    )

    answer = answer_mds_read_only_question(
        "Is the SITL container healthy?",
        deps=SimpleNamespace(sitl_control_service=service),
        intent_override="sitl_status",
    )

    assert answer is not None
    assert answer.intent == "sitl_status"
    assert "SITL instances: 1 total, 1 active; Docker reachable: Yes." in answer.content
    assert "drone-1" in answer.content
    assert "git off, requirements off" in answer.content
    assert "sim_mode=True, read_only=False" in answer.content
    assert "No SITL or drone action was executed" not in answer.content


def test_read_tools_answer_fleet_battery_arming_and_mode_from_live_telemetry():
    from agent_runtime.mds_read_tools import answer_mds_read_only_question, classify_mds_read_intent

    now = time.time()
    deps = SimpleNamespace(
        load_config=lambda: [
            {
                "hw_id": 1,
                "pos_id": 1,
                "callsign": "SCOUT",
                "ip": "192.0.2.33",
                "mavlink_port": 14550,
            }
        ],
        get_all_drone_positions=lambda: [],
        load_swarm=lambda: [],
        get_all_heartbeats=lambda: {"1": {"timestamp": int(now * 1000), "ip": "192.0.2.33"}},
        telemetry_data_all_drones={
            "1": {
                "telemetry_available": True,
                "position_lat": 47.397742,
                "position_long": 8.545594,
                "relative_altitude_m": 8.4,
                "global_position_valid": True,
                "gps_fix_type": 3,
                "satellites_visible": 12,
                "battery_voltage": 12.4,
                "is_armed": False,
                "is_ready_to_arm": True,
                "state": 0,
                "mission": 0,
                "flight_mode": 65536,
                "system_status": 4,
                "velocity_down": 0.0,
                "timestamp": int(now * 1000),
            }
        },
        last_telemetry_time={"1": now},
        data_lock=None,
    )

    assert classify_mds_read_intent("what is their battery, arm state, mode and gps health?") == "fleet_connectivity"

    answer = answer_mds_read_only_question(
        "what is their battery, arm state, mode and gps health?",
        deps=deps,
        conversation_topic="fleet",
    )

    assert answer is not None
    assert answer.intent == "fleet_connectivity"
    assert "Battery" in answer.content
    assert "12.40 V" in answer.content
    assert "Ready" in answer.content
    assert "MDS preflight verdict: Drone 1 is live and reports ready." in answer.content
    assert "On ground (inferred)" in answer.content
    assert "not a readiness-to-fly decision" not in answer.content
    assert "65536" in answer.content
    assert "fix 3, 12 sats" in answer.content
    assert "Fleet status from GCS configuration" not in answer.content

    combined = answer_mds_read_only_question(
        "what is their location, altitude, battery and arm state?",
        deps=deps,
        conversation_topic="fleet",
    )

    assert combined is not None
    assert combined.intent == "fleet_connectivity"
    assert "Position" in combined.content
    assert "lat 47.3977420" in combined.content
    assert "alt 8.4 m REL" in combined.content
    assert "Flight state" in combined.content
    assert "Final state" not in combined.content
    assert "12.40 V" in combined.content
    assert "Fleet status from GCS configuration" not in combined.content


def test_read_tools_answer_quickscout_status_from_mission_catalog():
    from agent_runtime.mds_read_tools import answer_mds_read_only_question, classify_mds_read_intent

    now = 1_780_360_000.0
    deps = SimpleNamespace(
        get_quickscout_mission_catalog=lambda limit=5: {
            "count": 1,
            "missions": [
                {
                    "mission_id": "qs_20260602_alpha",
                    "mission_label": "Damavand ridge search",
                    "mission_template": "area_sweep",
                    "state": "planned",
                    "updated_at": now,
                    "drone_count": 2,
                    "pos_ids": [1, 2],
                    "total_area_sq_m": 125_000.0,
                    "estimated_coverage_time_s": 720.0,
                    "return_behavior": "return_home",
                    "total_coverage_percent": 0.0,
                    "finding_count": 1,
                    "position_source_mode": "configured_origin",
                    "launchable": True,
                    "requires_revalidation": True,
                }
            ],
        },
        get_quickscout_mission_status=lambda mission_id: {
            "mission_id": mission_id,
            "state": "planned",
            "operation_phase": "launch_review",
            "total_coverage_percent": 12.5,
            "status_summary": "Mission package is staged for launch review.",
            "recommended_operator_action": "Revalidate live GPS positions before launch.",
            "findings": [{"id": "finding_1", "summary": "thermal anomaly"}],
            "drone_states": {
                "1": {
                    "state": "surveying",
                    "coverage_percent": 18.0,
                    "distance_covered_m": 340.0,
                    "estimated_remaining_s": 420.0,
                    "status_note": "on first lane",
                },
            },
        },
        get_quickscout_mission_workspace=lambda mission_id: {},
    )

    assert classify_mds_read_intent("is there any QuickScout mission ready for field test?") == "sar_summary"

    answer = answer_mds_read_only_question(
        "is there any QuickScout mission ready for field test?",
        deps=deps,
    )

    assert answer is not None
    assert answer.intent == "sar_summary"
    assert "QuickScout/SAR mission status from current GCS evidence" in answer.content
    assert "Damavand ridge search" in answer.content
    assert "live launch revalidation required" in answer.content
    assert "Mission package is staged for launch review" in answer.content
    assert "Revalidate live GPS positions before launch" in answer.content
    assert "Per-drone mission progress" in answer.content
    assert "thermal anomaly" not in answer.content
    assert "No mission, configuration, or drone action was executed" in answer.content


def test_read_tools_answer_quickscout_flags_stale_implausible_package():
    from agent_runtime.mds_read_tools import answer_mds_read_only_question

    deps = SimpleNamespace(
        get_quickscout_mission_catalog=lambda limit=5: {
            "count": 1,
            "missions": [
                {
                    "mission_id": "qs_old_bounds",
                    "state": "ready",
                    "updated_at": 1_715_663_280.0,
                    "drone_count": 1,
                    "pos_ids": [2],
                    "total_area_sq_m": 151_273_180_000.0,
                    "estimated_coverage_time_s": 361_399_161.0,
                    "launchable": True,
                    "requires_revalidation": False,
                }
            ],
        },
        get_quickscout_mission_status=lambda mission_id: {
            "mission_id": mission_id,
            "state": "ready",
            "operation_phase": "ready_to_launch",
            "status_summary": "Package is computed and ready for launch review.",
            "drone_states": {},
        },
        get_quickscout_mission_workspace=lambda mission_id: {},
    )

    answer = answer_mds_read_only_question("is the QuickScout mission ready for field test?", deps=deps)

    assert answer is not None
    assert answer.intent == "sar_summary"
    assert "not field-ready until stale/implausible mission evidence is reviewed" in answer.content
    assert "Readiness cautions" in answer.content
    assert "stale for field launch readiness" in answer.content
    assert "check bounds/origin" in answer.content
    assert "check planner inputs" in answer.content
    assert "No mission, configuration, or drone action was executed" in answer.content


def test_read_tools_answer_no_quickscout_mission_without_raw_registry_dump():
    from agent_runtime.mds_read_tools import answer_mds_read_only_question

    deps = SimpleNamespace(get_quickscout_mission_catalog=lambda limit=5: {"count": 0, "missions": []})

    answer = answer_mds_read_only_question("check QuickScout mission status", deps=deps)

    assert answer is not None
    assert answer.intent == "sar_summary"
    assert "do not see any persisted QuickScout mission package" in answer.content
    assert "Use [QuickScout](/quickscout)" in answer.content
    assert "Registry-backed read-only capability summary" not in answer.content
    assert "mds.sar.mission.status.read" not in answer.content


def test_read_only_plan_exposes_sanitized_fleet_telemetry_selection():
    from agent_runtime.mds_read_tools import build_mds_read_only_plan

    plan = build_mds_read_only_plan(
        "what is their location, altitude, battery and arm state?",
        conversation_topic="fleet",
    )
    metadata = plan.public_metadata()

    assert metadata["intent"] == "fleet_connectivity"
    assert metadata["response_mode"] == "status"
    assert metadata["topic"] == "fleet"
    assert metadata["execution_layer"] == "local_advisory"
    assert "mds.fleet.telemetry.read" in metadata["tool_ids"]
    assert "message" not in metadata
    assert "normalized_message" not in metadata
    assert "no action" in metadata["safety_posture"]


def test_read_only_plan_covers_logs_and_docs_workflows():
    from agent_runtime.mds_read_tools import build_mds_read_only_plan

    logs = build_mds_read_only_plan("check latest backend warnings in the logs")
    assert logs.intent == "backend_log_summary"
    assert logs.topic == "logs"
    assert logs.public_metadata()["tool_ids"] == ["mds.logs.sessions.read", "mds.logs.sources.read"]

    drone_logs = build_mds_read_only_plan("how many drone logs do we have and was there any errors logged?")
    assert drone_logs.intent == "drone_log_summary"
    assert "mds.logs.drone_sessions.read" in drone_logs.public_metadata()["tool_ids"]
    assert "mds.logs.drone_ulog_files.read" in drone_logs.public_metadata()["tool_ids"]

    mission_evidence = build_mds_read_only_plan(
        "Review this completed mission using the command tracker, unified MDS logs, and the newest onboard ULog."
    )
    assert mission_evidence.intent == "drone_log_summary"

    docs = build_mds_read_only_plan("can you give me link to read about creating SITL demo?")
    assert docs.intent == "sitl_help"
    assert docs.response_mode == "workflow"
    assert docs.topic == "sitl"
    assert "mds.docs.search" in docs.public_metadata()["tool_ids"]


def test_read_tools_answer_drone_log_summary_from_drone_and_ulog_metadata(monkeypatch):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools, answer_mds_read_only_question, build_mds_read_only_plan

    deps = SimpleNamespace(
        load_config=lambda: [
            {
                "hw_id": 1,
                "pos_id": 1,
                "callsign": "SCOUT",
                "ip": "192.0.2.33",
                "mavlink_port": 14550,
            }
        ],
    )

    def fake_fetch(self, drone_ip, path, *, params=None, timeout=0):  # noqa: ANN001
        assert drone_ip == "192.0.2.33"
        if path == "/api/logs/sessions":
            return {"sessions": [{"session_id": "s_drone_1", "size_bytes": 1234, "modified": 1780000000.0}]}, ""
        if path == "/api/logs/sessions/s_drone_1":
            return {
                "session_id": "s_drone_1",
                "count": 3,
                "lines": [
                    {"level": "INFO", "message": "boot ok"},
                    {
                        "ts": "2026-06-05T10:00:10Z",
                        "level": "ERROR",
                        "component": "flight",
                        "message": "example warning-worthy line token=private-value",
                    },
                    {
                        "ts": "2026-06-05T10:00:11Z",
                        "level": "DEBUG",
                        "component": "mavsdk",
                        "message": "MAVSDK: [10:00:11|Warn ] duplicate acknowledgement ignored",
                    },
                ],
            }, ""
        if path == "/api/v1/ulog/files":
            return {
                "hw_id": "1",
                "count": 2,
                "files": [{"id": 9, "date_utc": "2026-06-05T10:00:00Z", "size_bytes": 2048}],
            }, ""
        if path == "/api/v1/ulog/files/9/summary":
            return {
                "parsed": True,
                "staged_job_deleted": True,
                "duration_sec": 42.5,
                "parser": {"status": "ok"},
                "dropouts": {"count": 2, "total_duration_sec": 0.25, "max_duration_ms": 150.0},
                "logged_messages": {
                    "count": 3,
                    "levels": {"3": 1, "4": 2},
                    "raw_text_included": False,
                    "messages": ["private raw message must never render"],
                },
                "system": {"sys_name": "PX4", "ver_hw": "FMUv6X"},
                "local_position": {
                    "max_horizontal_distance_from_start_m": 10.2,
                    "relative_altitude_range_m": {"min": 0.0, "max": 10.0, "final": 0.1},
                    "final_relative_position_m": {"north": 0.4, "east": -0.2, "up": 0.1},
                },
                "battery": {"voltage_v": {"min": 15.9, "max": 16.2, "final": 16.0}},
                "vehicle_status": {"failsafe": {"0": 120, "1": 2}},
                "land_detected": {
                    "landed": {"0": 80, "1": 40},
                    "ground_contact": {"0": 75, "1": 45},
                    "freefall": {"0": 120},
                },
                "commands": {
                    "vehicle_command": {"samples": 3, "command_counts": {"22": 1, "176": 2}},
                    "vehicle_command_ack": {
                        "samples": 4,
                        "command_counts": {"22": 1, "176": 2},
                        "result_counts": {"0": 3, "5": 1},
                    },
                },
            }, ""
        raise AssertionError(f"unexpected drone log path: {path}")

    monkeypatch.setattr(MdsReadOnlyTools, "_fetch_drone_json", fake_fetch)

    plan = build_mds_read_only_plan(
        "how about the drones? how many drone logs and what was the flight time and was there any errors logged?"
    )
    answer = answer_mds_read_only_question(
        "how about the drones? how many drone logs and what was the flight time and was there any errors logged?",
        deps=deps,
    )

    assert plan.intent == "drone_log_summary"
    assert answer is not None
    assert answer.intent == "drone_log_summary"
    assert "Drone log evidence" in answer.content
    assert (
        "Verdict: review required - 2 ULog dropout(s); "
        "2 ULog failsafe-active sample(s)."
    ) in answer.content
    assert "Drone 1" in answer.content
    assert "2.0 KB" in answer.content
    assert "2 in latest session" in answer.content
    assert "Latest drone-log warning/error samples" in answer.content
    assert "2026-06-05T10:00:10Z | ERROR | flight" in answer.content
    assert "token=[redacted]" in answer.content
    assert "duplicate acknowledgement ignored" in answer.content
    assert "private-value" not in answer.content
    assert "Parsed latest ULog summary" in answer.content
    assert "42.5s" in answer.content
    assert "max horizontal 10.2m" in answer.content
    assert "dropouts 2 (total 0.250s, max 150.0ms)" in answer.content
    assert "logged messages 3 (levels 3:1, 4:2; raw text excluded)" in answer.content
    assert "system PX4; hardware FMUv6X" in answer.content
    assert "failsafe counts 0:120, 1:2" in answer.content
    assert "land detection landed[0:80, 1:40]" in answer.content
    assert "final displacement N +0.4m, E -0.2m, U +0.1m" in answer.content
    assert "command ids 176:2, 22:1" in answer.content
    assert "ack results 0:3, 5:1" in answer.content
    assert "non-accepted command acknowledgement" not in answer.content
    assert "unverified; newest available ULog may belong to another flight" in answer.content
    assert "private raw message must never render" not in answer.content
    assert "Backend warning/error" not in answer.content
    assert "mds.logs.drone_ulog_summary.read" in answer.tool_ids
    assert "mds.logs.drone_ulog_files.read" in answer.tool_ids

    brief_answer = answer_mds_read_only_question(
        "Briefly check the newest drone ULog and tell me whether anything went wrong.",
        deps=deps,
        response_detail="brief",
    )
    assert brief_answer is not None
    assert brief_answer.content.startswith("Flight evidence summary:")
    assert (
        "Verdict: review required - 2 ULog dropout(s); "
        "2 ULog failsafe-active sample(s)."
    ) in brief_answer.content
    assert "Drone 1: 1 log session(s); 1 ULog(s)" in brief_answer.content
    assert "Latest drone-log warning/error samples" in brief_answer.content
    assert "token=[redacted]" in brief_answer.content
    assert "Drone 1 ULog 9: 42.5s" in brief_answer.content
    assert "Safety: dropouts 2" in brief_answer.content
    assert "private raw message must never render" not in brief_answer.content
    assert "Parsed latest ULog summary" not in brief_answer.content
    assert "Evidence coverage:" not in brief_answer.content
    assert "API refs:" not in brief_answer.content


def test_drone_log_depth_uses_structured_options_before_lexical_fallback(
    monkeypatch,
):
    from agent_runtime.mds_read_tools import (
        MdsReadOnlyTools,
        answer_mds_read_only_question,
    )

    deps = SimpleNamespace(
        load_config=lambda: [{"hw_id": 1, "ip": "192.0.2.31"}],
        get_command_tracker=lambda: _PublicCommandTrackerStub(
            recent=(
                {
                    "command_id": "cmd-1",
                    "mission_name": "TAKE_OFF",
                    "phase": "terminal",
                    "status": "completed",
                    "outcome": "success",
                    "target_drones": [1],
                },
            ),
            stats={
                "total_commands": 1,
                "successful_commands": 1,
                "failed_commands": 0,
                "partial_commands": 0,
            },
        ),
    )
    requested_paths: list[str] = []

    def fake_fetch(self, drone_ip, path, *, params=None, timeout=0):  # noqa: ANN001
        del self, drone_ip, params, timeout
        requested_paths.append(path)
        if path == "/api/logs/sessions":
            return {"sessions": []}, ""
        if path == "/api/v1/ulog/files":
            return {
                "files": [
                    {
                        "id": 7,
                        "date_utc": "2026-06-20T22:01:00Z",
                        "size_bytes": 1024,
                    }
                ]
            }, ""
        if path == "/api/v1/ulog/files/7/summary":
            return {
                "parsed": True,
                "parser": {"status": "ok"},
                "duration_sec": 12.0,
                "staged_job_deleted": True,
            }, ""
        raise AssertionError(path)

    monkeypatch.setattr(MdsReadOnlyTools, "_fetch_drone_json", fake_fetch)
    monkeypatch.setattr(
        MdsReadOnlyTools,
        "_recent_warning_events",
        lambda self, **_kwargs: ([], ["unified-test"]),
    )

    lexical_words_but_shallow = answer_mds_read_only_question(
        "Analyze the mission and newest ULog and verify what happened.",
        deps=deps,
        intent_override="drone_log_summary",
        read_options={
            "drone_log_summary": {
                "verify_operation": False,
                "include_unified_logs": False,
                "analyze_latest_ulog": False,
            }
        },
    )
    assert lexical_words_but_shallow is not None
    assert "/api/v1/ulog/files/7/summary" not in requested_paths
    assert "Recent command tracker evidence" not in lexical_words_but_shallow.content
    assert "Unified GCS log evidence" not in lexical_words_but_shallow.content

    requested_paths.clear()
    semantic_only_deep = answer_mds_read_only_question(
        "پرواز انجام‌شده را با شواهد موجود بررسی کن",
        deps=deps,
        intent_override="drone_log_summary",
        read_options={
            "drone_log_summary": {
                "verify_operation": True,
                "include_unified_logs": True,
                "analyze_latest_ulog": True,
            }
        },
    )
    assert semantic_only_deep is not None
    assert "/api/v1/ulog/files/7/summary" in requested_paths
    assert "Recent command tracker evidence" in semantic_only_deep.content
    assert "Unified GCS log evidence" in semantic_only_deep.content
    assert "Parsed latest ULog summary" in semantic_only_deep.content


def test_drone_log_fanout_is_concurrent_and_keeps_fleet_order(monkeypatch):
    from agent_runtime.mds_read_tools import (
        MdsReadOnlyTools,
        answer_mds_read_only_question,
    )

    monkeypatch.setenv("MDS_SIMURGH_DRONE_LOG_MAX_WORKERS", "3")
    barrier = threading.Barrier(3, timeout=1.0)
    deps = SimpleNamespace(
        load_config=lambda: [
            {"hw_id": 3, "ip": "192.0.2.33"},
            {"hw_id": 1, "ip": "192.0.2.31"},
            {"hw_id": 2, "ip": "192.0.2.32"},
        ],
    )

    def fake_fetch(self, drone_ip, path, *, params=None, timeout=0):  # noqa: ANN001
        del self, drone_ip, params, timeout
        if path == "/api/logs/sessions":
            barrier.wait()
            return {"sessions": []}, ""
        if path == "/api/v1/ulog/files":
            return {"files": []}, ""
        raise AssertionError(path)

    monkeypatch.setattr(MdsReadOnlyTools, "_fetch_drone_json", fake_fetch)
    answer = answer_mds_read_only_question(
        "flight evidence",
        deps=deps,
        intent_override="drone_log_summary",
        read_options={
            "drone_log_summary": {
                "verify_operation": False,
                "include_unified_logs": False,
                "analyze_latest_ulog": False,
            }
        },
    )

    assert answer is not None
    assert answer.content.index("Drone 3") < answer.content.index("Drone 1")
    assert answer.content.index("Drone 1") < answer.content.index("Drone 2")
    assert "session inventory 3/3" in answer.content


def test_drone_log_fanout_honors_global_evidence_deadline(monkeypatch):
    from agent_runtime.mds_read_tools import (
        MdsReadOnlyTools,
        answer_mds_read_only_question,
    )

    monkeypatch.setenv("MDS_SIMURGH_DRONE_LOG_EVIDENCE_DEADLINE_SEC", "0.05")
    monkeypatch.setenv("MDS_SIMURGH_DRONE_LOG_MAX_WORKERS", "2")
    deps = SimpleNamespace(
        load_config=lambda: [
            {"hw_id": 1, "ip": "192.0.2.31"},
            {"hw_id": 2, "ip": "192.0.2.32"},
        ],
    )

    def slow_fetch(self, drone_ip, path, *, params=None, timeout=0):  # noqa: ANN001
        del self, drone_ip, params, timeout
        if path == "/api/logs/sessions":
            return {"sessions": []}, ""
        time.sleep(0.25)
        return {}, ""

    monkeypatch.setattr(MdsReadOnlyTools, "_fetch_drone_json", slow_fetch)
    started = time.monotonic()
    answer = answer_mds_read_only_question(
        "flight evidence",
        deps=deps,
        intent_override="drone_log_summary",
        read_options={
            "drone_log_summary": {
                "verify_operation": False,
                "include_unified_logs": False,
                "analyze_latest_ulog": False,
            }
        },
    )
    elapsed = time.monotonic() - started

    assert answer is not None
    assert elapsed < 0.2
    assert "global evidence deadline exceeded" in answer.content
    assert "session inventory 2/2" in answer.content
    assert "ULog inventory 0/2" in answer.content


def test_read_tools_answer_operation_log_check_with_command_and_ulog_evidence(monkeypatch):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools, answer_mds_read_only_question

    deps = SimpleNamespace(
        load_config=lambda: [
            {
                "hw_id": 1,
                "pos_id": 1,
                "callsign": "SCOUT",
                "ip": "192.0.2.33",
                "mavlink_port": 14550,
            }
        ],
        get_command_tracker=lambda: _PublicCommandTrackerStub(
            stats={
                "total_commands": 3,
                "successful_commands": 3,
                "failed_commands": 0,
                "partial_commands": 0,
            },
            recent=(
                {
                    "command_id": "cmd-takeoff",
                    "mission_name": "TAKE_OFF",
                    "phase": "terminal",
                    "status": "completed",
                    "outcome": "success",
                    "target_drones": [1],
                    "created_at": None,
                    "updated_at": None,
                },
                {
                    "command_id": "cmd-move",
                    "mission_name": "PRECISION_MOVE",
                    "phase": "terminal",
                    "status": "completed",
                    "outcome": "success",
                    "target_drones": [1],
                    "created_at": None,
                    "updated_at": None,
                },
            ),
        ),
    )

    def fake_fetch(self, drone_ip, path, *, params=None, timeout=0):  # noqa: ANN001
        assert drone_ip == "192.0.2.33"
        if path == "/api/logs/sessions":
            return {"sessions": [{"session_id": "s_drone_1", "size_bytes": 1234, "modified": 1780000000.0}]}, ""
        if path == "/api/logs/sessions/s_drone_1":
            return {"session_id": "s_drone_1", "lines": [{"level": "INFO", "message": "ok"}]}, ""
        if path == "/api/v1/ulog/files":
            return {"files": [{"id": 7, "date_utc": "2026-06-20T22:01:00Z", "size_bytes": 4096}]}, ""
        if path == "/api/v1/ulog/files/7/summary":
            return {
                "parsed": True,
                "staged_job_deleted": True,
                "duration_sec": 25.0,
                "parser": {"status": "ok"},
                "local_position": {
                    "max_horizontal_distance_from_start_m": 9.8,
                    "relative_altitude_range_m": {"min": 0.0, "max": 10.1, "final": 0.0},
                },
                "battery": {"voltage_v": {"min": 16.0, "max": 16.2, "final": 16.1}},
                "commands": {
                    "vehicle_command": {"samples": 3},
                    "vehicle_command_ack": {"samples": 3, "result_counts": {"0": 3}},
                },
            }, ""
        raise AssertionError(f"unexpected drone log path: {path}")

    monkeypatch.setattr(MdsReadOnlyTools, "_fetch_drone_json", fake_fetch)

    answer = answer_mds_read_only_question(
        "Check the logs and see if all happened was correct or not. Also do we have a ulog stored?",
        deps=deps,
    )

    assert answer is not None
    assert answer.intent == "drone_log_summary"
    assert "Recent command tracker evidence" in answer.content
    assert "Unified GCS log evidence" in answer.content
    assert "TAKE_OFF" in answer.content
    assert "PRECISION_MOVE" in answer.content
    assert "Drone log evidence" in answer.content
    assert "Drone 1" in answer.content
    assert "4.0 KB" in answer.content
    assert "Parsed latest ULog summary" in answer.content
    assert "25.0s" in answer.content
    assert "acks 3" in answer.content
    assert "Evidence correlation: latest sessions and newest ULogs are selected by recency" in answer.content
    assert "unverified; newest available ULog may belong to another flight" in answer.content
    assert "mds.commands.recent.read" in answer.tool_ids
    assert "mds.logs.sessions.read" in answer.tool_ids


def test_drone_log_summary_reports_unavailable_sources_as_unknown(monkeypatch):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools, answer_mds_read_only_question

    deps = SimpleNamespace(
        load_config=lambda: [
            {"hw_id": 1, "ip": "192.0.2.31"},
            {"hw_id": 2, "ip": "192.0.2.32"},
        ],
    )

    def fake_fetch(self, drone_ip, path, *, params=None, timeout=0):  # noqa: ANN001
        if drone_ip == "192.0.2.31":
            return {}, "timed out"
        if path == "/api/logs/sessions":
            return {"sessions": []}, ""
        if path == "/api/v1/ulog/files":
            return {"files": []}, ""
        raise AssertionError(path)

    monkeypatch.setattr(MdsReadOnlyTools, "_fetch_drone_json", fake_fetch)

    answer = answer_mds_read_only_question(
        "Analyze the drone logs and ULogs and report the evidence coverage.",
        deps=deps,
    )

    assert answer is not None
    assert "session inventory 1/2" in answer.content
    assert "ULog inventory 1/2" in answer.content
    assert "drone log sessions 0 in available sources (1/2 sources available; total unknown)" in answer.content
    assert "onboard ULogs 0 in available sources (1/2 sources available; total unknown)" in answer.content
    assert "No ULog is listed by the available inventories; unavailable inventories remain unknown." in answer.content
    assert "No onboard ULog file is listed in the complete checked scope" not in answer.content

    monkeypatch.setattr(
        MdsReadOnlyTools,
        "_recent_warning_events",
        lambda self, *, window_seconds=None, started_at_ms=None, ended_at_ms=None, completed_at_ms=None: (
            [],
            ["test-log"],
        ),
    )
    brief_answer = answer_mds_read_only_question(
        "Briefly verify whether the latest flight logs and ULog show a problem.",
        deps=deps,
        response_detail="brief",
    )
    assert brief_answer is not None
    assert "Verdict: no failure is shown in the available evidence" in brief_answer.content
    assert (
        "no onboard ULog listed by available inventories; remaining sources unknown"
        in brief_answer.content
    )
    assert "Evidence gaps:" in brief_answer.content


def test_drone_log_summary_exposes_ulog_parse_cap_and_partial_coverage(monkeypatch):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools, answer_mds_read_only_question

    monkeypatch.setenv("MDS_SIMURGH_ULOG_SUMMARY_MAX_DRONES", "2")
    deps = SimpleNamespace(
        load_config=lambda: [
            {"hw_id": 1, "ip": "192.0.2.31"},
            {"hw_id": 2, "ip": "192.0.2.32"},
            {"hw_id": 3, "ip": "192.0.2.33"},
        ],
    )

    def fake_fetch(self, drone_ip, path, *, params=None, timeout=0):  # noqa: ANN001
        drone_id = int(drone_ip.rsplit(".", 1)[-1]) - 30
        if path == "/api/logs/sessions":
            return {"sessions": []}, ""
        if path == "/api/v1/ulog/files":
            return {
                "files": [
                    {
                        "id": drone_id,
                        "date_utc": "2026-06-20T22:01:00Z",
                        "size_bytes": 1024,
                    }
                ]
            }, ""
        if path == f"/api/v1/ulog/files/{drone_id}/summary":
            return {
                "parsed": True,
                "parser": {"status": "ok"},
                "duration_sec": 10.0,
                "staged_job_deleted": True,
            }, ""
        raise AssertionError(path)

    monkeypatch.setattr(MdsReadOnlyTools, "_fetch_drone_json", fake_fetch)

    answer = answer_mds_read_only_question("Analyze all drone ULogs and report a summary.", deps=deps)

    assert answer is not None
    assert "ULog summary coverage: 2/3 known eligible drone(s) parsed successfully; 2 attempted; cap 2." in answer.content
    assert "1 eligible newest ULog(s) were left metadata-only by the parse cap." in answer.content


def test_drone_log_summary_does_not_count_unparsed_http_success(monkeypatch):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools, answer_mds_read_only_question

    deps = SimpleNamespace(
        load_config=lambda: [{"hw_id": 1, "ip": "192.0.2.31"}],
    )

    def fake_fetch(self, drone_ip, path, *, params=None, timeout=0):  # noqa: ANN001
        if path == "/api/logs/sessions":
            return {"sessions": []}, ""
        if path == "/api/v1/ulog/files":
            return {
                "files": [
                    {
                        "id": 1,
                        "date_utc": "2026-06-20T22:01:00Z",
                        "size_bytes": 1024,
                    }
                ]
            }, ""
        if path == "/api/v1/ulog/files/1/summary":
            return {
                "parsed": False,
                "parser": {
                    "available": False,
                    "status": "unavailable",
                    "error": "pyulog unavailable",
                },
                "staged_job_deleted": True,
            }, ""
        raise AssertionError(path)

    monkeypatch.setattr(MdsReadOnlyTools, "_fetch_drone_json", fake_fetch)

    answer = answer_mds_read_only_question("Analyze the newest drone ULog.", deps=deps)

    assert answer is not None
    assert "not parsed" in answer.content
    assert "pyulog unavailable" in answer.content
    assert "ULog summary coverage: 0/1 known eligible drone(s) parsed successfully; 1 attempted; cap 2." in answer.content


def test_drone_log_summary_requires_explicit_correlation_evidence_and_reports_cleanup_failure(monkeypatch):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools, answer_mds_read_only_question

    tracker = _PublicCommandTrackerStub(
        recent=(),
        stats={"total_commands": 0},
    )
    deps = SimpleNamespace(
        load_config=lambda: [{"hw_id": 1, "ip": "192.0.2.31"}],
        get_command_tracker=lambda: tracker,
    )

    def fake_fetch(self, drone_ip, path, *, params=None, timeout=0):  # noqa: ANN001
        if path == "/api/logs/sessions":
            return {"sessions": []}, ""
        if path == "/api/v1/ulog/files":
            return {
                "files": [{"id": 5, "date_utc": "2026-06-20T22:01:00Z", "size_bytes": 1024}]
            }, ""
        if path == "/api/v1/ulog/files/5/summary":
            return {
                "parsed": True,
                "parser": {"status": "ok"},
                "duration_sec": 20.0,
                "staged_job_deleted": False,
                "correlation": {
                    "status": "verified",
                    "verified": True,
                    "method": "gcs_target_time_action_command_overlap",
                    "evidence": {"command_ids": ["spoofed"]},
                },
            }, ""
        raise AssertionError(path)

    monkeypatch.setattr(MdsReadOnlyTools, "_fetch_drone_json", fake_fetch)

    answer = answer_mds_read_only_question(
        "Verify this mission using the command tracker, unified logs, and the newest ULog.",
        deps=deps,
    )

    assert answer is not None
    assert "correlation unverified; newest available ULog may belong to another flight" in answer.content
    assert "STAGED DOWNLOAD CLEANUP FAILED" in answer.content
    assert "Staged ULog cleanup failures" in answer.content
    assert "staged download cleanup failed" in answer.content
    assert tracker.calls == ["recent", "active", "statistics"]


def test_drone_log_summary_verifies_correlation_only_with_target_time_action_and_command(monkeypatch):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools, answer_mds_read_only_question

    started = datetime(2026, 6, 20, 22, 1, tzinfo=timezone.utc)
    started_ms = int(started.timestamp() * 1000)
    tracker = _PublicCommandTrackerStub(
        recent=(
            {
                "command_id": "cmd-takeoff-1",
                "mission_name": "TAKE_OFF",
                "target_drones": ["1"],
                "phase": "terminal",
                "status": "completed",
                "outcome": "success",
                "created_at": started_ms + 2_000,
                "execution_started_at": started_ms + 5_000,
                "completed_at": started_ms + 15_000,
                "updated_at": started_ms + 15_000,
                "params": {"operator_label": "simurgh:act-a1b2c3d4:take_off"},
            },
            {
                "command_id": "cmd-move-1",
                "mission_name": "PRECISION_MOVE",
                "target_drones": ["1"],
                "phase": "terminal",
                "status": "completed",
                "outcome": "success",
                "created_at": started_ms + 20_000,
                "execution_started_at": started_ms + 22_000,
                "completed_at": started_ms + 30_000,
                "updated_at": started_ms + 30_000,
                "params": {"operator_label": "simurgh:act-a1b2c3d4:step:2"},
            },
            {
                "command_id": "cmd-rtl-1",
                "mission_name": "RETURN_RTL",
                "target_drones": ["1"],
                "phase": "terminal",
                "status": "completed",
                "outcome": "success",
                "created_at": started_ms + 35_000,
                "execution_started_at": started_ms + 37_000,
                "completed_at": started_ms + 45_000,
                "updated_at": started_ms + 45_000,
                "params": {"operator_label": "simurgh:act-a1b2c3d4:step:3"},
            },
        ),
        stats={"total_commands": 3, "successful_commands": 3},
    )
    deps = SimpleNamespace(
        load_config=lambda: [{"hw_id": 1, "ip": "192.0.2.31"}],
        get_command_tracker=lambda: tracker,
    )

    def fake_fetch(self, drone_ip, path, *, params=None, timeout=0):  # noqa: ANN001
        if path == "/api/logs/sessions":
            return {"sessions": []}, ""
        if path == "/api/v1/ulog/files":
            return {
                "files": [{"id": 7, "date_utc": "2026-06-20T22:01:00Z", "size_bytes": 2048}]
            }, ""
        if path == "/api/v1/ulog/files/7/summary":
            return {
                "parsed": True,
                "parser": {"status": "ok"},
                "duration_sec": 60.0,
                "staged_job_deleted": True,
            }, ""
        raise AssertionError(path)

    monkeypatch.setattr(MdsReadOnlyTools, "_fetch_drone_json", fake_fetch)

    answer = answer_mds_read_only_question(
        "Verify this completed mission from the command tracker, unified logs, and newest ULog.",
        deps=deps,
    )

    assert answer is not None
    assert "correlation verified for act-a1b2c3d4" in answer.content
    assert "3 GCS command id(s)" in answer.content
    assert "association only, not mission-success proof" in answer.content
    assert tracker.calls == ["recent", "active", "statistics"]

    tracker.calls.clear()
    semantic_answer = answer_mds_read_only_question(
        "Verify this completed mission from the command tracker, unified logs, and newest ULog.",
        deps=deps,
        intent_override="drone_log_summary",
        target_drone_ids=("1",),
    )

    assert semantic_answer is not None
    assert "correlation verified for act-a1b2c3d4" in semantic_answer.content
    assert tracker.calls == ["recent", "active", "statistics"]


def test_drone_log_summary_scopes_commands_and_ulog_to_durable_action_run(monkeypatch):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools, answer_mds_read_only_question

    started = datetime(2026, 6, 20, 22, 1, tzinfo=timezone.utc)
    started_ms = int(started.timestamp() * 1000)
    action_commands = (
        ("cmd-takeoff-1", "TAKE_OFF", "simurgh:act-run1234:take_off", 2_000, 15_000),
        ("cmd-move-1", "PRECISION_MOVE", "simurgh:act-run1234:step:2", 20_000, 30_000),
        ("cmd-rtl-1", "RETURN_RTL", "simurgh:act-run1234:step:3", 35_000, 45_000),
    )
    recent = [
        {
            "command_id": command_id,
            "mission_name": mission_name,
            "target_drones": ["1"],
            "phase": "terminal",
            "status": "completed",
            "outcome": "success",
            "created_at": started_ms + start_offset,
            "execution_started_at": started_ms + start_offset,
            "completed_at": started_ms + end_offset,
            "updated_at": started_ms + end_offset,
            "params": {"operator_label": operator_label},
        }
        for command_id, mission_name, operator_label, start_offset, end_offset in action_commands
    ]
    recent.append(
        {
            "command_id": "cmd-unrelated",
            "mission_name": "LAND",
            "target_drones": ["1"],
            "phase": "terminal",
            "status": "failed",
            "outcome": "failed",
            "created_at": started_ms + 10_000,
            "execution_started_at": started_ms + 10_000,
            "completed_at": started_ms + 12_000,
            "updated_at": started_ms + 12_000,
            "params": {"operator_label": "simurgh:act-unrelated:step:1"},
        }
    )
    tracker = _PublicCommandTrackerStub(
        recent=tuple(recent),
        stats={
            "total_commands": 4,
            "successful_commands": 3,
            "failed_commands": 1,
        },
    )
    deps = SimpleNamespace(
        load_config=lambda: [{"hw_id": 1, "ip": "192.0.2.31"}],
        get_command_tracker=lambda: tracker,
    )

    def fake_fetch(self, drone_ip, path, *, params=None, timeout=0):  # noqa: ANN001
        if path == "/api/logs/sessions":
            return {"sessions": []}, ""
        if path == "/api/v1/ulog/files":
            return {
                "files": [{"id": 11, "date_utc": "2026-06-20T22:01:00Z", "size_bytes": 2048}]
            }, ""
        if path == "/api/v1/ulog/files/11/summary":
            return {
                "parsed": True,
                "parser": {"status": "ok"},
                "duration_sec": 60.0,
                "staged_job_deleted": True,
            }, ""
        raise AssertionError(path)

    monkeypatch.setattr(MdsReadOnlyTools, "_fetch_drone_json", fake_fetch)
    monkeypatch.setattr(
        MdsReadOnlyTools,
        "_recent_warning_events",
        lambda self, **_kwargs: ([], ["gcs.jsonl"]),
    )
    action_context = {
        "draft_id": "act-run1234",
        "command_id": "cmd-takeoff-1",
        "action_run_created_at": "2026-06-20T22:01:00Z",
        "action_run_completed_at": "2026-06-20T22:02:00Z",
        "action_run_result": {
            "post_action_results": [
                {"command_id": "cmd-move-1"},
                {"command_id": "cmd-rtl-1"},
            ]
        },
    }

    answer = answer_mds_read_only_question(
        "Verify this completed mission from the command tracker, unified logs, and newest ULog.",
        deps=deps,
        intent_override="drone_log_summary",
        target_drone_ids=("1",),
        action_context=action_context,
    )

    assert answer is not None
    assert "Durable action-run command tracker evidence" in answer.content
    assert "cmd-unrelated" not in answer.content
    assert "LAND" not in answer.content
    assert "correlation verified for act-run1234" in answer.content
    assert "3 GCS command id(s)" in answer.content
    assert "Scope: durable action-run time window" in answer.content


def test_action_scoped_command_snapshot_rehydrates_durable_monitor_records():
    from agent_runtime.mds_read_tools import _scope_command_snapshot_to_action

    action_context = {
        "draft_id": "act-durable",
        "command_id": "cmd-primary",
        "target_drone_ids": ["1"],
        "action_run_result": {
            "monitor_result": {
                "command_status": {
                    "command_id": "cmd-primary",
                    "mission_name": "TAKE_OFF",
                    "target_drones": ["1"],
                    "status": "completed",
                    "outcome": "completed",
                    "created_at": 1000,
                    "completed_at": 2000,
                    "params": {"operator_label": "simurgh:act-durable:take_off"},
                }
            },
            "post_action_results": [
                {
                    "command_id": "cmd-rtl",
                    "resolved_target_drone_ids": ["1"],
                    "monitor_result": {
                        "command_status": {
                            "command_id": "cmd-rtl",
                            "mission_name": "RETURN_RTL",
                            "status": "completed",
                            "outcome": "completed",
                            "created_at": 3000,
                            "completed_at": 4000,
                            "params": {"operator_label": "simurgh:act-durable:step:2"},
                        }
                    },
                }
            ],
        },
    }

    scoped = _scope_command_snapshot_to_action(
        {
            "available": True,
            "recent": [],
            "active": [],
            "stats": {},
        },
        action_context,
    )

    assert [item["command_id"] for item in scoped["recent"]] == [
        "cmd-primary",
        "cmd-rtl",
    ]
    assert scoped["missing_command_ids"] == []
    assert scoped["durable_command_ids"] == ["cmd-primary", "cmd-rtl"]
    assert scoped["stats"] == {
        "total_commands": 2,
        "successful_commands": 2,
        "failed_commands": 0,
        "partial_commands": 0,
    }


def test_drone_log_summary_does_not_verify_when_one_sequence_step_label_is_unmatched(monkeypatch):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools, answer_mds_read_only_question

    started = datetime(2026, 6, 20, 22, 1, tzinfo=timezone.utc)
    started_ms = int(started.timestamp() * 1000)
    tracker = _PublicCommandTrackerStub(
        recent=(
            {
                "command_id": "cmd-takeoff-1",
                "mission_name": "TAKE_OFF",
                "target_drones": ["1"],
                "created_at": started_ms + 2_000,
                "execution_started_at": started_ms + 5_000,
                "completed_at": started_ms + 15_000,
                "updated_at": started_ms + 15_000,
                "params": {"operator_label": "simurgh:act-a1b2c3d4:take_off"},
            },
            {
                "command_id": "cmd-move-1",
                "mission_name": "PRECISION_MOVE",
                "target_drones": ["1"],
                "created_at": started_ms + 20_000,
                "execution_started_at": started_ms + 22_000,
                "completed_at": started_ms + 30_000,
                "updated_at": started_ms + 30_000,
                "params": {"operator_label": "simurgh:act-a1b2c3d4:step:not-an-index"},
            },
            {
                "command_id": "cmd-rtl-1",
                "mission_name": "RETURN_RTL",
                "target_drones": ["1"],
                "created_at": started_ms + 35_000,
                "execution_started_at": started_ms + 37_000,
                "completed_at": started_ms + 45_000,
                "updated_at": started_ms + 45_000,
                "params": {"operator_label": "simurgh:act-a1b2c3d4:step:3"},
            },
        ),
        stats={"total_commands": 3, "successful_commands": 3},
    )
    deps = SimpleNamespace(
        load_config=lambda: [{"hw_id": 1, "ip": "192.0.2.31"}],
        get_command_tracker=lambda: tracker,
    )

    def fake_fetch(self, drone_ip, path, *, params=None, timeout=0):  # noqa: ANN001
        if path == "/api/logs/sessions":
            return {"sessions": []}, ""
        if path == "/api/v1/ulog/files":
            return {
                "files": [{"id": 8, "date_utc": "2026-06-20T22:01:00Z", "size_bytes": 2048}]
            }, ""
        if path == "/api/v1/ulog/files/8/summary":
            return {
                "parsed": True,
                "parser": {"status": "ok"},
                "duration_sec": 60.0,
                "staged_job_deleted": True,
            }, ""
        raise AssertionError(path)

    monkeypatch.setattr(MdsReadOnlyTools, "_fetch_drone_json", fake_fetch)

    answer = answer_mds_read_only_question(
        "Verify this completed mission from the command tracker, unified logs, and newest ULog.",
        deps=deps,
    )

    assert answer is not None
    assert "correlation candidate only" in answer.content
    assert "correlation verified" not in answer.content
    assert tracker.calls == ["recent", "active", "statistics"]


def test_backend_log_summary_reports_unknown_when_no_source_is_scanned(monkeypatch):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools

    monkeypatch.setattr(MdsReadOnlyTools, "_recent_warning_events", lambda self, **kwargs: ([], []))

    answer = MdsReadOnlyTools().backend_log_summary()

    assert "Warning/error count is unknown because no local GCS log source was scanned." in answer.content
    assert "No WARNING/ERROR/CRITICAL entries were found" not in answer.content


def test_fleet_flight_state_labels_landed_and_altitude_frames():
    from agent_runtime.mds_read_tools import _fleet_altitude_summary, _fleet_health_summary

    airborne = _fleet_health_summary(
        {
            "landed_state": 2,
            "position_alt": 1_234.5,
            "gps_raw_altitude_m": 1_235.0,
        }
    )
    landed = _fleet_health_summary(
        {
            "landed_state": 1,
            "relative_altitude_m": 0.2,
        }
    )
    local_report = _fleet_altitude_summary(
        {
            "position_alt": 1_298.2,
            "altitude_report": {
                "display_m": 20.2,
                "source": "local_ned",
                "label": "LCL",
                "relative_home_m": None,
                "local_up_m": 20.2,
            },
        }
    )

    assert airborne["landed"] == "In air"
    assert "Landed: In air" in airborne["flight_state"]
    assert "Altitude: 1234.5 m MSL" in airborne["flight_state"]
    assert "Final state" not in airborne["flight_state"]
    assert landed["landed"] == "On ground"
    assert "Altitude: 0.2 m REL" in landed["flight_state"]
    assert local_report == {"value": 20.2, "label": "LCL", "source": "local_ned"}


def test_assistant_turn_audit_records_read_only_plan_without_prompt_leak(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    record = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="what is mavlink?",
    )

    plan = record.audit_event.metadata["read_only_plan"]
    assert plan["intent"] == "general_knowledge"
    assert plan["response_mode"] == "interpret"
    assert plan["execution_layer"] == "local_advisory"
    assert plan["tool_ids"] == ["simurgh.general_knowledge.read"]
    assert "message" not in plan
    assert "normalized_message" not in plan


def test_assistant_turn_records_structured_read_only_evidence(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    sessions = AgentSessionStore()

    record = create_assistant_turn(
        sessions=sessions,
        audit=InMemoryAuditSink(),
        actor="operator",
        message="How many drones do we have configured?",
    )

    evidence = record.audit_event.metadata["read_only_evidence"]
    assert evidence["intent"] == "fleet_summary"
    assert evidence["response_mode"] == "status"
    assert evidence["source"] == "local_read_only_mds"
    assert evidence["item_count"] == 1
    assert "mds.config.fleet.read" in evidence["tool_ids"]
    assert "Fleet status from GCS configuration" in evidence["summary"]
    assert "How many drones" not in json.dumps(evidence)

    private_context = sessions.get_private_context(record.session.id)
    persisted = json.loads(private_context["last_read_only_evidence"])
    assert persisted["content_hash"] == evidence["content_hash"]
    assert persisted["summary"] == evidence["summary"]


def test_read_tools_answer_mds_autopilot_support_boundary():
    from agent_runtime.mds_read_tools import answer_mds_read_only_question

    answer = answer_mds_read_only_question("does MDS support ArduPilot?")

    assert answer is not None
    assert answer.intent == "autopilot_support"
    assert "PX4-first" in answer.content
    assert "not currently supported" in answer.content.lower()
    assert "ArduPilot" in answer.content


def test_read_tools_answer_exposes_structured_evidence_bundle():
    from agent_runtime.mds_read_tools import answer_mds_read_only_question

    answer = answer_mds_read_only_question("check latest backend warnings in the logs")

    assert answer is not None
    assert answer.evidence is not None
    metadata = answer.evidence.public_metadata()
    assert metadata["intent"] == "backend_log_summary"
    assert metadata["source"] == "local_read_only_mds"
    assert metadata["item_count"] == 1
    assert "mds.logs.sessions.read" in metadata["tool_ids"]
    assert metadata["content_hash"]
    assert "message" not in metadata


def test_assistant_turn_answers_origin_launch_positions_as_read_only_status(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    deps = SimpleNamespace(
        load_origin=lambda: {"lat": 35.0, "lon": 51.0, "alt": 1200.0, "alt_source": "fixture"},
        get_all_drone_positions=lambda: [
            {"hw_id": 1, "pos_id": 1, "x": -2.5, "y": 10.0},
            {"hw_id": 2, "pos_id": 2, "x": -2.5, "y": 5.0},
        ],
    )

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="what is current origin and launch position status?",
        deps=deps,
    )

    assert record.turn.provider == "mds-tools"
    assert record.audit_event.metadata["tool_intent"] == "origin_status"
    assert record.turn.blocked_intents == ()
    assert "Origin and launch-position status" in record.turn.content
    assert "35.0000000" in record.turn.content
    assert "No mission/global origin is currently set" not in record.turn.content


def test_assistant_turn_answers_sidecar_px4_system_and_environment_read_only(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    sidecar = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="what wifi and mavlink sidecar dashboards exist?",
    )
    assert sidecar.turn.provider == "mds-tools"
    assert sidecar.audit_event.metadata["tool_intent"] == "sidecar_status"
    assert "smart-wifi-manager" in sidecar.turn.content
    assert "/fleet-ops/wifi" in sidecar.turn.content
    assert "mavlink-anywhere" in sidecar.turn.content

    px4 = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="what px4 params support do we have?",
    )
    assert px4.turn.provider == "mds-tools"
    assert px4.audit_event.metadata["tool_intent"] == "px4_params_summary"
    assert "PX4 parameter support" in px4.turn.content
    assert "ArduPilot" not in px4.turn.content

    system = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="what is current GCS health and system status?",
    )
    assert system.turn.provider == "mds-tools"
    assert system.audit_event.metadata["tool_intent"] == "system_status"
    assert "Current GCS/Simurgh health summary" in system.turn.content

    env = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="which environment settings and API keys can I edit?",
    )
    assert env.turn.provider == "mds-tools"
    assert env.audit_event.metadata["tool_intent"] == "environment_summary"
    assert "Environment registry" in env.turn.content
    assert "raw values" in env.turn.content.lower()


def test_assistant_turn_summarizes_fleet_ops_sidecar_node_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    now_ms = int(time.time() * 1000)
    deps = SimpleNamespace(
        BASE_DIR=str(tmp_path),
        Params=SimpleNamespace(TELEMETRY_POLLING_TIMEOUT=600, drone_api_port=7070),
        load_config=lambda: [
            {"hw_id": "1", "pos_id": 1, "ip": "198.51.100.11"},
        ],
        get_all_heartbeats=lambda: {"1": {"timestamp": now_ms}},
        data_lock_git_status=None,
        git_status_data_all_drones={
            "1": {
                "connectivity_runtime": {
                    "service_status": "active",
                    "dashboard_access_mode": "direct",
                    "dashboard_listen": "0.0.0.0:9080",
                    "mode": "fleet-merge",
                    "drift_state": "in_sync",
                    "profile_count": 2,
                    "profile_summary": {
                        "source": "runtime",
                        "profiles": [
                            {"ssid": "field-link", "priority": 50, "password": "redacted-by-route"},
                        ],
                    },
                },
                "mavlink_runtime": {
                    "router_service_status": "active",
                    "dashboard_access_mode": "direct",
                    "dashboard_listen": "0.0.0.0:9070",
                    "mode": "local",
                    "drift_state": "in_sync",
                    "endpoint_count": 1,
                    "profile_summary": {
                        "source": "runtime",
                        "endpoints": [
                            {"name": "qgc", "type": "UdpEndpoint", "mode": "client", "port": 14550},
                        ],
                    },
                },
            },
        },
        get_network_info_from_heartbeats=lambda: [{"hw_id": "1", "link": "example"}],
    )

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="which wifi and mavlink sidecar dashboards are live and are profiles drifted?",
        deps=deps,
    )

    assert record.turn.provider == "mds-tools"
    assert record.audit_event.metadata["tool_intent"] == "sidecar_status"
    assert "Fleet Ops sidecar status from current GCS state" in record.turn.content
    assert "smart-wifi-manager" in record.turn.content
    assert "mavlink-anywhere" in record.turn.content
    assert "http://198.51.100.11:9080/" in record.turn.content
    assert "http://198.51.100.11:9070/" in record.turn.content
    assert "in_sync" in record.turn.content
    assert "No Wi-Fi profile, MAVLink route, repository state, or drone setting was changed" in record.turn.content


def test_assistant_turn_summarizes_fleet_enrollment_candidates(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    now_ms = int(time.time() * 1000)
    deps = SimpleNamespace(
        get_fleet_candidates_payload=lambda include_inactive=True, runtime_mode="current": {
            "runtime_mode_filter": "real",
            "timestamp": now_ms,
            "state_counts": {"pending_operator_review": 1, "conflict": 1, "accepted": 1},
            "candidates": [
                {
                    "candidate_id": "real:node-alpha",
                    "runtime_mode": "real",
                    "node_uuid": "node-alpha",
                    "hw_id": "3",
                    "hostname": "cm4-03",
                    "primary_control_ip": "198.51.100.33",
                    "registration_state": "pending_operator_review",
                    "heartbeat_status": "online",
                    "heartbeat_age_sec": 4,
                    "reported_pos_id": "3",
                },
                {
                    "candidate_id": "real:node-bravo",
                    "runtime_mode": "real",
                    "node_uuid": "node-bravo",
                    "hw_id": "2",
                    "hostname": "node-bravo-replacement",
                    "ip_addresses": ["198.51.100.22"],
                    "registration_state": "conflict",
                    "conflict_reasons": ["hw_id_already_in_fleet"],
                    "heartbeat_status": "stale",
                    "heartbeat_age_sec": 120,
                    "detected_pos_id": "2",
                },
                {
                    "candidate_id": "real:old-node",
                    "runtime_mode": "real",
                    "hw_id": "9",
                    "hostname": "old-node",
                    "registration_state": "accepted",
                    "heartbeat_status": "offline",
                    "heartbeat_age_sec": 3600,
                },
            ],
        }
    )

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="are there any new boards waiting in fleet enrollment or conflicts?",
        deps=deps,
    )

    assert record.turn.provider == "mds-tools"
    assert record.audit_event.metadata["tool_intent"] == "fleet_enrollment_summary"
    assert "Fleet Enrollment status from current GCS state" in record.turn.content
    assert "real:node-alpha" in record.turn.content
    assert "cm4-03" in record.turn.content
    assert "pending operator review" in record.turn.content
    assert "hw id already in fleet" in record.turn.content
    assert "Presence caution" in record.turn.content
    assert "Fleet Enrollment" in record.turn.content
    assert "No enrollment, repository, or flight action was executed" in record.turn.content
    assert "Fleet status from GCS configuration" not in record.turn.content


def test_read_tools_answer_no_fleet_enrollment_candidates():
    from agent_runtime.mds_read_tools import answer_mds_read_only_question, classify_mds_read_intent

    deps = SimpleNamespace(
        get_fleet_candidates_payload=lambda include_inactive=True, runtime_mode="current": {
            "runtime_mode_filter": "real",
            "timestamp": int(time.time() * 1000),
            "state_counts": {},
            "candidates": [],
        }
    )

    assert classify_mds_read_intent("show fleet enrollment candidates") == "fleet_enrollment_summary"
    answer = answer_mds_read_only_question("show fleet enrollment candidates", deps=deps)

    assert answer is not None
    assert answer.intent == "fleet_enrollment_summary"
    assert "do not see any announced companion/board candidates" in answer.content
    assert "Use [Fleet Enrollment](/fleet-enrollment)" in answer.content
    assert "mds.fleet.candidates.read" not in answer.content


def test_read_tools_answer_fleet_enrollment_registry_error_is_not_empty_status():
    from agent_runtime.mds_read_tools import answer_mds_read_only_question

    deps = SimpleNamespace(
        get_fleet_candidates_payload=lambda include_inactive=True, runtime_mode="current": {
            "runtime_mode_filter": "real",
            "timestamp": int(time.time() * 1000),
            "state_counts": {},
            "candidates": [],
            "error": "candidate registry unavailable",
        }
    )

    answer = answer_mds_read_only_question("show fleet enrollment candidates", deps=deps)

    assert answer is not None
    assert answer.intent == "fleet_enrollment_summary"
    assert "could not verify Fleet Enrollment candidates" in answer.content
    assert "Do not treat this as zero candidates" in answer.content
    assert "do not see any announced companion/board candidates" not in answer.content
    assert answer.tool_ids == ("mds.fleet.candidates.read",)


def test_fleet_enrollment_classifier_does_not_steal_board_setup_docs_prompt():
    from agent_runtime.mds_read_tools import classify_mds_read_intent

    assert (
        classify_mds_read_intent("can you give me link to the doc so where I can read about how to setup new board and setup its env and keys")
        == "board_setup_help"
    )
    assert classify_mds_read_intent("how do I enroll a new board?") == "board_setup_help"
    assert classify_mds_read_intent("how many pending fleet enrollment candidates are there?") == "fleet_enrollment_summary"
    assert classify_mds_read_intent("how do I add a new drone and enroll it?") == "add_drone_workflow"
    assert classify_mds_read_intent("if I want to build new drone 3 on a raspberry pi what should I do?") == "companion_setup_help"
    assert classify_mds_read_intent("are there any pending fleet enrollment candidates?") == "fleet_enrollment_summary"


def test_read_tools_answer_selected_fleet_enrollment_candidate():
    from agent_runtime.mds_read_tools import answer_mds_read_only_question

    deps = SimpleNamespace(
        get_fleet_candidates_payload=lambda include_inactive=True, runtime_mode="current": {
            "runtime_mode_filter": "real",
            "timestamp": int(time.time() * 1000),
            "state_counts": {"pending_operator_review": 2},
            "candidates": [
                {
                    "candidate_id": "real:node-alpha",
                    "runtime_mode": "real",
                    "node_uuid": "node-alpha",
                    "hw_id": "3",
                    "hostname": "cm4-03",
                    "primary_control_ip": "198.51.100.33",
                    "registration_state": "pending_operator_review",
                    "heartbeat_status": "online",
                    "heartbeat_age_sec": 4,
                },
                {
                    "candidate_id": "real:node-bravo",
                    "runtime_mode": "real",
                    "node_uuid": "node-bravo",
                    "hw_id": "4",
                    "hostname": "cm4-04",
                    "primary_control_ip": "198.51.100.44",
                    "registration_state": "pending_operator_review",
                    "heartbeat_status": "online",
                    "heartbeat_age_sec": 9,
                },
            ],
        }
    )

    answer = answer_mds_read_only_question("show fleet enrollment candidate real:node-bravo", deps=deps)

    assert answer is not None
    assert answer.intent == "fleet_enrollment_summary"
    assert "Selected candidate: `real:node-bravo`" in answer.content
    assert "cm4-04" in answer.content
    assert "198.51.100.44" in answer.content
    assert "cm4-03" not in answer.content
    assert "No enrollment, repository, or flight action was executed" in answer.content
    assert answer.tool_ids == ("mds.fleet.candidates.read",)


def test_read_tools_answer_fleet_enrollment_count_prompt_does_not_select_hw_id():
    from agent_runtime.mds_read_tools import answer_mds_read_only_question

    deps = SimpleNamespace(
        get_fleet_candidates_payload=lambda include_inactive=True, runtime_mode="current": {
            "runtime_mode_filter": "real",
            "timestamp": int(time.time() * 1000),
            "state_counts": {"pending_operator_review": 2},
            "candidates": [
                {
                    "candidate_id": "real:node-alpha",
                    "runtime_mode": "real",
                    "node_uuid": "node-alpha",
                    "hw_id": "3",
                    "hostname": "cm4-03",
                    "primary_control_ip": "198.51.100.33",
                    "registration_state": "pending_operator_review",
                    "heartbeat_status": "online",
                    "heartbeat_age_sec": 4,
                },
                {
                    "candidate_id": "real:node-bravo",
                    "runtime_mode": "real",
                    "node_uuid": "node-bravo",
                    "hw_id": "4",
                    "hostname": "cm4-04",
                    "primary_control_ip": "198.51.100.44",
                    "registration_state": "pending_operator_review",
                    "heartbeat_status": "online",
                    "heartbeat_age_sec": 9,
                },
            ],
        }
    )

    answer = answer_mds_read_only_question("are there 3 pending fleet enrollment candidates?", deps=deps)

    assert answer is not None
    assert answer.intent == "fleet_enrollment_summary"
    assert "Selected candidate" not in answer.content
    assert "cm4-03" in answer.content
    assert "cm4-04" in answer.content


def test_assistant_turn_answers_command_tracker_summary_from_deps(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    command = SimpleNamespace(
        command_id="cmd-1234567890",
        mission_type=10,
        mission_name="TAKE_OFF",
        phase="pending_execution",
        status="submitted",
        outcome=None,
        target_drones=["1", "2"],
        created_at=1,
        updated_at=2,
    )
    tracker = _PublicCommandTrackerStub(
        recent=(command,),
        active=(command,),
        stats={
            "total_commands": 1,
            "successful_commands": 0,
            "failed_commands": 0,
            "partial_commands": 0,
        },
    )
    deps = SimpleNamespace(get_command_tracker=lambda: tracker)

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="what commands are active or recent?",
        deps=deps,
    )

    assert record.turn.provider == "mds-tools"
    assert record.audit_event.metadata["tool_intent"] == "command_summary"
    assert "GCS command tracker summary" in record.turn.content
    assert "TAKE_OFF" in record.turn.content
    assert "No direct drone API" not in record.turn.content


def test_assistant_turn_answers_git_status_summary_from_deps(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    class NoopLock:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    now_ms = int(time.time() * 1000)
    deps = SimpleNamespace(
        load_config=lambda: [
            {"hw_id": 1, "pos_id": 1, "ip": "198.51.100.11"},
            {"hw_id": 2, "pos_id": 2, "ip": "198.51.100.12"},
        ],
        get_gcs_git_report=lambda: {
            "branch": "main",
            "commit": "abc123456789",
            "status": "dirty",
            "commits_ahead": 1,
            "commits_behind": 0,
            "uncommitted_changes": [" M swarm.json"],
        },
        get_all_heartbeats=lambda: {
            "1": {"timestamp": now_ms, "hw_id": "1"},
            "2": {"timestamp": now_ms, "hw_id": "2"},
        },
        git_status_data_all_drones={
            "1": {
                "status": "clean",
                "branch": "main",
                "commit": "abc123456789",
                "commits_ahead": 0,
                "commits_behind": 0,
                "uncommitted_changes": [],
                "git_auth_health_status": "healthy",
            },
            "2": {
                "status": "dirty",
                "branch": "main",
                "commit": "def987654321",
                "commits_ahead": 0,
                "commits_behind": 1,
                "uncommitted_changes": [" M config.json"],
                "git_auth_health_status": "warning",
            },
        },
        data_lock_git_status=NoopLock(),
        _sync_state={"active": False},
        Params=SimpleNamespace(TELEMETRY_POLLING_TIMEOUT=5),
    )

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="check git repo status; did the smart swarm commit happen and are boards synced?",
        deps=deps,
    )

    assert record.turn.provider == "mds-tools"
    assert record.audit_event.metadata["tool_intent"] == "git_status_summary"
    assert "GCS repository and fleet sync status" in record.turn.content
    assert "swarm.json" in record.turn.content
    assert "pos 1 / hw 1" in record.turn.content
    assert "pos 2 / hw 2" in record.turn.content
    assert "needs review" in record.turn.content
    assert "No git commit, push, pull, node sync" in record.turn.content


def test_assistant_turn_translates_previous_answer_instead_of_capability_catalog(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "هیچ پهپادی در حال حاضر متصل دیده نمی‌شود. هیچ فرمانی به پهپاد ارسال نشد.",
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="wat droens are connected?",
    )

    assert first.turn.provider == "mds-tools"
    assert first.audit_event.metadata["tool_intent"] == "fleet_connectivity"
    assert first.session.metadata["last_domain"] == "fleet"

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="can you say it in persian",
    )

    assert followup.turn.provider == "openai"
    assert followup.audit_event.metadata["tool_intent"] == "conversation_transform"
    assert followup.audit_event.metadata["response_mode"] == "transform"
    assert "MCP endpoint" not in followup.turn.content
    assert "capability registry" not in followup.turn.content
    assert "session.previous_assistant_answer" in str(captured["input"])
    assert "Connectivity from GCS state" in str(captured["input"])


def test_assistant_turn_translates_immediate_fleet_answer_for_persian_followup(monkeypatch, tmp_path):
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "وضعیت ناوگان از پیکربندی GCS: ۲ پهپاد تنظیم شده‌اند. هیچ فرمانی ارسال نشد.",
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="what is the current fleet status and info?",
    )

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="فارسی بگو همینو",
    )

    assert followup.turn.provider == "openai"
    assert followup.audit_event.metadata["tool_intent"] == "conversation_transform"
    assert "Fleet status from GCS configuration" in str(captured["input"])
    assert "MCP endpoint" not in followup.turn.content


def test_assistant_turn_honors_server_grounded_semantic_transform_without_phrase_aliases(
    monkeypatch,
    tmp_path,
):
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        del self, api_key
        captured.update(payload)
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "۴ فرمان موفق بود و پهپاد فرود آمد.",
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()
    first = create_mock_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="Report the result.",
        metadata={"fixture": "previous-answer"},
    )

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="همین خلاصه را کوتاه و فارسی بگو",
        metadata={
            "_semantic_conversation_transform_kind": "transform_previous_answer",
        },
    )

    assert followup.turn.provider == "openai"
    assert followup.audit_event.metadata["tool_intent"] == "conversation_transform"
    assert "۴ فرمان موفق" in followup.turn.content
    assert "session.previous_assistant_answer" in str(captured["input"])
    assert first.turn.content in str(captured["input"])


def test_assistant_turn_explicit_fleet_status_overrides_log_topic(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="check last 1 hour logs is there anything I need to know?",
    )
    assert first.audit_event.metadata["tool_intent"] == "backend_log_summary"
    assert first.session.metadata["last_domain"] == "logs"

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="what is the current fleet status and info?",
    )

    assert followup.turn.provider == "mds-tools"
    assert followup.audit_event.metadata["tool_intent"] == "fleet_summary"
    assert followup.audit_event.metadata["query_domain"] == "fleet"
    assert "Fleet status from GCS configuration" in followup.turn.content
    assert "Backend warning/error summary" not in followup.turn.content


def test_assistant_turn_mds_telemetry_followup_overrides_log_topic(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="check latest logs and tell me if anything is wrong",
    )
    assert first.audit_event.metadata["tool_intent"] == "backend_log_summary"
    assert first.session.metadata["last_domain"] == "logs"

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message=(
            "I dont have QGC now. All I have is what you already have in MDS telemetry. "
            "You can check yourself. Why do you rely on me?"
        ),
    )

    assert followup.turn.provider == "mds-tools"
    assert followup.audit_event.metadata["tool_intent"] == "fleet_connectivity"
    assert followup.audit_event.metadata["query_domain"] == "fleet"
    assert "Connectivity from GCS state" in followup.turn.content
    assert "Backend warning/error summary" not in followup.turn.content


def test_assistant_turn_generic_self_check_does_not_steal_log_topic(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="check latest logs and tell me if anything is wrong",
    )
    assert first.audit_event.metadata["tool_intent"] == "backend_log_summary"
    assert first.session.metadata["last_domain"] == "logs"

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="you can check yourself, why do you rely on me?",
    )

    assert followup.turn.provider == "mds-tools"
    assert followup.audit_event.metadata["tool_intent"] == "backend_log_summary"
    assert followup.audit_event.metadata["query_domain"] == "logs"
    assert "Connectivity from GCS state" not in followup.turn.content


def test_assistant_turn_answers_general_robotics_and_weather_without_fleet_tables(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="any drone connected?",
    )
    assert first.session.metadata["last_domain"] == "fleet"

    drone = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="what is a drone?",
    )
    assert drone.turn.provider == "mds-tools"
    assert drone.audit_event.metadata["tool_intent"] == "general_knowledge"
    assert "unmanned aircraft" in drone.turn.content
    assert "Fleet status from GCS configuration" not in drone.turn.content

    mavlink = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="what is mavlink?",
    )
    assert mavlink.audit_event.metadata["tool_intent"] == "general_knowledge"
    assert "MAVLink" in mavlink.turn.content
    assert "Connectivity from GCS state" not in mavlink.turn.content

    weather = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="how is the weather today?",
    )
    assert weather.audit_event.metadata["tool_intent"] == "general_knowledge"
    assert "do not have a live weather feed" in weather.turn.content
    assert "Fleet status from GCS configuration" not in weather.turn.content


def test_assistant_turn_routes_can_you_warning_request_to_logs_not_capabilities(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="what drones are connected?",
    )

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="can you report any warning from the last 30 minutes in GCS?",
    )

    assert followup.turn.provider == "mds-tools"
    assert followup.audit_event.metadata["tool_intent"] == "backend_log_summary"
    assert followup.audit_event.metadata["query_domain"] == "logs"
    assert "Backend warning/error summary" in followup.turn.content
    assert "Simurgh capabilities" not in followup.turn.content
    assert "MCP endpoint" not in followup.turn.content


def test_assistant_turn_routes_setup_followup_to_bootstrap_guidance(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="if I want to add a third drone now, what workflow must be done?",
    )

    assert first.turn.provider == "mds-tools"
    assert first.session.metadata["last_domain"] == "setup"

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="what scripts and docs should I use now?",
    )

    assert followup.turn.provider == "mds-tools"
    assert followup.audit_event.metadata["tool_intent"] == "companion_setup_help"
    assert "tools/install_mds_node.sh" in followup.turn.content
    assert "Fleet Enrollment" in followup.turn.content
    assert "generic checklist" not in followup.turn.content


def test_assistant_turn_routes_capability_followup_from_session_context(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()

    first = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        message="What MCP tools and API capabilities can Simurgh expose?",
    )

    assert first.turn.provider == "mds-tools"
    assert first.session.metadata["last_domain"] == "capabilities"

    followup = create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor="operator",
        session_id=first.session.id,
        message="can n8n use that same menu too?",
    )

    assert followup.turn.provider == "mds-tools"
    assert followup.audit_event.metadata["tool_intent"] == "capability_catalog"
    assert "MCP endpoint" in followup.turn.content
    assert "config/agent_tools.yaml" in followup.turn.content


def test_assistant_turn_uses_query_plan_fallback_for_client_api_prompt(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="what interfaces are exposed to clients like n8n and claude?",
    )

    assert record.turn.provider == "mds-tools"
    assert record.audit_event.metadata["tool_intent"] == "capability_catalog"
    assert "MCP endpoint" in record.turn.content
    assert "hardcoded chat-only tools" in record.turn.content


def test_assistant_turn_includes_generated_docs_sources_for_docs_questions(monkeypatch):
    from agent_runtime.docs_index import build_docs_search_payload

    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="can you give me link to read about creating sitl demo?",
    )

    assert record.turn.provider == "mds-tools"
    assert "Sources:" in record.turn.content
    assert "chunk `" in record.turn.content
    assert "/api/v1/simurgh/context/mds.advanced_sitl/markdown" in record.turn.content
    docs_payload = build_docs_search_payload("creating sitl demo", tags="sitl", limit=3)
    assert docs_payload["results"]
    assert any(
        item["canonical_url"] in record.turn.content
        for item in docs_payload["results"]
    )


def test_assistant_turn_records_query_adaptation_trace_for_multilingual_local_tool(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="Combien de drones sont configurés maintenant ?",
    )

    assert record.turn.provider == "mds-tools"
    adaptation = record.audit_event.metadata["query_adaptation"]
    assert adaptation["input_language"] == "fr"
    assert adaptation["routing_language"] == "fr"
    assert adaptation["strategy"] == "provider-semantic-routing-required"
    assert adaptation["applied_rule_count"] == 0
    assert "Combien" not in str(adaptation)
    assert record.session.metadata["last_domain"] == "fleet"
    assert record.session.metadata["last_intent"] == "fleet_summary"


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
    assert "could not complete that request" in record.turn.content
    assert "Please clarify" in record.turn.content
    assert "provider request" not in record.turn.content
    assert "No provider request was made" in record.turn.safety_notes[0]


def test_openai_assistant_turn_still_blocks_direct_drone_show_launch(monkeypatch, tmp_path):
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
        message="Can you launch the drone show now?",
    )

    assert record.turn.provider == "openai"
    assert "launch" in record.turn.blocked_intents
    assert "could not complete that request" in record.turn.content
    assert "Please clarify" in record.turn.content
    assert "provider request" not in record.turn.content
    assert "Drone Show has two workflow families" not in record.turn.content


@pytest.mark.parametrize(
    ("message", "expected_signal"),
    (
        ("Here is a customer ULog excerpt from the field test.", "ulog excerpt"),
        ("The customer .ulg flight log is pasted below.", "customer flight log artifact"),
        ("The customer flight log is pasted below.", "customer flight log artifact"),
        ("Attach the QGroundControl log from the customer flight.", "QGroundControl log artifact"),
        ("CM4-99 stopped streaming on 192.168.1.10.", "field vehicle label"),
        ("Private repo path git@github.com:customer/mds-private.git", "private repository path"),
        ("Ticket ID TST-1042 includes the field notes.", "ticket identifier"),
        ("Serial SN:ABC123456 was visible in the screenshot.", "device serial identifier"),
        ("NetBird peer id peer_example12345 is in the report.", "NetBird peer identifier"),
        ("Screenshot from the customer field test is attached.", "screenshot"),
        ("2026-05-19 17:32:15 field log line was pasted.", "exact timestamp"),
        ("Mission name: Example Harbor Recovery should be redacted.", "mission name"),
        ("Customer identifier: ExampleSiteAlpha should be private.", "customer or site identifier"),
        ("INFO mavlink-router forwarded packet details from a private field run", "pasted log body"),
        ("".join(("Authorization: Bearer ", "mds_test_secret_12345 should not leave the GCS.")), "secret assignment"),
        ("".join(("The api key is ", "sk-", "test-redacted-12345.")), "secret assignment"),
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
    assert "raw field artifacts stay inside the GCS" in record.turn.content
    assert "local unified logs or derived ULog summary" in record.turn.content
    assert "Provider:" not in record.turn.content
    assert "Loaded context resources" not in record.turn.content
    assert "No provider request was made" in record.turn.safety_notes[0]


def test_safe_ulog_mission_check_clears_sensitive_signal_only_for_local_drone_log_summary():
    from agent_runtime.assistant import filter_safe_read_only_sensitive_input_matches, sensitive_input_matches
    from agent_runtime.mds_read_tools import build_mds_read_only_plan

    config = load_default_assistant_config()
    message = "Check the ulog and unified log to see if mission executed as we planned ?"
    plan = build_mds_read_only_plan(message)
    raw_matches = sensitive_input_matches(config, message)

    assert plan.intent == "drone_log_summary"
    assert raw_matches == ()
    assert (
        filter_safe_read_only_sensitive_input_matches(
            raw_matches,
            message=message,
            routing_message=message,
            local_intent=plan.intent,
        )
        == ()
    )

    unsafe_message = "Download the raw ULog and pasted unified log content for the mission."
    unsafe_plan = build_mds_read_only_plan(unsafe_message)
    unsafe_matches = sensitive_input_matches(config, unsafe_message)
    assert "raw or transferred ULog artifact" in unsafe_matches
    assert filter_safe_read_only_sensitive_input_matches(
        unsafe_matches,
        message=unsafe_message,
        routing_message=unsafe_message,
        local_intent=unsafe_plan.intent,
    )


def test_ulog_followup_overrides_generic_logs_conversation_topic():
    from agent_runtime.mds_read_tools import build_mds_read_only_plan

    plan = build_mds_read_only_plan(
        "Can you verify the mission from the ULog now?",
        conversation_topic="logs",
    )

    assert plan.intent == "drone_log_summary"
    assert "mds.logs.drone_ulog_files.read" in plan.tool_ids
    assert "mds.logs.drone_ulog_summary.read" in plan.tool_ids


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


def test_openai_semantic_routing_prompt_is_config_driven(monkeypatch, tmp_path):
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    config_path = tmp_path / "agent_assistant.yaml"
    payload = yaml.safe_load(ASSISTANT_CONFIG_PATH.read_text(encoding="utf-8"))
    payload["provider"] = "openai"
    payload["semantic_routing_instructions"] = "CONFIGURED SEMANTIC CONTRACT"
    config_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    monkeypatch.setenv("MDS_AGENT_ASSISTANT_FILE", str(config_path))
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    captured: dict[str, object] = {}

    def fake_post(self, request_payload, *, api_key):  # noqa: ANN001
        del api_key
        captured.update(request_payload)
        semantic_payload = {
            "normalized_message": "inspect status",
            "language": "en",
            "route_hint": "general_question",
            "read_intents": [],
            "read_target_drone_ids": [],
            "response_detail": "brief",
            "confidence": 0.98,
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_reason": "none",
            "action_control_explicit": False,
            "action_control_source_start": None,
            "action_control_source_end": None,
            "action_control_source_excerpt": None,
            "notes": [],
            "action_plan": None,
        }
        return {"output_text": json.dumps(semantic_payload)}

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    config = load_default_assistant_config()

    rewrite = rewrite_operator_message_with_provider(
        config=config,
        message="inspect status",
        previous_action_summary="target drone 1 from the previous completed action",
        allowed_target_ids=("1",),
    )

    assert rewrite is not None
    assert captured["instructions"] == "CONFIGURED SEMANTIC CONTRACT"
    assert json.loads(str(captured["input"]))["previous_action_summary"] == (
        "target drone 1 from the previous completed action"
    )
    assert json.loads(str(captured["input"]))["allowed_context_target_ids"] == ["1"]
    assert rewrite.response_detail == "brief"
    response_schema = captured["text"]["format"]["schema"]
    assert "response_detail" in response_schema["required"]
    assert response_schema["properties"]["response_detail"]["enum"] == [
        "brief",
        "standard",
        "detailed",
    ]
    action_plan_schema = response_schema["properties"]["action_plan"]["anyOf"][0]
    assert "target_references" in action_plan_schema["required"]


def test_semantic_action_route_preserves_independent_read_intents():
    message = "Report SITL status, then create one instance."
    action_excerpt = "create one instance"
    action_start = message.index(action_excerpt)
    payload = {
        "normalized_message": "Report SITL status, then create one instance.",
        "language": "en",
        "response_detail": "brief",
        "route_hint": "draft_sitl_lifecycle_action",
        "read_intents": ["sitl_status"],
        "read_options": {},
        "read_target_drone_ids": [],
        "confidence": 0.99,
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_reason": "none",
        "action_control_explicit": False,
        "action_control_source_start": None,
        "action_control_source_end": None,
        "action_control_source_excerpt": None,
        "notes": [],
        "action_plan": {
            "summary": "Create one SITL instance",
            "coverage_complete": True,
            "target_references": [],
            "preconditions": [],
            "steps": [
                {
                    "kind": "tool",
                    "tool_id": "mds.sitl.instances.create",
                    "arguments_json": "{}",
                    "delay_seconds": None,
                    "run_after_prior_failure": False,
                    "monitor_requested": True,
                    "label": "Create one SITL instance",
                    "source_message_index": 0,
                    "source_start": action_start,
                    "source_end": action_start + len(action_excerpt),
                    "source_excerpt": action_excerpt,
                }
            ],
        },
    }

    rewrite = _semantic_rewrite_from_payload(
        payload,
        config=load_default_assistant_config(),
        original_message=message,
    )

    assert rewrite.route_hint == "draft_sitl_lifecycle_action"
    assert rewrite.read_intents == ("sitl_status",)
    assert rewrite.action_plan is not None


def test_semantic_transform_route_requires_no_read_or_action_plan():
    payload = {
        "normalized_message": "Rewrite the previous answer briefly in Persian.",
        "language": "fa",
        "response_detail": "brief",
        "route_hint": "transform_previous_answer",
        "read_intents": [],
        "read_options": {},
        "read_target_drone_ids": [],
        "confidence": 0.99,
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_reason": "none",
        "action_control_explicit": False,
        "action_control_source_start": None,
        "action_control_source_end": None,
        "action_control_source_excerpt": None,
        "notes": [],
        "action_plan": None,
    }

    rewrite = _semantic_rewrite_from_payload(
        payload,
        config=load_default_assistant_config(),
        original_message="همین خلاصه را کوتاه و فارسی بگو",
    )

    assert rewrite.route_hint == "transform_previous_answer"
    assert rewrite.read_intents == ()
    assert rewrite.action_plan is None
    assert rewrite.usable_for_routing is True


def test_sensitive_semantic_redaction_is_reversible_and_provider_safe(
    monkeypatch,
    tmp_path,
):
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    config = load_default_assistant_config()
    message = (
        "لطفاً raw ULog را برای 35.6892, 51.3890 "
        "از 192.168.1.44 بررسی کن"
    )
    redaction = redact_sensitive_input_for_provider(config, message)

    assert redaction.has_redactions is True
    assert "35.6892, 51.3890" not in redaction.redacted_text
    assert "192.168.1.44" not in redaction.redacted_text
    assert "raw ULog" not in redaction.redacted_text
    assert redaction.restore(redaction.redacted_text) == message
    assert "35.6892" not in repr(redaction)
    assert "192.168.1.44" not in repr(redaction)
    assert all(
        "35.6892" not in json.dumps(item, ensure_ascii=False)
        and "192.168.1.44" not in json.dumps(item, ensure_ascii=False)
        and "raw ULog" not in json.dumps(item, ensure_ascii=False)
        for item in redaction.provider_placeholders()
    )

    captured: dict[str, object] = {}

    def fake_post(self, request_payload, *, api_key):  # noqa: ANN001
        del self, api_key
        captured.update(request_payload)
        provider_input = json.loads(str(request_payload["input"]))
        return {
            "output_text": json.dumps(
                {
                    "normalized_message": provider_input["operator_message"],
                    "language": "fa",
                    "response_detail": "brief",
                    "route_hint": "read_status",
                    "read_intents": ["drone_log_summary"],
                    "read_options": {
                        "drone_log_summary": {
                            "verify_operation": False,
                            "include_unified_logs": False,
                            "analyze_latest_ulog": True,
                        }
                    },
                    "read_target_drone_ids": [],
                    "confidence": 0.99,
                    "needs_clarification": False,
                    "clarification_question": "",
                    "clarification_reason": "none",
                    "action_control_explicit": False,
                    "action_control_source_start": None,
                    "action_control_source_end": None,
                    "action_control_source_excerpt": None,
                    "notes": [],
                    "action_plan": None,
                },
                ensure_ascii=False,
            )
        }

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    rewrite = rewrite_operator_message_with_provider(
        config=config,
        message=message,
        read_intent_contracts=provider_read_intent_contracts(),
    )

    request_text = str(captured["input"])
    assert "35.6892, 51.3890" not in request_text
    assert "192.168.1.44" not in request_text
    assert "raw ULog" not in request_text
    assert rewrite is not None
    assert rewrite.normalized_message == message
    assert rewrite.language == "fa"
    assert rewrite.read_options == {
        "drone_log_summary": {
            "verify_operation": False,
            "include_unified_logs": False,
            "analyze_latest_ulog": True,
        }
    }
    response_schema = captured["text"]["format"]["schema"]
    assert "read_options" in response_schema["required"]
    assert (
        response_schema["properties"]["read_options"]["properties"][
            "drone_log_summary"
        ]["anyOf"][0]["additionalProperties"]
        is False
    )


def test_provider_log_read_contract_exposes_structured_depth_options():
    contract = next(
        item
        for item in provider_read_intent_contracts()
        if item["id"] == "drone_log_summary"
    )

    assert contract["options_schema"]["required"] == [
        "verify_operation",
        "include_unified_logs",
        "analyze_latest_ulog",
    ]
    assert set(contract["options_schema"]["properties"]) == {
        "verify_operation",
        "include_unified_logs",
        "analyze_latest_ulog",
    }


def test_openai_provider_receives_retrieved_docs_context_for_unexpected_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Context-aware answer."}]}]}

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="The assistant feels robotic; how should I think about the Simurgh chat page and context memory?",
    )

    input_text = str(captured["input"])
    assert record.turn.provider == "openai"
    assert record.audit_event.metadata["query_domain"] in {"ui", "capabilities", "general"}
    assert record.audit_event.metadata["retrieved_context_count"] > 0
    assert "### retrieved." in input_text
    assert "Retrieved query:" in input_text
    assert "Simurgh" in input_text


def test_openai_provider_gets_clarify_mode_for_low_signal_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "I need a clearer MDS question."}]}]}

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="qrxzz blnk",
    )

    assert record.turn.provider == "openai"
    assert record.audit_event.metadata["query_domain"] == "general"
    assert record.audit_event.metadata["query_unclear"] is True
    assert record.audit_event.metadata["response_mode"] == "clarify"
    assert "Public MDS context" in str(captured["input"])


def test_assistant_turn_records_language_profile_without_raw_prompt(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="How many drones do we have configured?",
    )

    profile = record.audit_event.metadata["language_profile"]
    assert profile["language"] == "en"
    assert profile["script"] == "latin"
    assert profile["localization_strategy"] == "english-direct"
    assert record.audit_event.metadata["input_language"] == "en"
    assert "How many drones" not in str(record.audit_event.to_json_dict())


def test_openai_provider_receives_language_profile_guidance(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Réponse."}]}]}

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)

    record = create_assistant_turn(
        sessions=AgentSessionStore(),
        audit=InMemoryAuditSink(),
        actor="operator",
        message="Combien de pages Simurgh sont utiles maintenant ?",
    )

    assert record.turn.provider == "openai"
    assert record.audit_event.metadata["language_profile"]["language"] == "fr"
    input_text = str(captured["input"])
    assert "Simurgh language/tone profile" in input_text
    assert "Detected language: fr" in input_text
    assert "answer in that same language" in input_text


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
            "raw_prompt": "CM4-99 stopped streaming on 192.168.1.10",
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
        metadata={"source": "CM4-99"},
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
