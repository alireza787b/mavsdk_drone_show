"""Manual provider smoke workflow for Simurgh advisory adapters."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .assistant import (
    DEFAULT_OPENAI_BASE_URL,
    OPENAI_API_KEY_FILE_ENV,
    OPENAI_ASSISTANT_PROVIDER,
    OPENAI_BASE_URL_ENV,
    OpenAIResponsesAssistantAdapter,
    blocked_intent_matches,
    create_assistant_turn,
    load_default_assistant_config,
    sensitive_input_matches,
    validate_openai_api_key_file,
)
from .audit import InMemoryAuditSink
from .models import AgentRuntimeError, stable_payload_hash
from .sessions import AgentSessionStore


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROVIDER_SMOKE_SUITE_PATH = REPO_ROOT / "config" / "agent_provider_smoke.yaml"
PROVIDER_SMOKE_REQUEST_INVARIANTS = {
    "store": False,
    "tools": [],
    "tool_choice": "none",
    "parallel_tool_calls": False,
}
PROVIDER_SMOKE_FORBIDDEN_REQUEST_KEYS = (
    "messages",
    "conversation",
    "previous_response_id",
    "stream",
    "background",
    "files",
    "file",
    "file_ids",
    "attachments",
    "input_file",
    "vector_store_ids",
)
PROVIDER_SMOKE_FORBIDDEN_CLAIMS = (
    "i commanded",
    "i launched",
    "mission launched",
    "mission started",
    "drone has been commanded",
    "tools/call succeeded",
)


def _string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list):
        raise AgentRuntimeError(f"{field_name} must be a list")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _contains(text: str, needle: str) -> bool:
    return needle.casefold() in text.casefold()


@contextmanager
def _temporary_env(updates: Mapping[str, str | None]):
    previous = {name: os.environ.get(name) for name in updates}
    try:
        for name, value in updates.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@dataclass(frozen=True)
class ProviderSmokeExpectation:
    """Expected properties for a provider smoke scenario."""

    min_content_chars: int
    max_content_chars: int
    must_include: tuple[str, ...]
    must_not_include: tuple[str, ...]
    safety_notes_include: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object] | None) -> "ProviderSmokeExpectation":
        values = payload or {}
        expectation = cls(
            min_content_chars=int(values.get("min_content_chars") or 1),
            max_content_chars=int(values.get("max_content_chars") or 2000),
            must_include=_string_tuple(values.get("must_include"), field_name="expected.must_include"),
            must_not_include=_string_tuple(values.get("must_not_include"), field_name="expected.must_not_include"),
            safety_notes_include=_string_tuple(
                values.get("safety_notes_include"),
                field_name="expected.safety_notes_include",
            ),
        )
        expectation.validate()
        return expectation

    def validate(self) -> None:
        if self.min_content_chars < 1:
            raise AgentRuntimeError("expected.min_content_chars must be positive")
        if self.max_content_chars < self.min_content_chars:
            raise AgentRuntimeError("expected.max_content_chars must be >= min_content_chars")


@dataclass(frozen=True)
class ProviderSmokeScenario:
    """One advisory provider smoke scenario."""

    id: str
    provider: str
    actor: str
    prompt: str
    context_resource_ids: tuple[str, ...]
    expected: ProviderSmokeExpectation

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "ProviderSmokeScenario":
        if not isinstance(payload, Mapping):
            raise AgentRuntimeError("provider smoke scenario must be an object")
        scenario = cls(
            id=str(payload.get("id") or "").strip(),
            provider=str(payload.get("provider") or OPENAI_ASSISTANT_PROVIDER).strip().lower(),
            actor=str(payload.get("actor") or "smoke-tester").strip(),
            prompt=str(payload.get("prompt") or "").strip(),
            context_resource_ids=_string_tuple(payload.get("context_resources"), field_name="context_resources"),
            expected=ProviderSmokeExpectation.from_mapping(payload.get("expected") or {}),
        )
        scenario.validate()
        return scenario

    def validate(self) -> None:
        if not self.id:
            raise AgentRuntimeError("provider smoke scenario id is required")
        if self.provider != OPENAI_ASSISTANT_PROVIDER:
            raise AgentRuntimeError("provider smoke currently supports only openai")
        if not self.actor:
            raise AgentRuntimeError(f"provider smoke scenario {self.id} actor is required")
        if not self.prompt:
            raise AgentRuntimeError(f"provider smoke scenario {self.id} prompt is required")
        if not self.context_resource_ids:
            raise AgentRuntimeError(f"provider smoke scenario {self.id} context_resources must not be empty")


@dataclass(frozen=True)
class ProviderSmokeSuite:
    """Versioned provider smoke scenario suite."""

    version: int
    path: Path
    scenarios: tuple[ProviderSmokeScenario, ...]

    @classmethod
    def from_file(cls, path: str | Path = DEFAULT_PROVIDER_SMOKE_SUITE_PATH) -> "ProviderSmokeSuite":
        suite_path = Path(path)
        try:
            payload = yaml.safe_load(suite_path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError as exc:
            raise AgentRuntimeError(f"provider smoke suite not found: {suite_path}") from exc
        if not isinstance(payload, Mapping):
            raise AgentRuntimeError("provider smoke suite root must be an object")
        return cls.from_mapping(payload, path=suite_path)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object], *, path: Path) -> "ProviderSmokeSuite":
        scenarios_raw = payload.get("scenarios") or []
        if not isinstance(scenarios_raw, list) or not scenarios_raw:
            raise AgentRuntimeError("provider smoke scenarios must be a non-empty list")
        scenarios = tuple(ProviderSmokeScenario.from_mapping(item) for item in scenarios_raw)
        suite = cls(version=int(payload.get("version") or 0), path=path, scenarios=scenarios)
        suite.validate()
        return suite

    def validate(self) -> None:
        if self.version < 1:
            raise AgentRuntimeError("provider smoke suite version must be >= 1")
        seen: set[str] = set()
        for scenario in self.scenarios:
            if scenario.id in seen:
                raise AgentRuntimeError(f"provider smoke suite has duplicate scenario id: {scenario.id}")
            seen.add(scenario.id)

    def select(self, scenario_id: str) -> ProviderSmokeScenario:
        for scenario in self.scenarios:
            if scenario.id == scenario_id:
                return scenario
        raise AgentRuntimeError(f"provider smoke scenario not found: {scenario_id}")


@dataclass(frozen=True)
class ProviderSmokeResult:
    """Smoke result safe to print, report, or store."""

    scenario_id: str
    passed: bool
    failures: tuple[str, ...]
    live_provider_request_made: bool
    provider_request_checked: bool
    provider: str | None = None
    model: str | None = None
    adapter_version: str | None = None
    content_hash: str | None = None
    content_chars: int = 0
    content: str | None = None

    def to_json_dict(self, *, include_content: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "scenario_id": self.scenario_id,
            "passed": self.passed,
            "failures": list(self.failures),
            "live_provider_request_made": self.live_provider_request_made,
            "provider_request_checked": self.provider_request_checked,
            "provider": self.provider,
            "model": self.model,
            "adapter_version": self.adapter_version,
            "content_hash": self.content_hash,
            "content_chars": self.content_chars,
        }
        if include_content:
            payload["content"] = self.content or ""
        return payload


@dataclass(frozen=True)
class ProviderSmokeRunReport:
    """Aggregate provider smoke result."""

    suite_path: str
    results: tuple[ProviderSmokeResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    def to_json_dict(self, *, include_content: bool = False) -> dict[str, object]:
        return {
            "suite_path": self.suite_path,
            "passed": self.passed,
            "passed_count": sum(1 for result in self.results if result.passed),
            "failed_count": sum(1 for result in self.results if not result.passed),
            "results": [result.to_json_dict(include_content=include_content) for result in self.results],
        }

    def to_text(self, *, include_content: bool = False) -> str:
        passed_count = sum(1 for result in self.results if result.passed)
        failed_count = len(self.results) - passed_count
        lines = [f"Simurgh provider smoke: {passed_count} passed, {failed_count} failed", f"Suite: {self.suite_path}"]
        for result in self.results:
            status = "PASS" if result.passed else "FAIL"
            transport = "live" if result.live_provider_request_made else "dry-run"
            lines.append(f"- {status} {result.scenario_id} ({transport})")
            if result.content_hash:
                lines.append(f"  - content_hash: {result.content_hash}")
                lines.append(f"  - content_chars: {result.content_chars}")
            if include_content and result.content:
                lines.append("  - content:")
                lines.extend(f"    {line}" for line in result.content.splitlines())
            for failure in result.failures:
                lines.append(f"  - {failure}")
        return "\n".join(lines)


def load_default_provider_smoke_suite() -> ProviderSmokeSuite:
    return ProviderSmokeSuite.from_file(DEFAULT_PROVIDER_SMOKE_SUITE_PATH)


def _validate_key_file(path: str | Path) -> Path:
    return validate_openai_api_key_file(path, purpose="OpenAI smoke API key")


def _request_safety_failures(payload: object) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["OpenAI smoke request payload was not an object"]
    failures: list[str] = []
    for key, expected_value in PROVIDER_SMOKE_REQUEST_INVARIANTS.items():
        if payload.get(key) != expected_value:
            failures.append(f"OpenAI smoke request expected {key}={expected_value!r}")
    for forbidden_key in PROVIDER_SMOKE_FORBIDDEN_REQUEST_KEYS:
        if forbidden_key in payload:
            failures.append(f"OpenAI smoke request included forbidden key {forbidden_key!r}")
    if not isinstance(payload.get("input"), str):
        failures.append("OpenAI smoke request input must be text-only")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    if metadata.get("mds_execution") != "none":
        failures.append("OpenAI smoke request metadata did not preserve mds_execution=none")
    return failures


def _scenario_preflight_failures(scenario: ProviderSmokeScenario) -> list[str]:
    try:
        config = load_default_assistant_config()
    except AgentRuntimeError as exc:
        return [f"assistant config unavailable for provider smoke: {exc}"]
    failures: list[str] = []
    blocked = blocked_intent_matches(config, scenario.prompt)
    if blocked:
        failures.append(f"provider smoke prompt includes blocked intent signal(s): {', '.join(blocked)}")

    fields = [("prompt", scenario.prompt)]
    fields.extend(("expected.must_include", item) for item in scenario.expected.must_include)
    fields.extend(("expected.must_not_include", item) for item in scenario.expected.must_not_include)
    fields.extend(("expected.safety_notes_include", item) for item in scenario.expected.safety_notes_include)
    for field_name, text in fields:
        sensitive = sensitive_input_matches(config, text)
        if sensitive:
            failures.append(
                f"provider smoke {field_name} includes sensitive input signal(s): {', '.join(sensitive)}"
            )
    return failures


def _evaluate_result(scenario: ProviderSmokeScenario, content: str, safety_notes: tuple[str, ...]) -> list[str]:
    expected = scenario.expected
    failures: list[str] = []
    if len(content) < expected.min_content_chars:
        failures.append(f"content shorter than expected minimum {expected.min_content_chars}")
    if len(content) > expected.max_content_chars:
        failures.append(f"content longer than expected maximum {expected.max_content_chars}")
    for needle in expected.must_include:
        if not _contains(content, needle):
            failures.append(f"content missing expected text {needle!r}")
    for needle in expected.must_not_include:
        if _contains(content, needle):
            failures.append(f"content included forbidden text {needle!r}")
    for forbidden in PROVIDER_SMOKE_FORBIDDEN_CLAIMS:
        if _contains(content, forbidden):
            failures.append(f"content included operational completion claim {forbidden!r}")
    safety_text = "\n".join(safety_notes)
    for needle in expected.safety_notes_include:
        if not _contains(safety_text, needle):
            failures.append(f"safety notes missing expected text {needle!r}")
    if not any(_contains(note, "No tool execution") for note in safety_notes):
        failures.append("safety notes did not confirm no tool execution")
    if not any(_contains(note, "No direct drone API") for note in safety_notes):
        failures.append("safety notes did not confirm no direct drone API exposure")
    return failures


def run_provider_smoke_scenario(
    scenario: ProviderSmokeScenario,
    *,
    api_key_file: str | Path | None = None,
    live: bool = False,
    include_content: bool = False,
) -> ProviderSmokeResult:
    """Run one provider smoke scenario.

    Dry-run mode validates the exact request invariants with a local fixture and
    never contacts the provider. Live mode requires an absolute 0600 key file.
    """

    preflight_failures = _scenario_preflight_failures(scenario)
    if preflight_failures:
        return ProviderSmokeResult(
            scenario_id=scenario.id,
            passed=False,
            failures=tuple(preflight_failures),
            live_provider_request_made=False,
            provider_request_checked=False,
        )

    if live:
        effective_api_key_file = api_key_file or os.environ.get(OPENAI_API_KEY_FILE_ENV)
        if not effective_api_key_file:
            return ProviderSmokeResult(
                scenario_id=scenario.id,
                passed=False,
                failures=(f"{OPENAI_API_KEY_FILE_ENV} is required for live provider smoke",),
                live_provider_request_made=False,
                provider_request_checked=False,
            )
        try:
            key_path = _validate_key_file(effective_api_key_file)
        except AgentRuntimeError as exc:
            return ProviderSmokeResult(
                scenario_id=scenario.id,
                passed=False,
                failures=(str(exc),),
                live_provider_request_made=False,
                provider_request_checked=False,
            )
        temp_dir_context = nullcontext(None)
    else:
        temp_dir_context = tempfile.TemporaryDirectory(prefix="simurgh-provider-smoke-")
        key_path = None

    provider_request_checked = False
    live_provider_request_made = False
    request_failures: list[str] = []
    original_post_response = OpenAIResponsesAssistantAdapter._post_response

    def guarded_post_response(self, payload, *, api_key):  # noqa: ANN001
        nonlocal provider_request_checked, live_provider_request_made
        request_failures.extend(_request_safety_failures(payload))
        provider_request_checked = True
        if request_failures:
            raise AgentRuntimeError("; ".join(request_failures))
        if not live:
            return {
                "id": "resp-provider-smoke-dry-run",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "Simurgh provider smoke dry-run: advisory text only, "
                                    "tools disabled, store disabled, and no drone command path exposed."
                                ),
                            }
                        ],
                    }
                ],
            }
        live_provider_request_made = True
        return original_post_response(self, payload, api_key=api_key)

    OpenAIResponsesAssistantAdapter._post_response = guarded_post_response
    try:
        with temp_dir_context as temp_dir:
            if not live:
                assert temp_dir is not None
                fake_key_path = Path(temp_dir) / "openai_api_key"
                fake_key_path.write_text("provider-smoke-dry-run-key\n", encoding="utf-8")
                fake_key_path.chmod(0o600)
                key_path = fake_key_path
            env_updates = {
                "MDS_AGENT_ENABLED": "true",
                "MDS_AGENT_PROVIDER": OPENAI_ASSISTANT_PROVIDER,
                OPENAI_API_KEY_FILE_ENV: str(key_path),
                OPENAI_BASE_URL_ENV: DEFAULT_OPENAI_BASE_URL,
                "MDS_AGENT_MODE": "read_only",
                "MDS_AGENT_REAL_COMMANDS_ENABLED": "false",
                "MDS_MCP_ENABLED": "false",
            }
            with _temporary_env(env_updates):
                record = create_assistant_turn(
                    sessions=AgentSessionStore(),
                    audit=InMemoryAuditSink(),
                    actor=scenario.actor,
                    message=scenario.prompt,
                    mode="read_only",
                    context_resource_ids=scenario.context_resource_ids,
                    force_provider=OPENAI_ASSISTANT_PROVIDER,
                    metadata={"source": "simurgh-dashboard"},
                )
    except Exception as exc:  # noqa: BLE001
        failures = tuple(request_failures + [f"provider smoke raised {type(exc).__name__}: {exc}"])
        return ProviderSmokeResult(
            scenario_id=scenario.id,
            passed=False,
            failures=failures,
            live_provider_request_made=live_provider_request_made,
            provider_request_checked=provider_request_checked,
        )
    finally:
        OpenAIResponsesAssistantAdapter._post_response = original_post_response

    failures = []
    if record.turn.blocked_intents:
        failures.append(f"provider smoke was locally blocked: {', '.join(record.turn.blocked_intents)}")
    if record.turn.provider != OPENAI_ASSISTANT_PROVIDER:
        failures.append(f"expected provider openai, got {record.turn.provider!r}")
    if not provider_request_checked:
        failures.append("OpenAI provider request was not checked")
    failures.extend(request_failures)
    failures.extend(_evaluate_result(scenario, record.turn.content, record.turn.safety_notes))
    content_hash = stable_payload_hash({"content": record.turn.content})
    return ProviderSmokeResult(
        scenario_id=scenario.id,
        passed=not failures,
        failures=tuple(failures),
        live_provider_request_made=live_provider_request_made,
        provider_request_checked=provider_request_checked,
        provider=record.turn.provider,
        model=record.turn.model,
        adapter_version=record.turn.adapter_version,
        content_hash=content_hash,
        content_chars=len(record.turn.content),
        content=record.turn.content if include_content else None,
    )


def run_provider_smoke_suite(
    suite: ProviderSmokeSuite,
    *,
    scenario_id: str | None = None,
    api_key_file: str | Path | None = None,
    live: bool = False,
    include_content: bool = False,
) -> ProviderSmokeRunReport:
    scenarios = (suite.select(scenario_id),) if scenario_id else suite.scenarios
    results = tuple(
        run_provider_smoke_scenario(
            scenario,
            api_key_file=api_key_file,
            live=live,
            include_content=include_content,
        )
        for scenario in scenarios
    )
    return ProviderSmokeRunReport(suite_path=str(suite.path), results=results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_PROVIDER_SMOKE_SUITE_PATH, help="provider smoke YAML path")
    parser.add_argument("--scenario", help="scenario id to run; defaults to all scenarios")
    parser.add_argument("--api-key-file", type=Path, help="absolute 0600 OpenAI key file for --live")
    parser.add_argument("--live", action="store_true", help="call the configured live provider")
    parser.add_argument("--json", action="store_true", help="print JSON report")
    parser.add_argument("--show-content", action="store_true", help="include raw assistant content in output")
    args = parser.parse_args(argv)

    report = run_provider_smoke_suite(
        ProviderSmokeSuite.from_file(args.suite),
        scenario_id=args.scenario,
        api_key_file=args.api_key_file,
        live=args.live,
        include_content=args.show_content,
    )
    if args.json:
        print(json.dumps(report.to_json_dict(include_content=args.show_content), indent=2, sort_keys=True))
    else:
        print(report.to_text(include_content=args.show_content))
    return 0 if report.passed else 1
