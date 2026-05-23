from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime import (
    OpenAIResponsesAssistantAdapter,
    ProviderSmokeSuite,
    load_default_context_index,
    load_default_provider_smoke_suite,
    run_provider_smoke_scenario,
    run_provider_smoke_suite,
)


def test_default_provider_smoke_suite_runs_dry_run_without_key(monkeypatch):
    monkeypatch.delenv("MDS_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("MDS_AGENT_OPENAI_API_KEY_FILE", raising=False)

    suite = load_default_provider_smoke_suite()
    report = run_provider_smoke_suite(suite)

    assert report.passed is True
    assert len(report.results) == len(suite.scenarios)
    result = report.results[0]
    assert result.live_provider_request_made is False
    assert result.provider_request_checked is True
    assert result.provider == "openai"
    assert result.content_hash
    assert result.content_chars > 40
    assert result.content is None


def test_provider_smoke_json_omits_content_by_default():
    report = run_provider_smoke_suite(load_default_provider_smoke_suite())

    payload = report.to_json_dict()

    assert payload["passed"] is True
    assert "content" not in payload["results"][0]


def test_provider_smoke_live_requires_absolute_restricted_key_file(monkeypatch, tmp_path):
    monkeypatch.delenv("MDS_AGENT_OPENAI_API_KEY_FILE", raising=False)
    scenario = load_default_provider_smoke_suite().scenarios[0]

    missing = run_provider_smoke_scenario(scenario, live=True)
    relative = run_provider_smoke_scenario(scenario, api_key_file=Path("relative-key"), live=True)
    loose_key = tmp_path / "openai_api_key"
    loose_key.write_text("test-openai-key\n", encoding="utf-8")
    loose_key.chmod(0o644)
    loose = run_provider_smoke_scenario(scenario, api_key_file=loose_key, live=True)

    assert missing.passed is False
    assert "required for live provider smoke" in missing.failures[0]
    assert relative.passed is False
    assert "absolute path" in relative.failures[0]
    assert loose.passed is False
    assert "must not be readable" in loose.failures[0]


def test_provider_smoke_live_accepts_env_key_file(monkeypatch, tmp_path):
    scenario = load_default_provider_smoke_suite().scenarios[0]
    api_key_file = tmp_path / "openai_api_key"
    api_key_file.write_text("test-openai-key\n", encoding="utf-8")
    api_key_file.chmod(0o600)

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                "Simurgh advisory response only: tools disabled, "
                                "store=false, and no direct drone API is exposed."
                            ),
                        }
                    ],
                }
            ]
        }

    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)

    result = run_provider_smoke_scenario(scenario, live=True)

    assert result.passed is True
    assert result.live_provider_request_made is True


def test_provider_smoke_live_uses_guarded_request_without_tools(monkeypatch, tmp_path):
    scenario = load_default_provider_smoke_suite().scenarios[0]
    api_key_file = tmp_path / "openai_api_key"
    api_key_file.write_text("test-openai-key\n", encoding="utf-8")
    api_key_file.chmod(0o600)
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        captured["api_key"] = api_key
        return {
            "id": "resp-smoke-live-test",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                "Simurgh advisory response only: tools disabled, "
                                "store=false, and no direct drone API is exposed."
                            ),
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)

    result = run_provider_smoke_scenario(scenario, api_key_file=api_key_file, live=True)

    assert result.passed is True
    assert result.live_provider_request_made is True
    assert result.provider_request_checked is True
    assert captured["api_key"] == "test-openai-key"
    assert captured["store"] is False
    assert captured["tools"] == []
    assert captured["tool_choice"] == "none"
    assert captured["parallel_tool_calls"] is False
    assert "stream" not in captured
    assert "background" not in captured
    assert "file_ids" not in captured
    assert "messages" not in captured
    assert "conversation" not in captured
    assert "previous_response_id" not in captured
    assert captured["metadata"]["mds_execution"] == "none"


def test_provider_smoke_fails_closed_on_request_invariant_regression(monkeypatch):
    scenario = load_default_provider_smoke_suite().scenarios[0]
    original_request_payload = OpenAIResponsesAssistantAdapter._request_payload

    def unsafe_request_payload(self, *, message, context_documents):  # noqa: ANN001
        payload = original_request_payload(self, message=message, context_documents=context_documents)
        payload["store"] = True
        payload["tools"] = [{"type": "function", "name": "unsafe"}]
        payload["tool_choice"] = "auto"
        payload["previous_response_id"] = "resp_unsafe"
        payload["stream"] = True
        payload["background"] = True
        payload["file_ids"] = ["file_unsafe"]
        payload["metadata"]["mds_execution"] = "tools"
        return payload

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_request_payload", unsafe_request_payload)

    result = run_provider_smoke_scenario(scenario)

    assert result.passed is False
    assert result.provider_request_checked is True
    failures = "\n".join(result.failures)
    assert "store=False" in failures
    assert "tools=[]" in failures
    assert "tool_choice='none'" in failures
    assert "previous_response_id" in failures
    assert "stream" in failures
    assert "background" in failures
    assert "file_ids" in failures
    assert "mds_execution=none" in failures


def test_provider_smoke_rejects_sensitive_prompt_before_provider(monkeypatch, tmp_path):
    suite_path = tmp_path / "provider-smoke.yaml"
    payload = {
        "version": 1,
        "scenarios": [
            {
                "id": "sensitive_prompt_regression",
                "provider": "openai",
                "actor": "smoke-tester",
                "prompt": (
                    "Authorization: "
                    "Bearer "
                    "mds_test_secret_12345 should not leave the GCS."
                ),
                "context_resources": ["simurgh.safety_policy"],
                "expected": {"min_content_chars": 1},
            }
        ],
    }
    suite_path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    def fail_post(self, payload, *, api_key):  # noqa: ANN001
        raise AssertionError("provider should not be called for a sensitive smoke prompt")

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fail_post)

    report = run_provider_smoke_suite(ProviderSmokeSuite.from_file(suite_path))

    assert report.passed is False
    assert report.results[0].provider_request_checked is False
    assert "sensitive input signal" in "\n".join(report.results[0].failures)


def test_provider_smoke_rejects_sensitive_expected_text_before_report(tmp_path):
    suite_path = tmp_path / "provider-smoke.yaml"
    payload = {
        "version": 1,
        "scenarios": [
            {
                "id": "sensitive_expected_regression",
                "provider": "openai",
                "actor": "smoke-tester",
                "prompt": "Summarize the safety policy.",
                "context_resources": ["simurgh.safety_policy"],
                "expected": {"must_include": ["AIRFRAME-01"]},
            }
        ],
    }
    suite_path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    report = run_provider_smoke_suite(ProviderSmokeSuite.from_file(suite_path))

    assert report.passed is False
    assert report.results[0].provider_request_checked is False
    assert "expected.must_include" in "\n".join(report.results[0].failures)
    assert "AIRFRAME-01" not in report.to_text()


def test_provider_smoke_text_report_can_include_content_when_requested():
    report = run_provider_smoke_suite(load_default_provider_smoke_suite(), include_content=True)

    text = report.to_text(include_content=True)

    assert "content:" in text
    assert "Simurgh provider smoke dry-run" in text


def test_provider_smoke_suite_is_indexed_as_public_context():
    index = load_default_context_index()
    suite = load_default_provider_smoke_suite()

    assert index.require("simurgh.provider_smoke_workflow").sensitivity == "public"
    assert index.require("simurgh.provider_smoke_suite").path == Path("config/agent_provider_smoke.yaml")
    assert suite.version == 1
    assert suite.scenarios[0].id == "openai_basic_advisory_sanity"
