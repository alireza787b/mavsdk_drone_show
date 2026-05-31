"""Provider-neutral assistant scaffolding for Simurgh Operator."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx
import yaml

from .audit import InMemoryAuditSink
from .context import AgentContextIndex, load_default_context_index
from .language import LanguageProfile, detect_language_profile, provider_language_guidance
from .mds_read_tools import (
    READ_TOOL_ADAPTER_VERSION,
    READ_TOOL_MODEL,
    READ_TOOL_PROVIDER,
    MdsReadToolAnswer,
    answer_mds_read_only_question,
    classify_mds_read_intent,
    infer_mds_read_topic,
    is_safe_blocked_term_read_only_intent,
)
from .models import AgentRuntimeError, AgentSession, AuditEvent, ContextResource, stable_payload_hash, utc_now
from .policy import load_default_policy
from .query_adaptation import adapt_operator_query
from .query_understanding import AssistantQueryPlan, build_assistant_query_plan
from .tool_executor import ADVISORY_ANSWER_TOOL_ID, execute_policy_allowed_advisory_tool
from .retrieval import load_default_retriever, search_retriever_queries
from .sessions import AgentSessionStore, sanitize_session_metadata


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ASSISTANT_CONFIG_PATH = REPO_ROOT / "config" / "agent_assistant.yaml"
DEFAULT_ASSISTANT_HISTORY_PATH = REPO_ROOT / "runtime_data" / "simurgh" / "assistant_turns.jsonl"
ASSISTANT_CONFIG_ENV = "MDS_AGENT_ASSISTANT_FILE"
ASSISTANT_HISTORY_FILE_ENV = "MDS_AGENT_ASSISTANT_HISTORY_FILE"
ASSISTANT_HISTORY_MAX_AGE_DAYS_ENV = "MDS_AGENT_ASSISTANT_HISTORY_MAX_AGE_DAYS"
ASSISTANT_HISTORY_MAX_RECORDS_ENV = "MDS_AGENT_ASSISTANT_HISTORY_MAX_RECORDS"
AGENT_PROVIDER_ENV = "MDS_AGENT_PROVIDER"
SUPPORTED_ASSISTANT_PROVIDER = "mock"
OPENAI_ASSISTANT_PROVIDER = "openai"
SUPPORTED_ASSISTANT_PROVIDERS = (SUPPORTED_ASSISTANT_PROVIDER, OPENAI_ASSISTANT_PROVIDER)
OPENAI_API_KEY_FILE_ENV = "MDS_AGENT_OPENAI_API_KEY_FILE"
OPENAI_MODEL_ENV = "MDS_AGENT_OPENAI_MODEL"
OPENAI_BASE_URL_ENV = "MDS_AGENT_OPENAI_BASE_URL"
OPENAI_TIMEOUT_SECONDS_ENV = "MDS_AGENT_OPENAI_TIMEOUT_SEC"
OPENAI_MAX_OUTPUT_TOKENS_ENV = "MDS_AGENT_OPENAI_MAX_OUTPUT_TOKENS"
OPENAI_REASONING_EFFORT_ENV = "MDS_AGENT_OPENAI_REASONING_EFFORT"
OPENAI_TEXT_VERBOSITY_ENV = "MDS_AGENT_OPENAI_TEXT_VERBOSITY"
OPENAI_WEB_SEARCH_ENABLED_ENV = "MDS_AGENT_WEB_SEARCH_ENABLED"
OPENAI_WEB_SEARCH_CONTEXT_SIZE_ENV = "MDS_AGENT_WEB_SEARCH_CONTEXT_SIZE"
OPENAI_WEB_SEARCH_EXTERNAL_ACCESS_ENV = "MDS_AGENT_WEB_SEARCH_EXTERNAL_ACCESS"
OPENAI_WEB_SEARCH_ALLOWED_DOMAINS_ENV = "MDS_AGENT_WEB_SEARCH_ALLOWED_DOMAINS"
OPENAI_WEB_SEARCH_BLOCKED_DOMAINS_ENV = "MDS_AGENT_WEB_SEARCH_BLOCKED_DOMAINS"
DEFAULT_ASSISTANT_HISTORY_MAX_AGE_DAYS = 30
DEFAULT_ASSISTANT_HISTORY_MAX_RECORDS = 200
ASSISTANT_HISTORY_SCHEMA_VERSION = 1
MOCK_ASSISTANT_ADAPTER_VERSION = "mock-v1"
MOCK_ASSISTANT_MODEL = "mock-local"
OPENAI_ASSISTANT_ADAPTER_VERSION = "openai-responses-v1"
DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
ALLOWED_OPENAI_BASE_URLS = (DEFAULT_OPENAI_BASE_URL,)
DEFAULT_OPENAI_TIMEOUT_SECONDS = 30.0
DEFAULT_OPENAI_MAX_OUTPUT_TOKENS = 900
DEFAULT_OPENAI_REASONING_EFFORT = "medium"
DEFAULT_OPENAI_TEXT_VERBOSITY = "low"
DEFAULT_OPENAI_WEB_SEARCH_CONTEXT_SIZE = "medium"
DEFAULT_RETRIEVED_CONTEXT_LIMIT = 4
LOCAL_PROVIDER_COMPOSITION_DISABLED_INTENTS = frozenset({"registry_domain_tool_summary"})
DEFAULT_RETRIEVED_CONTEXT_MAX_CHARS = 2200
DEFAULT_RETRIEVED_CONTEXT_BUDGET_BYTES = 14000
SUPPORTED_OPENAI_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh"}
SUPPORTED_OPENAI_TEXT_VERBOSITY = {"low", "medium", "high"}
SUPPORTED_OPENAI_WEB_SEARCH_CONTEXT_SIZE = {"low", "medium", "high"}


def _string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list):
        raise AgentRuntimeError(f"{field_name} must be a list")
    return tuple(str(item).strip() for item in value if str(item).strip())


@dataclass(frozen=True)
class SensitiveInputPattern:
    """Configurable regex used to block private field evidence before providers."""

    label: str
    regex: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "SensitiveInputPattern":
        pattern = cls(
            label=str(payload.get("label") or "").strip(),
            regex=str(payload.get("regex") or "").strip(),
        )
        pattern.validate()
        return pattern

    def validate(self) -> None:
        if not self.label:
            raise AgentRuntimeError("assistant sensitive_input_patterns.label is required")
        if not self.regex:
            raise AgentRuntimeError("assistant sensitive_input_patterns.regex is required")
        try:
            re.compile(self.regex, re.IGNORECASE)
        except re.error as exc:
            raise AgentRuntimeError(f"assistant sensitive input regex is invalid: {self.label}") from exc

    def matches(self, message: str) -> bool:
        return re.search(self.regex, message, flags=re.IGNORECASE) is not None


def _sensitive_input_patterns(value: object) -> tuple[SensitiveInputPattern, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list):
        raise AgentRuntimeError("sensitive_input_patterns must be a list")
    patterns = []
    for item in value:
        if not isinstance(item, Mapping):
            raise AgentRuntimeError("each sensitive_input_patterns item must be an object")
        patterns.append(SensitiveInputPattern.from_mapping(item))
    return tuple(patterns)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise AgentRuntimeError(f"{name} must be an integer") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise AgentRuntimeError(f"{name} must be a number") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return _coerce_bool(raw, field_name=name)


def _coerce_bool(value: object, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise AgentRuntimeError(f"{field_name} must be a boolean")


def _env_csv_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _string_or_csv_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise AgentRuntimeError(f"{field_name} must be a list or comma-separated string")


def validate_openai_api_key_file(
    path: str | Path,
    *,
    purpose: str = "OpenAI assistant API key",
) -> Path:
    """Validate a file-backed OpenAI key path before the key is read."""

    key_path = Path(path)
    if not key_path.is_absolute():
        raise AgentRuntimeError(f"{OPENAI_API_KEY_FILE_ENV} must be an absolute path")
    try:
        key_stat = key_path.stat()
    except OSError as exc:
        raise AgentRuntimeError(f"{purpose} file is not readable: {key_path}") from exc
    if not stat.S_ISREG(key_stat.st_mode):
        raise AgentRuntimeError(f"{purpose} path must be a regular file")
    if key_stat.st_mode & 0o077:
        raise AgentRuntimeError(f"{purpose} file must not be readable, writable, or executable by group/other")
    if key_stat.st_uid not in {0, os.geteuid()}:
        raise AgentRuntimeError(f"{purpose} file must be owned by root or the current service user")
    if not key_path.read_text(encoding="utf-8").strip():
        raise AgentRuntimeError(f"{purpose} file is empty")
    return key_path


@dataclass(frozen=True)
class AssistantResponseTemplate:
    """Editable deterministic response text for the mock assistant."""

    preamble: str
    blocked_action_notice: str
    sensitive_input_notice: str
    no_action_notice: str
    suggested_next_steps: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "AssistantResponseTemplate":
        return cls(
            preamble=str(payload.get("preamble") or "").strip(),
            blocked_action_notice=str(payload.get("blocked_action_notice") or "").strip(),
            sensitive_input_notice=str(payload.get("sensitive_input_notice") or "").strip(),
            no_action_notice=str(payload.get("no_action_notice") or "").strip(),
            suggested_next_steps=_string_tuple(
                payload.get("suggested_next_steps"),
                field_name="response_template.suggested_next_steps",
            ),
        )

    def validate(self) -> None:
        if not self.preamble:
            raise AgentRuntimeError("assistant response preamble is required")
        if not self.blocked_action_notice:
            raise AgentRuntimeError("assistant blocked_action_notice is required")
        if not self.sensitive_input_notice:
            raise AgentRuntimeError("assistant sensitive_input_notice is required")
        if not self.no_action_notice:
            raise AgentRuntimeError("assistant no_action_notice is required")


@dataclass(frozen=True)
class OpenAIWebSearchConfig:
    """Responses API web-search settings for public/general assistant prompts."""

    enabled: bool = False
    search_context_size: str = DEFAULT_OPENAI_WEB_SEARCH_CONTEXT_SIZE
    external_web_access: bool = True
    allowed_domains: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object] | None) -> "OpenAIWebSearchConfig":
        values = dict(payload or {})
        config = cls(
            enabled=_coerce_bool(
                values.get("enabled", False),
                field_name="providers.openai.web_search.enabled",
            ),
            search_context_size=str(values.get("search_context_size") or DEFAULT_OPENAI_WEB_SEARCH_CONTEXT_SIZE)
            .strip()
            .lower(),
            external_web_access=_coerce_bool(
                values.get("external_web_access", True),
                field_name="providers.openai.web_search.external_web_access",
            ),
            allowed_domains=_string_or_csv_tuple(
                values.get("allowed_domains"),
                field_name="providers.openai.web_search.allowed_domains",
            ),
            blocked_domains=_string_or_csv_tuple(
                values.get("blocked_domains"),
                field_name="providers.openai.web_search.blocked_domains",
            ),
        )
        return config.with_env_overrides()

    def with_env_overrides(self) -> "OpenAIWebSearchConfig":
        updated = OpenAIWebSearchConfig(
            enabled=_env_bool(OPENAI_WEB_SEARCH_ENABLED_ENV, self.enabled),
            search_context_size=os.environ.get(
                OPENAI_WEB_SEARCH_CONTEXT_SIZE_ENV,
                self.search_context_size,
            ).strip().lower()
            or self.search_context_size,
            external_web_access=_env_bool(
                OPENAI_WEB_SEARCH_EXTERNAL_ACCESS_ENV,
                self.external_web_access,
            ),
            allowed_domains=_env_csv_tuple(OPENAI_WEB_SEARCH_ALLOWED_DOMAINS_ENV, self.allowed_domains),
            blocked_domains=_env_csv_tuple(OPENAI_WEB_SEARCH_BLOCKED_DOMAINS_ENV, self.blocked_domains),
        )
        updated.validate()
        return updated

    def validate(self) -> None:
        if self.search_context_size not in SUPPORTED_OPENAI_WEB_SEARCH_CONTEXT_SIZE:
            raise AgentRuntimeError("OpenAI web search context size is not supported")
        if self.allowed_domains and self.blocked_domains:
            raise AgentRuntimeError("OpenAI web search cannot set both allowed_domains and blocked_domains")
        for label, domains in (
            ("allowed_domains", self.allowed_domains),
            ("blocked_domains", self.blocked_domains),
        ):
            if len(domains) > 100:
                raise AgentRuntimeError(f"OpenAI web search {label} supports at most 100 domains")
            for domain in domains:
                _validate_web_search_domain(domain, field_name=label)

    def tool_payload(self) -> dict[str, Any]:
        tool: dict[str, Any] = {
            "type": "web_search",
            "search_context_size": self.search_context_size,
            "external_web_access": self.external_web_access,
        }
        if self.allowed_domains:
            tool["filters"] = {"allowed_domains": list(self.allowed_domains)}
        elif self.blocked_domains:
            tool["filters"] = {"blocked_domains": list(self.blocked_domains)}
        return tool


def _validate_web_search_domain(domain: str, *, field_name: str) -> None:
    value = str(domain or "").strip().lower()
    if not value:
        raise AgentRuntimeError(f"OpenAI web search {field_name} includes an empty domain")
    if "://" in value or "/" in value or "?" in value or "#" in value:
        raise AgentRuntimeError(f"OpenAI web search {field_name} must contain bare domains only")
    if len(value) > 253 or not re.fullmatch(r"[a-z0-9*.-]+", value):
        raise AgentRuntimeError(f"OpenAI web search {field_name} includes an invalid domain")


@dataclass(frozen=True)
class OpenAIProviderConfig:
    """OpenAI Responses API settings for advisory assistant turns."""

    model: str = DEFAULT_OPENAI_MODEL
    api_key_file: str = ""
    base_url: str = DEFAULT_OPENAI_BASE_URL
    timeout_seconds: float = DEFAULT_OPENAI_TIMEOUT_SECONDS
    max_output_tokens: int = DEFAULT_OPENAI_MAX_OUTPUT_TOKENS
    reasoning_effort: str = DEFAULT_OPENAI_REASONING_EFFORT
    text_verbosity: str = DEFAULT_OPENAI_TEXT_VERBOSITY
    store: bool = False
    web_search: OpenAIWebSearchConfig = field(default_factory=OpenAIWebSearchConfig)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object] | None) -> "OpenAIProviderConfig":
        values = dict(payload or {})
        if values.get("store") not in (None, "", False):
            raise AgentRuntimeError("OpenAI assistant store is fixed false in this slice")
        config = cls(
            model=str(values.get("model") or DEFAULT_OPENAI_MODEL).strip(),
            api_key_file=str(values.get("api_key_file") or "").strip(),
            base_url=str(values.get("base_url") or DEFAULT_OPENAI_BASE_URL).strip().rstrip("/"),
            timeout_seconds=float(values.get("timeout_seconds") or DEFAULT_OPENAI_TIMEOUT_SECONDS),
            max_output_tokens=int(values.get("max_output_tokens") or DEFAULT_OPENAI_MAX_OUTPUT_TOKENS),
            reasoning_effort=str(values.get("reasoning_effort") or DEFAULT_OPENAI_REASONING_EFFORT).strip().lower(),
            text_verbosity=str(values.get("text_verbosity") or DEFAULT_OPENAI_TEXT_VERBOSITY).strip().lower(),
            web_search=OpenAIWebSearchConfig.from_mapping(
                values.get("web_search") if isinstance(values.get("web_search"), Mapping) else None
            ),
        )
        return config.with_env_overrides()

    def with_env_overrides(self) -> "OpenAIProviderConfig":
        updated = OpenAIProviderConfig(
            model=os.environ.get(OPENAI_MODEL_ENV, self.model).strip() or self.model,
            api_key_file=os.environ.get(OPENAI_API_KEY_FILE_ENV, self.api_key_file).strip(),
            base_url=os.environ.get(OPENAI_BASE_URL_ENV, self.base_url).strip().rstrip("/") or self.base_url,
            timeout_seconds=_env_float(OPENAI_TIMEOUT_SECONDS_ENV, self.timeout_seconds),
            max_output_tokens=_env_int(OPENAI_MAX_OUTPUT_TOKENS_ENV, self.max_output_tokens),
            reasoning_effort=os.environ.get(OPENAI_REASONING_EFFORT_ENV, self.reasoning_effort).strip().lower()
            or self.reasoning_effort,
            text_verbosity=os.environ.get(OPENAI_TEXT_VERBOSITY_ENV, self.text_verbosity).strip().lower()
            or self.text_verbosity,
            web_search=self.web_search.with_env_overrides(),
        )
        updated.validate()
        return updated

    def validate(self) -> None:
        if not self.model:
            raise AgentRuntimeError("OpenAI assistant model is required")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise AgentRuntimeError("OpenAI assistant base_url must be an absolute HTTPS URL")
        if parsed.query or parsed.fragment or parsed.params:
            raise AgentRuntimeError("OpenAI assistant base_url must not include query strings or fragments")
        if self.base_url not in ALLOWED_OPENAI_BASE_URLS:
            allowed = ", ".join(ALLOWED_OPENAI_BASE_URLS)
            raise AgentRuntimeError(f"OpenAI assistant base_url is pinned to: {allowed}")
        if self.timeout_seconds <= 0:
            raise AgentRuntimeError("OpenAI assistant timeout_seconds must be positive")
        if self.max_output_tokens <= 0:
            raise AgentRuntimeError("OpenAI assistant max_output_tokens must be positive")
        if self.reasoning_effort not in SUPPORTED_OPENAI_REASONING_EFFORTS:
            raise AgentRuntimeError("OpenAI assistant reasoning_effort is not supported")
        if self.text_verbosity not in SUPPORTED_OPENAI_TEXT_VERBOSITY:
            raise AgentRuntimeError("OpenAI assistant text_verbosity is not supported")
        if self.store is not False:
            raise AgentRuntimeError("OpenAI assistant store is fixed false in this slice")
        self.web_search.validate()

    def read_api_key(self) -> str:
        if not self.api_key_file:
            raise AgentRuntimeError(f"{OPENAI_API_KEY_FILE_ENV} is required when MDS_AGENT_PROVIDER=openai")
        path = validate_openai_api_key_file(self.api_key_file)
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise AgentRuntimeError(f"OpenAI assistant API key file is not readable: {path}") from exc
        if not value:
            raise AgentRuntimeError("OpenAI assistant API key file is empty")
        return value


@dataclass(frozen=True)
class AssistantConfig:
    """Versioned assistant settings loaded from `config/agent_assistant.yaml`."""

    version: int
    path: Path
    provider: str
    max_message_chars: int
    max_context_bytes: int
    default_context_resource_ids: tuple[str, ...]
    blocked_intent_terms: tuple[str, ...]
    sensitive_input_terms: tuple[str, ...]
    sensitive_input_patterns: tuple[SensitiveInputPattern, ...]
    response_template: AssistantResponseTemplate
    provider_instructions: str
    provider_input_template: str
    openai: OpenAIProviderConfig

    @classmethod
    def from_file(cls, path: str | Path = DEFAULT_ASSISTANT_CONFIG_PATH) -> "AssistantConfig":
        config_path = Path(path)
        try:
            payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError as exc:
            raise AgentRuntimeError(f"assistant config not found: {config_path}") from exc
        if not isinstance(payload, dict):
            raise AgentRuntimeError("assistant config root must be an object")
        return cls.from_mapping(payload, path=config_path)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object], *, path: Path | None = None) -> "AssistantConfig":
        version = int(payload.get("version") or 0)
        if version < 1:
            raise AgentRuntimeError("assistant config version must be >= 1")
        response_template_raw = payload.get("response_template") or {}
        if not isinstance(response_template_raw, dict):
            raise AgentRuntimeError("assistant response_template must be an object")
        providers_raw = payload.get("providers") or {}
        if not isinstance(providers_raw, dict):
            raise AgentRuntimeError("assistant providers must be an object")
        openai_raw = providers_raw.get(OPENAI_ASSISTANT_PROVIDER) or {}
        if not isinstance(openai_raw, dict):
            raise AgentRuntimeError("assistant providers.openai must be an object")

        config = cls(
            version=version,
            path=path or DEFAULT_ASSISTANT_CONFIG_PATH,
            provider=str(payload.get("provider") or SUPPORTED_ASSISTANT_PROVIDER).strip().lower(),
            max_message_chars=int(payload.get("max_message_chars") or 4000),
            max_context_bytes=int(payload.get("max_context_bytes") or 64000),
            default_context_resource_ids=_string_tuple(
                payload.get("default_context_resource_ids"),
                field_name="default_context_resource_ids",
            ),
            blocked_intent_terms=_string_tuple(payload.get("blocked_intent_terms"), field_name="blocked_intent_terms"),
            sensitive_input_terms=_string_tuple(
                payload.get("sensitive_input_terms"),
                field_name="sensitive_input_terms",
            ),
            sensitive_input_patterns=_sensitive_input_patterns(payload.get("sensitive_input_patterns")),
            response_template=AssistantResponseTemplate.from_mapping(response_template_raw),
            provider_instructions=str(payload.get("provider_instructions") or "").strip(),
            provider_input_template=str(payload.get("provider_input_template") or "").strip(),
            openai=OpenAIProviderConfig.from_mapping(openai_raw),
        )
        config.validate()
        return config.with_env_provider()

    def validate(self) -> None:
        if self.provider not in SUPPORTED_ASSISTANT_PROVIDERS:
            raise AgentRuntimeError(f"assistant provider {self.provider!r} is not implemented in this slice")
        if self.max_message_chars <= 0:
            raise AgentRuntimeError("assistant max_message_chars must be positive")
        if self.max_context_bytes <= 0:
            raise AgentRuntimeError("assistant max_context_bytes must be positive")
        if not self.default_context_resource_ids:
            raise AgentRuntimeError("assistant default_context_resource_ids must not be empty")
        if not self.sensitive_input_terms:
            raise AgentRuntimeError("assistant sensitive_input_terms must not be empty")
        if not self.sensitive_input_patterns:
            raise AgentRuntimeError("assistant sensitive_input_patterns must not be empty")
        if not self.provider_instructions:
            raise AgentRuntimeError("assistant provider_instructions is required")
        if not self.provider_input_template:
            raise AgentRuntimeError("assistant provider_input_template is required")
        for placeholder in ("{message}", "{context_blocks}"):
            if placeholder not in self.provider_input_template:
                raise AgentRuntimeError(f"assistant provider_input_template must include {placeholder}")
        self.response_template.validate()
        self.openai.validate()

    def with_env_provider(self) -> "AssistantConfig":
        provider = os.environ.get(AGENT_PROVIDER_ENV, self.provider).strip().lower() or self.provider
        if provider == self.provider:
            return self
        updated = AssistantConfig(
            version=self.version,
            path=self.path,
            provider=provider,
            max_message_chars=self.max_message_chars,
            max_context_bytes=self.max_context_bytes,
            default_context_resource_ids=self.default_context_resource_ids,
            blocked_intent_terms=self.blocked_intent_terms,
            sensitive_input_terms=self.sensitive_input_terms,
            sensitive_input_patterns=self.sensitive_input_patterns,
            response_template=self.response_template,
            provider_instructions=self.provider_instructions,
            provider_input_template=self.provider_input_template,
            openai=self.openai,
        )
        updated.validate()
        return updated


@dataclass(frozen=True)
class AssistantContextDocument:
    """Context document loaded from the versioned context index."""

    id: str
    title: str
    uri: str
    mime_type: str
    summary: str
    tags: tuple[str, ...]
    content_hash: str
    text: str

    @classmethod
    def from_resource(
        cls,
        *,
        index: AgentContextIndex,
        resource: ContextResource,
        text: str,
    ) -> "AssistantContextDocument":
        return cls(
            id=resource.id,
            title=resource.title,
            uri=f"mds://simurgh/context/{resource.id}",
            mime_type=resource.mime_type,
            summary=resource.summary,
            tags=resource.tags,
            content_hash=resource.content_hash(repo_root=index.repo_root),
            text=text,
        )

    def public_metadata(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "uri": self.uri,
            "mime_type": self.mime_type,
            "summary": self.summary,
            "tags": list(self.tags),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class AssistantTurnResult:
    """Deterministic assistant turn result."""

    id: str
    created_at: str
    provider: str
    model: str
    adapter_version: str
    content: str
    context_documents: tuple[AssistantContextDocument, ...]
    blocked_intents: tuple[str, ...]
    safety_notes: tuple[str, ...]


@dataclass(frozen=True)
class AssistantTurnRecord:
    """Assistant turn plus session and audit metadata."""

    session: AgentSession
    turn: AssistantTurnResult
    audit_event: AuditEvent


@dataclass(frozen=True)
class AssistantTurnHistoryRecord:
    """Persisted assistant transcript record kept outside audit and MCP resources."""

    schema_version: int
    id: str
    created_at: str
    provider: str
    model: str
    adapter_version: str
    session_id: str
    actor: str
    mode: str
    message: str
    content: str
    context_resources: tuple[dict[str, Any], ...]
    blocked_intents: tuple[str, ...]
    safety_notes: tuple[str, ...]
    audit_event_id: str
    message_hash: str
    message_chars: int

    @classmethod
    def from_turn_record(
        cls,
        *,
        record: AssistantTurnRecord,
        message: str,
    ) -> "AssistantTurnHistoryRecord":
        normalized_message = message.strip()
        return cls(
            schema_version=ASSISTANT_HISTORY_SCHEMA_VERSION,
            id=record.turn.id,
            created_at=record.turn.created_at,
            provider=record.turn.provider,
            model=record.turn.model,
            adapter_version=record.turn.adapter_version,
            session_id=record.session.id,
            actor=record.session.actor,
            mode=record.session.mode,
            message="",
            content="",
            context_resources=tuple(document.public_metadata() for document in record.turn.context_documents),
            blocked_intents=record.turn.blocked_intents,
            safety_notes=record.turn.safety_notes,
            audit_event_id=record.audit_event.id,
            message_hash=stable_payload_hash({"message": normalized_message}),
            message_chars=len(normalized_message),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "AssistantTurnHistoryRecord":
        return cls(
            schema_version=int(payload.get("schema_version") or 0),
            id=str(payload.get("id") or "").strip(),
            created_at=str(payload.get("created_at") or "").strip(),
            provider=str(payload.get("provider") or "").strip(),
            model=str(payload.get("model") or "").strip(),
            adapter_version=str(payload.get("adapter_version") or "").strip(),
            session_id=str(payload.get("session_id") or "").strip(),
            actor=str(payload.get("actor") or "").strip(),
            mode=str(payload.get("mode") or "").strip(),
            message="",
            content="",
            context_resources=tuple(dict(item) for item in payload.get("context_resources") or ()),
            blocked_intents=tuple(str(item) for item in payload.get("blocked_intents") or ()),
            safety_notes=tuple(str(item) for item in payload.get("safety_notes") or ()),
            audit_event_id=str(payload.get("audit_event_id") or "").strip(),
            message_hash=str(payload.get("message_hash") or "").strip(),
            message_chars=int(payload.get("message_chars") or 0),
        )

    def validate(self) -> None:
        if self.schema_version != ASSISTANT_HISTORY_SCHEMA_VERSION:
            raise AgentRuntimeError(f"unsupported assistant history schema version: {self.schema_version}")
        missing = [
            name
            for name in (
                "id",
                "created_at",
                "provider",
                "model",
                "adapter_version",
                "session_id",
                "actor",
                "mode",
                "audit_event_id",
                "message_hash",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise AgentRuntimeError(f"assistant history record missing field(s): {', '.join(missing)}")
        if self.message_chars < 0:
            raise AgentRuntimeError("assistant history message_chars must be non-negative")

    def to_json_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "created_at": self.created_at,
            "provider": self.provider,
            "model": self.model,
            "adapter_version": self.adapter_version,
            "session_id": self.session_id,
            "actor": self.actor,
            "mode": self.mode,
            "message": "",
            "content": "",
            "context_resources": [dict(resource) for resource in self.context_resources],
            "blocked_intents": list(self.blocked_intents),
            "safety_notes": list(self.safety_notes),
            "audit_event_id": self.audit_event_id,
            "message_hash": self.message_hash,
            "message_chars": self.message_chars,
        }


class AssistantHistoryStore:
    """Bounded JSONL-backed assistant history store."""

    def __init__(
        self,
        path: str | Path = DEFAULT_ASSISTANT_HISTORY_PATH,
        *,
        load_on_init: bool = True,
        max_age_days: int | None = DEFAULT_ASSISTANT_HISTORY_MAX_AGE_DAYS,
        max_records: int = DEFAULT_ASSISTANT_HISTORY_MAX_RECORDS,
    ):
        if max_records <= 0:
            raise AgentRuntimeError("assistant history max_records must be positive")
        if max_age_days is not None and max_age_days < 0:
            raise AgentRuntimeError("assistant history max_age_days must be non-negative")
        self.path = Path(path)
        self.max_age_days = None if max_age_days == 0 else max_age_days
        self.max_records = max_records
        self._records: list[AssistantTurnHistoryRecord] = []
        if load_on_init:
            with self._locked():
                self._records = self._load_records(compact=True)

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @classmethod
    def from_env(cls, *, load_on_init: bool = True) -> "AssistantHistoryStore":
        raw_path = os.environ.get(ASSISTANT_HISTORY_FILE_ENV)
        path = Path(raw_path) if raw_path else DEFAULT_ASSISTANT_HISTORY_PATH
        if not path.is_absolute():
            path = REPO_ROOT / path
        raw_limit = os.environ.get(ASSISTANT_HISTORY_MAX_RECORDS_ENV)
        try:
            max_records = int(raw_limit) if raw_limit not in (None, "") else DEFAULT_ASSISTANT_HISTORY_MAX_RECORDS
        except ValueError as exc:
            raise AgentRuntimeError("assistant history max records must be an integer") from exc
        raw_age_days = os.environ.get(ASSISTANT_HISTORY_MAX_AGE_DAYS_ENV)
        try:
            max_age_days = (
                int(raw_age_days)
                if raw_age_days not in (None, "")
                else DEFAULT_ASSISTANT_HISTORY_MAX_AGE_DAYS
            )
        except ValueError as exc:
            raise AgentRuntimeError("assistant history max age days must be an integer") from exc
        return cls(path, load_on_init=load_on_init, max_age_days=max_age_days, max_records=max_records)

    def append_turn(self, *, record: AssistantTurnRecord, message: str) -> AssistantTurnHistoryRecord:
        history_record = AssistantTurnHistoryRecord.from_turn_record(record=record, message=message)
        history_record.validate()
        with self._locked():
            self._records = self._load_records()
            self._records.append(history_record)
            self._records = self._retained_records(self._records)
            self._write_records()
        return history_record

    def list_records(
        self,
        *,
        session_id: str | None = None,
        actor: str | None = None,
        limit: int = 50,
    ) -> list[AssistantTurnHistoryRecord]:
        if limit <= 0:
            raise AgentRuntimeError("assistant history limit must be positive")
        with self._locked():
            self._records = self._load_records(compact=True)
        values = self._records
        if session_id:
            values = [record for record in values if record.session_id == session_id]
        if actor:
            values = [record for record in values if record.actor == actor]
        return list(reversed(values[-limit:]))

    def _load_records(self, *, compact: bool = False) -> list[AssistantTurnHistoryRecord]:
        if not self.path.exists():
            return []
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        records: list[AssistantTurnHistoryRecord] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise AgentRuntimeError(f"assistant history file is not readable: {self.path}") from exc
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise AgentRuntimeError("history line is not an object")
                record = AssistantTurnHistoryRecord.from_mapping(payload)
                record.validate()
            except Exception as exc:
                raise AgentRuntimeError(
                    f"assistant history file has invalid record at line {line_number}: {self.path}"
                ) from exc
            records.append(record)
        retained = self._retained_records(records)
        if compact and len(retained) != len(records):
            self._records = retained
            self._write_records()
        return retained

    def _retained_records(self, records: list[AssistantTurnHistoryRecord]) -> list[AssistantTurnHistoryRecord]:
        if self.max_age_days is None:
            retained = records
        else:
            cutoff = utc_now() - timedelta(days=self.max_age_days)
            retained = []
            for record in records:
                try:
                    created_at = datetime.fromisoformat(record.created_at)
                except ValueError as exc:
                    raise AgentRuntimeError(f"assistant history record has invalid created_at: {record.id}") from exc
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                if created_at >= cutoff:
                    retained.append(record)
        return retained[-self.max_records :]

    def _write_records(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f"{self.path.name}.tmp")
        try:
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for record in self._records:
                    handle.write(json.dumps(record.to_json_dict(), sort_keys=True, separators=(",", ":")))
                    handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            tmp_path.replace(self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            try:
                directory_fd = os.open(self.path.parent, os.O_DIRECTORY)
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except OSError as exc:
            raise AgentRuntimeError(f"assistant history file is not writable: {self.path}") from exc


def load_default_assistant_config() -> AssistantConfig:
    """Load assistant defaults from the configured artifact."""

    raw = os.environ.get(ASSISTANT_CONFIG_ENV)
    path = Path(raw) if raw else DEFAULT_ASSISTANT_CONFIG_PATH
    if not path.is_absolute():
        path = REPO_ROOT / path
    return AssistantConfig.from_file(path)


class AssistantContextAssembler:
    """Load bounded public context resources for an assistant turn."""

    def __init__(self, *, config: AssistantConfig, index: AgentContextIndex | None = None):
        self.config = config
        self.index = index or load_default_context_index()

    def assemble(self, resource_ids: tuple[str, ...] | None = None) -> tuple[AssistantContextDocument, ...]:
        selected_ids = resource_ids or self.config.default_context_resource_ids
        docs: list[AssistantContextDocument] = []
        total_bytes = 0
        for resource_id in selected_ids:
            resource = self.index.require(resource_id)
            if resource.sensitivity != "public":
                raise AgentRuntimeError(f"assistant context resource is not public: {resource_id}")
            text = self.index.read_text(resource_id, max_bytes=self.config.max_context_bytes)
            total_bytes += len(text.encode("utf-8"))
            if total_bytes > self.config.max_context_bytes:
                raise AgentRuntimeError("assistant context exceeds max_context_bytes")
            docs.append(AssistantContextDocument.from_resource(index=self.index, resource=resource, text=text))
        return tuple(docs)


class MockAssistantAdapter:
    """Deterministic adapter used before real provider integration."""

    def __init__(self, *, config: AssistantConfig):
        self.config = config

    def generate(self, *, message: str, context_documents: tuple[AssistantContextDocument, ...]) -> AssistantTurnResult:
        sensitive_input_terms = self._sensitive_input_terms(message)
        blocked_intents = tuple(sorted(set(self._blocked_intents(message) + sensitive_input_terms)))
        template = self.config.response_template
        lines = [
            template.preamble,
            f"Provider: {self.config.provider}.",
            f"Loaded context resources: {', '.join(doc.id for doc in context_documents)}.",
            (
                template.sensitive_input_notice
                if sensitive_input_terms
                else template.blocked_action_notice
                if blocked_intents
                else template.no_action_notice
            ),
        ]
        if blocked_intents:
            lines.append(f"Blocked intent signals: {', '.join(blocked_intents)}.")
        if template.suggested_next_steps:
            lines.append("Suggested next steps:")
            lines.extend(f"- {step}" for step in template.suggested_next_steps)

        return AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=self.config.provider,
            model=MOCK_ASSISTANT_MODEL,
            adapter_version=MOCK_ASSISTANT_ADAPTER_VERSION,
            content="\n".join(lines),
            context_documents=context_documents,
            blocked_intents=blocked_intents,
            safety_notes=(
                "No tool execution was attempted.",
                "No provider SDK was called.",
                "No direct drone API or raw GCS command was exposed.",
            ),
        )

    def _blocked_intents(self, message: str) -> tuple[str, ...]:
        return self._matched_terms(message, self.config.blocked_intent_terms)

    def _sensitive_input_terms(self, message: str) -> tuple[str, ...]:
        matches = list(self._matched_terms(message, self.config.sensitive_input_terms))
        matches.extend(pattern.label for pattern in self.config.sensitive_input_patterns if pattern.matches(message))
        return tuple(sorted(set(matches)))

    @staticmethod
    def _matched_terms(message: str, terms: tuple[str, ...]) -> tuple[str, ...]:
        normalized = message.lower()
        matches = []
        for term in terms:
            pattern = r"\b" + re.escape(term.lower()) + r"\b"
            if re.search(pattern, normalized):
                matches.append(term)
        return tuple(sorted(set(matches)))


def sensitive_input_matches(config: AssistantConfig, message: str) -> tuple[str, ...]:
    """Return configured sensitive-input matches for a candidate operator message."""

    return MockAssistantAdapter(config=config)._sensitive_input_terms(message)


def blocked_intent_matches(config: AssistantConfig, message: str) -> tuple[str, ...]:
    """Return configured blocked-intent matches for a candidate operator message."""

    return MockAssistantAdapter(config=config)._blocked_intents(message)


class OpenAIResponsesAssistantAdapter:
    """OpenAI Responses API adapter for advisory text only."""

    def __init__(self, *, config: AssistantConfig):
        self.config = config

    def generate(
        self,
        *,
        message: str,
        context_documents: tuple[AssistantContextDocument, ...],
        language_profile: LanguageProfile | None = None,
        enable_web_search: bool = False,
    ) -> AssistantTurnResult:
        mock_adapter = MockAssistantAdapter(config=self.config)
        sensitive_input_terms = mock_adapter._sensitive_input_terms(message)
        blocked_intents = tuple(sorted(set(mock_adapter._blocked_intents(message) + sensitive_input_terms)))
        if blocked_intents:
            return self._local_blocked_turn(
                message=message,
                context_documents=context_documents,
                blocked_intents=blocked_intents,
                sensitive_input_terms=sensitive_input_terms,
            )

        request_payload = self._request_payload(
            message=message,
            context_documents=context_documents,
            language_profile=language_profile,
            enable_web_search=enable_web_search,
        )
        response_payload = self._post_response(request_payload, api_key=self.config.openai.read_api_key())
        content = self._extract_response_text(response_payload)
        web_search_used = _response_used_web_search(response_payload)

        return AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=OPENAI_ASSISTANT_PROVIDER,
            model=self.config.openai.model,
            adapter_version=OPENAI_ASSISTANT_ADAPTER_VERSION,
            content=content,
            context_documents=context_documents,
            blocked_intents=(),
            safety_notes=(
                "No tool execution was attempted.",
                (
                    "OpenAI Responses API was called with web_search enabled, citations preserved, and store=false."
                    if web_search_used
                    else "OpenAI Responses API was called with tools disabled and store=false."
                ),
                "No direct drone API or raw GCS command was exposed.",
            ),
        )

    def _local_blocked_turn(
        self,
        *,
        message: str,
        context_documents: tuple[AssistantContextDocument, ...],
        blocked_intents: tuple[str, ...],
        sensitive_input_terms: tuple[str, ...] = (),
    ) -> AssistantTurnResult:
        template = self.config.response_template
        content = "\n".join(
            [
                template.preamble,
                f"Provider: {OPENAI_ASSISTANT_PROVIDER} (local safety block; no provider request was made).",
                f"Loaded context resources: {', '.join(doc.id for doc in context_documents)}.",
                template.sensitive_input_notice if sensitive_input_terms else template.blocked_action_notice,
                f"Blocked intent signals: {', '.join(blocked_intents)}.",
            ]
        )
        return AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=OPENAI_ASSISTANT_PROVIDER,
            model=self.config.openai.model,
            adapter_version=OPENAI_ASSISTANT_ADAPTER_VERSION,
            content=content,
            context_documents=context_documents,
            blocked_intents=blocked_intents,
            safety_notes=(
                (
                    "No provider request was made because the message matched sensitive operational data handling terms."
                    if sensitive_input_terms
                    else "No provider request was made because the message matched blocked operational intent."
                ),
                "No tool execution was attempted.",
                "No direct drone API or raw GCS command was exposed.",
            ),
        )

    def _request_payload(
        self,
        *,
        message: str,
        context_documents: tuple[AssistantContextDocument, ...],
        language_profile: LanguageProfile | None = None,
        enable_web_search: bool = False,
    ) -> dict[str, Any]:
        context_blocks = self._context_blocks(context_documents)
        provider_message = _provider_message_with_language_guidance(message, language_profile)
        try:
            input_text = self.config.provider_input_template.format(
                message=provider_message,
                context_blocks=context_blocks,
            )
        except KeyError as exc:
            raise AgentRuntimeError("assistant provider_input_template has an unknown placeholder") from exc

        tools: list[dict[str, Any]] = []
        tool_choice: str = "none"
        include: list[str] = []
        if enable_web_search:
            tools = [self.config.openai.web_search.tool_payload()]
            tool_choice = "required"
            include = ["web_search_call.action.sources"]

        return {
            "model": self.config.openai.model,
            "instructions": self.config.provider_instructions,
            "input": input_text,
            "max_output_tokens": self.config.openai.max_output_tokens,
            "reasoning": {"effort": self.config.openai.reasoning_effort},
            "text": {
                "format": {"type": "text"},
                "verbosity": self.config.openai.text_verbosity,
            },
            "store": False,
            "include": include,
            "tools": tools,
            "tool_choice": tool_choice,
            "parallel_tool_calls": False,
            "metadata": {
                "mds_component": "simurgh_operator",
                "mds_execution": "none",
                "mds_web_search": "enabled" if enable_web_search else "disabled",
            },
        }

    def _context_blocks(self, context_documents: tuple[AssistantContextDocument, ...]) -> str:
        blocks = []
        for document in context_documents:
            blocks.append(
                "\n".join(
                    [
                        f"### {document.id}",
                        f"Title: {document.title}",
                        f"Summary: {document.summary}",
                        f"Content hash: {document.content_hash}",
                        "",
                        document.text,
                    ]
                )
            )
        return "\n\n".join(blocks)

    def _post_response(self, payload: dict[str, Any], *, api_key: str) -> dict[str, Any]:
        url = f"{self.config.openai.base_url.rstrip('/')}/responses"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self.config.openai.timeout_seconds) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                decoded = response.json()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            raise AgentRuntimeError(f"OpenAI assistant request failed with HTTP {status_code}") from exc
        except httpx.TimeoutException as exc:
            raise AgentRuntimeError("OpenAI assistant request timed out") from exc
        except httpx.HTTPError as exc:
            raise AgentRuntimeError("OpenAI assistant request failed") from exc
        except ValueError as exc:
            raise AgentRuntimeError("OpenAI assistant response was not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise AgentRuntimeError("OpenAI assistant response must be a JSON object")
        return decoded

    def _extract_response_text(self, payload: Mapping[str, Any]) -> str:
        error = payload.get("error")
        if error:
            raise AgentRuntimeError("OpenAI assistant response returned an error")
        self._reject_non_text_outputs(payload)
        citations = _url_citations_from_response(payload)
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return _append_citation_sources(output_text.strip(), citations)

        parts: list[str] = []
        for item in payload.get("output") or ():
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or ():
                if not isinstance(content, dict):
                    continue
                if content.get("type") in {"output_text", "text"}:
                    text = content.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
        text = "\n".join(parts).strip()
        if not text:
            raise AgentRuntimeError("OpenAI assistant response did not include output text")
        return _append_citation_sources(text, citations)

    def _reject_non_text_outputs(self, payload: Mapping[str, Any]) -> None:
        for item in payload.get("output") or ():
            if not isinstance(item, dict):
                raise AgentRuntimeError("OpenAI assistant response included an invalid output item")
            item_type = item.get("type")
            if item_type in {"reasoning", "web_search_call"}:
                continue
            if item_type != "message":
                raise AgentRuntimeError("OpenAI assistant response included non-text output")
            for content in item.get("content") or ():
                if not isinstance(content, dict):
                    raise AgentRuntimeError("OpenAI assistant response included an invalid content item")
                if content.get("type") not in {"output_text", "text"}:
                    raise AgentRuntimeError("OpenAI assistant response included non-text content")


def _adapter_for_config(config: AssistantConfig) -> MockAssistantAdapter | OpenAIResponsesAssistantAdapter:
    if config.provider == SUPPORTED_ASSISTANT_PROVIDER:
        return MockAssistantAdapter(config=config)
    if config.provider == OPENAI_ASSISTANT_PROVIDER:
        return OpenAIResponsesAssistantAdapter(config=config)
    raise AgentRuntimeError(f"assistant provider {config.provider!r} is not implemented in this slice")


def _safe_assistant_session_metadata(metadata: Mapping[str, object] | None) -> dict[str, object]:
    safe = sanitize_session_metadata({"channel": "assistant", "source": (metadata or {}).get("source")})
    safe["channel"] = "assistant"
    return safe


def _context_bytes(documents: tuple[AssistantContextDocument, ...]) -> int:
    return sum(len(document.text.encode("utf-8")) for document in documents)


def _retrieved_context_documents(
    *,
    query_plan: AssistantQueryPlan,
    existing_documents: tuple[AssistantContextDocument, ...],
) -> tuple[AssistantContextDocument, ...]:
    """Return bounded public docs chunks for provider context assembly."""

    try:
        retriever = load_default_retriever()
    except AgentRuntimeError:
        return ()

    search_queries = query_plan.search_queries or (query_plan.normalized_message,)
    try:
        ranked = search_retriever_queries(
            retriever,
            search_queries,
            limit=DEFAULT_RETRIEVED_CONTEXT_LIMIT,
            tags=query_plan.tags,
        )
    except AgentRuntimeError:
        return ()

    existing_ids = {document.id for document in existing_documents}
    documents: list[AssistantContextDocument] = []
    budget = DEFAULT_RETRIEVED_CONTEXT_BUDGET_BYTES
    used = 0
    for hit in ranked[: DEFAULT_RETRIEVED_CONTEXT_LIMIT * 2]:
        chunk = hit.chunk
        document_id = "retrieved." + re.sub(r"[^A-Za-z0-9_.:-]+", ".", chunk.id).strip(".")
        if not document_id or document_id in existing_ids:
            continue
        text = _retrieved_chunk_text(
            chunk_text=chunk.text,
            canonical_url=chunk.canonical_url,
            route_hint=chunk.route_hint,
            search_query=hit.query,
            max_chars=DEFAULT_RETRIEVED_CONTEXT_MAX_CHARS,
        )
        next_bytes = len(text.encode("utf-8"))
        if used + next_bytes > budget and documents:
            break
        used += next_bytes
        documents.append(
            AssistantContextDocument(
                id=document_id,
                title=f"Retrieved docs: {chunk.title}" + (f" - {chunk.heading}" if chunk.heading else ""),
                uri=chunk.canonical_url or f"mds://simurgh/docs/{chunk.id}",
                mime_type=chunk.mime_type,
                summary=(
                    f"Retrieved public docs context for domain={query_plan.domain}, "
                    f"mode={query_plan.response_mode}, score={hit.score:.1f}. {chunk.summary}"
                ),
                tags=tuple(dict.fromkeys(("retrieved", "rag", query_plan.domain, *chunk.tags))),
                content_hash=chunk.content_hash,
                text=text,
            )
        )
        if len(documents) >= DEFAULT_RETRIEVED_CONTEXT_LIMIT:
            break
    return tuple(documents)

def _retrieved_chunk_text(
    *,
    chunk_text: str,
    canonical_url: str,
    route_hint: str | None,
    search_query: str,
    max_chars: int,
) -> str:
    text = str(chunk_text or "").strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n...[truncated by Simurgh retrieval context budget]"
    lines = [f"Retrieved query: {search_query}"]
    if canonical_url:
        lines.append(f"Source: {canonical_url}")
    if route_hint:
        lines.append(f"Dashboard route: {route_hint}")
    lines.extend(["", text])
    return "\n".join(lines)


def _response_used_web_search(payload: Mapping[str, Any]) -> bool:
    return any(
        isinstance(item, Mapping) and item.get("type") == "web_search_call"
        for item in payload.get("output") or ()
    )


def _url_citations_from_response(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    for item in payload.get("output") or ():
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content") or ():
            if isinstance(content, Mapping):
                citations.extend(_url_citations_from_content(content))
        citations.extend(_url_citations_from_web_search_item(item))
    return citations


def _url_citations_from_web_search_item(item: Mapping[str, Any]) -> list[dict[str, str]]:
    if item.get("type") != "web_search_call":
        return []
    action = item.get("action")
    if not isinstance(action, Mapping):
        return []
    sources = action.get("sources")
    if not isinstance(sources, list):
        return []
    citations: list[dict[str, str]] = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        url = str(source.get("url") or source.get("uri") or "").strip()
        if not _safe_https_url(url):
            continue
        title = _citation_title_from_url(url, source.get("title") or source.get("name"))
        citations.append({"title": title[:160], "url": url})
    return citations


def _url_citations_from_content(content: Mapping[str, Any]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    for annotation in content.get("annotations") or ():
        if not isinstance(annotation, Mapping) or annotation.get("type") != "url_citation":
            continue
        url = str(annotation.get("url") or "").strip()
        if not _safe_https_url(url):
            continue
        title = _citation_title_from_url(url, annotation.get("title"))
        citations.append({"title": title[:160], "url": url})
    return citations


def _citation_title_from_url(url: str, raw_title: object | None) -> str:
    title = str(raw_title or "").strip()
    if title and title.casefold() != "source":
        return title[:160]
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
    except ValueError:
        host = ""
    return host[:160] or "Source"


def _append_citation_sources(text: str, citations: list[dict[str, str]]) -> str:
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for citation in citations:
        url = citation.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(citation)
    if not unique:
        return text
    lines = [text.rstrip(), "", "Sources:"]
    for citation in unique[:8]:
        label = _markdown_link_label(citation.get("title") or "Source")
        url = citation["url"]
        lines.append(f"- [{label}]({url})")
    return "\n".join(lines).strip()


def _markdown_link_label(value: str) -> str:
    return re.sub(r"[\[\]\n\r]+", " ", str(value or "Source")).strip()[:160] or "Source"


def _safe_https_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    return parsed.scheme == "https" and bool(parsed.netloc)


def _should_enable_web_search_for_turn(
    *,
    config: AssistantConfig,
    query_plan: AssistantQueryPlan,
    normalized_message: str,
    routing_message: str,
    local_intent: str | None,
) -> bool:
    if config.provider != OPENAI_ASSISTANT_PROVIDER or not config.openai.web_search.enabled:
        return False
    if local_intent not in {None, "general_knowledge"}:
        return False
    normalized = re.sub(r"\s+", " ", (routing_message or normalized_message).casefold()).strip()
    if not normalized:
        return False
    if _has_mds_private_or_state_signal(normalized):
        return False
    if _has_public_current_or_lookup_signal(normalized):
        return True
    return local_intent is None and query_plan.domain == "general" and query_plan.confidence < 0.4


def _has_mds_private_or_state_signal(normalized: str) -> bool:
    return _has_any_text(
        normalized,
        (
            "mds",
            "simurgh",
            "fleet",
            "swarm",
            "drone show",
            "skybrush",
            "qgc",
            "px4",
            "mavlink",
            "sys_id",
            "telemetry",
            "heartbeat",
            "netbird",
            "gcs",
            "dashboard",
            "sitl",
            "logs",
            "runtime",
            "mcp",
            "scout drone",
            "drone 1",
            "drone 2",
            "drone 3",
            "ip",
            "connected",
            "configured",
        ),
    )


def _has_public_current_or_lookup_signal(normalized: str) -> bool:
    return _has_any_text(
        normalized,
        (
            "weather",
            "forecast",
            "today",
            "latest",
            "current",
            "right now",
            "news",
            "internet",
            "web search",
            "search the web",
            "search internet",
            "who is",
            "when is",
            "where is",
            "capital of",
            "population of",
            "latitude",
            "longitude",
            "lat long",
            "lat lon",
            "lat/lon",
            "lat and long",
            "coordinates",
            "coordinate of",
            "wgs84",
            "altitude",
            "elevation",
            "height",
            "how far",
            "distance from",
            "distance between",
            "regulation",
            "regulations",
            "law",
            "rules",
        ),
    )


def _has_any_text(value: str, needles: tuple[str, ...]) -> bool:
    for needle in needles:
        marker = str(needle or "").strip()
        if not marker:
            continue
        if re.fullmatch(r"[a-z0-9_]+", marker):
            if re.search(rf"\b{re.escape(marker)}\b", value):
                return True
        elif marker in value:
            return True
    return False


def _provider_message_with_language_guidance(
    message: str,
    language_profile: LanguageProfile | None,
) -> str:
    """Append safe language/tone guidance for provider turns without mutating stored prompts."""

    if language_profile is None:
        return message
    return message + "\n\n" + provider_language_guidance(language_profile)


def _conversation_transform_kind(message: str) -> str | None:
    """Return the requested previous-answer transform, if the turn is referential.

    This is a generic conversation-state primitive, not an MDS domain intent. It
    prevents polite follow-ups like "can you say it in Persian" from being
    stolen by capability or fleet routing before the provider can transform the
    actual previous answer.
    """

    normalized = re.sub(r"\s+", " ", str(message or "").strip().casefold())
    if not normalized:
        return None
    language_markers = (
        "persian",
        "farsi",
        "فارسی",
        "français",
        "french",
        "spanish",
        "español",
        "arabic",
        "عربی",
        "english",
    )
    transform_markers = (
        "say it in",
        "say this in",
        "translate",
        "translation",
        "same in",
        "answer in",
        "write it in",
        "rewrite it in",
        "به فارسی",
        "فارسی بگو",
        "فارسی بنویس",
        "همینو فارسی",
        "همین رو فارسی",
        "همین را فارسی",
        "in persian",
        "in farsi",
    )
    persian_same_answer = "فارسی" in normalized and any(
        marker in normalized for marker in ("همینو", "همین رو", "همین را", "این رو", "این را")
    )
    marker_transform = any(marker in normalized for marker in transform_markers) and any(
        marker in normalized for marker in language_markers
    )
    if persian_same_answer or marker_transform:
        return "translate_previous_answer"
    if any(marker in normalized for marker in ("shorter", "more concise", "simpler", "summarize that", "summarise that")):
        return "rewrite_previous_answer"
    return None


def _previous_answer_context_document(previous_answer: str) -> AssistantContextDocument:
    content = str(previous_answer or "").strip()
    return AssistantContextDocument(
        id="session.previous_assistant_answer",
        title="Previous Simurgh answer in this chat",
        uri="mds://simurgh/session/previous-assistant-answer",
        mime_type="text/markdown",
        summary="Bounded private session context used only to transform the previous answer for the current operator.",
        tags=("session", "conversation", "previous-answer"),
        content_hash=stable_payload_hash({"previous_assistant_answer": content}),
        text=content[:DEFAULT_RETRIEVED_CONTEXT_MAX_CHARS],
    )


def _previous_answer_transform_message(*, operator_message: str, transform_kind: str) -> str:
    return "\n".join(
        [
            f"Operator follow-up: {operator_message}",
            f"Conversation task: {transform_kind}.",
            "Use the context document `session.previous_assistant_answer` as the source answer.",
            "Do not retrieve new facts, do not change numbers/IPs/routes/safety caveats, and do not claim any action was executed.",
            "Return only the transformed answer in the operator-requested language or style.",
        ]
    )


def _read_only_tool_evidence_context_document(
    *,
    tool_intent: str,
    tool_ids: list[str],
    response_mode: str,
    content: str,
) -> AssistantContextDocument:
    evidence = str(content or "").strip()
    intent = str(tool_intent or "read_only_mds_tool").strip() or "read_only_mds_tool"
    mode = str(response_mode or "status").strip() or "status"
    tool_ids_text = ", ".join(tool_ids) or "none"
    return AssistantContextDocument(
        id="session.read_only_mds_evidence",
        title="Read-only MDS evidence for this assistant turn",
        uri="mds://simurgh/session/read-only-mds-evidence",
        mime_type="text/markdown",
        summary=(
            "Authoritative read-only GCS/MDS tool result selected by the Simurgh policy layer. "
            f"intent={intent}; response_mode={mode}; tool_ids={tool_ids_text}."
        ),
        tags=("session", "tool-evidence", "read-only", intent),
        content_hash=stable_payload_hash(
            {
                "tool_intent": intent,
                "tool_ids": tool_ids,
                "response_mode": response_mode,
                "content": evidence,
            }
        ),
        text=evidence[:DEFAULT_RETRIEVED_CONTEXT_BUDGET_BYTES],
    )


def _provider_tool_composition_message(
    *,
    operator_message: str,
    tool_intent: str,
    response_mode: str,
) -> str:
    intent_label = tool_intent or "unknown"
    response_mode_label = response_mode or "status"
    return "\n".join(
        [
            f"Operator message: {operator_message}",
            "Conversation task: answer naturally using the read-only MDS evidence context.",
            f"Read-only tool intent: {intent_label}.",
            f"Response mode: {response_mode_label}.",
            "Use `session.read_only_mds_evidence` as authoritative. Preserve exact counts, IPs, routes, URLs, modes, times, coordinates, safety caveats, and no-action statements from that evidence.",
            "Do not invent live state, do not call or imply any action, and do not add unsupported claims. If the user is asking a short follow-up, answer the follow-up directly instead of repeating the whole evidence dump.",
            "Prefer a concise ChatGPT-style answer: short direct verdict first, then only the useful details. Keep Markdown tables/lists only when they improve scanability.",
        ]
    )


def _safe_provider_composition_error(exc: Exception) -> str:
    message = str(exc or "").strip()
    if not message:
        return "provider-composition-failed"
    return re.sub(r"[^A-Za-z0-9 .:_/-]+", "", message)[:160]


def _looks_like_public_geography_frame_reply(message: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(message or "").strip().casefold())
    if not normalized or len(normalized) > 140:
        return False
    return _has_any_text(
        normalized,
        (
            "yes",
            "yeah",
            "ok",
            "correct",
            "meter",
            "meters",
            "metre",
            "metres",
            "wgs84",
            "decimal degree",
            "decimal degrees",
            "altitude",
            "elevation",
            "msl",
            "asl",
            "above sea level",
        ),
    )


def _frame_bound_routing_message(
    *,
    routing_message: str,
    original_message: str,
    conversation_topic: str,
    previous_context: Mapping[str, str],
) -> str:
    """Bind very short slot-filling replies to the active task frame.

    This is the missing state layer that prevents a reply like "yes, WGS84 and
    meters" from being interpreted against an older swarm/fleet topic. It only
    rewrites the internal routing text; the provider still sees the original
    user message and the final answer is based on retrieved evidence.
    """

    if conversation_topic != "public_geography":
        return routing_message
    if _conversation_transform_kind(original_message):
        return routing_message
    if not _looks_like_public_geography_frame_reply(original_message):
        return routing_message
    previous_question = (
        previous_context.get("last_routing_message")
        or previous_context.get("last_user_message")
        or ""
    ).strip()
    if not previous_question:
        return routing_message
    return f"{previous_question}\nFollow-up answer from operator: {routing_message}"


def _provider_failure_turn(
    *,
    exc: Exception,
    config: AssistantConfig,
    context_documents: tuple[AssistantContextDocument, ...],
    local_fallback: MdsReadToolAnswer | None = None,
) -> AssistantTurnResult:
    safe_error = _safe_provider_composition_error(exc)
    if local_fallback is not None:
        content = "\n\n".join(
            (
                local_fallback.content,
                "Provider note: external model/search composition was unavailable for this turn, so Simurgh returned the deterministic read-only evidence instead of a raw transport failure.",
            )
        )
        return AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=READ_TOOL_PROVIDER,
            model=READ_TOOL_MODEL,
            adapter_version=READ_TOOL_ADAPTER_VERSION,
            content=content,
            context_documents=context_documents,
            blocked_intents=(),
            safety_notes=(
                "External assistant provider failed after routing; deterministic local read-only evidence was returned.",
                f"Provider failure class: {safe_error or provider-unavailable}.",
                "No direct drone API, raw command, GCS mutation, or mission action was exposed.",
            ),
        )
    content = (
        "I could not reach the external assistant provider/search service for that turn. "
        "The chat state was kept, and no GCS mutation or drone command was attempted. "
        "Please retry, or ask for an MDS read-only status/tool answer that can be resolved locally."
    )
    return AssistantTurnResult(
        id=f"turn-{uuid.uuid4().hex}",
        created_at=utc_now().isoformat(),
        provider=config.provider,
        model=config.openai.model if config.provider == OPENAI_ASSISTANT_PROVIDER else MOCK_ASSISTANT_MODEL,
        adapter_version="provider-fallback-v1",
        content=content,
        context_documents=context_documents,
        blocked_intents=(),
        safety_notes=(
            "External assistant provider failed; Simurgh returned a bounded fallback instead of exposing raw transport errors.",
            f"Provider failure class: {safe_error or provider-unavailable}.",
            "No direct drone API, raw command, GCS mutation, or mission action was exposed.",
        ),
    )


def _is_provider_runtime_recoverable(exc: Exception) -> bool:
    """Return whether a provider error should become a chat fallback.

    Configuration errors, schema violations, unsafe tool outputs, and unsupported
    provider behavior should still fail tests loudly. Transport/service failures
    should not surface to operators as raw network errors.
    """

    message = str(exc or "").casefold()
    return any(
        marker in message
        for marker in (
            "network",
            "timeout",
            "timed out",
            "connection",
            "request failed",
            "rate limit",
            "service unavailable",
            "temporarily unavailable",
            "bad gateway",
            "gateway timeout",
        )
    )


def create_assistant_turn(
    *,
    sessions: AgentSessionStore,
    audit: InMemoryAuditSink,
    actor: str,
    message: str,
    deps: Any | None = None,
    session_id: str | None = None,
    mode: str | None = None,
    context_resource_ids: tuple[str, ...] | None = None,
    metadata: Mapping[str, object] | None = None,
    force_provider: str | None = None,
    allow_provider_for_local_tools: bool = False,
) -> AssistantTurnRecord:
    """Create one assistant turn without command or mutation execution."""

    policy = load_default_policy()
    if not policy.agent_enabled:
        raise PermissionError("Simurgh agent runtime is disabled")

    config = load_default_assistant_config()
    if force_provider:
        config = replace(config, provider=force_provider)
        config.validate()
    normalized_actor = actor.strip()
    if not normalized_actor:
        raise AgentRuntimeError("assistant actor is required")
    normalized_message = message.strip()
    if not normalized_message:
        raise AgentRuntimeError("assistant message is required")
    if len(normalized_message) > config.max_message_chars:
        raise AgentRuntimeError("assistant message exceeds max_message_chars")

    language_profile = detect_language_profile(normalized_message)

    if session_id:
        session = sessions.require(session_id)
        if session.closed:
            raise AgentRuntimeError("assistant session is closed")
        if session.actor != normalized_actor:
            raise PermissionError("assistant session belongs to a different actor")
    else:
        session_mode = mode or policy.mode
        if session_mode not in policy.runtime_modes:
            raise AgentRuntimeError(f"unknown Simurgh mode: {session_mode}")
        session = sessions.create(
            actor=normalized_actor,
            mode=session_mode,
            metadata=_safe_assistant_session_metadata(metadata),
        )

    context_documents = AssistantContextAssembler(config=config).assemble(context_resource_ids)
    previous_context = sessions.get_private_context(session.id)
    conversation_topic = str(session.metadata.get("last_domain") or previous_context.get("last_domain") or "")
    query_adaptation = adapt_operator_query(
        normalized_message,
        language_profile=language_profile,
        conversation_topic=conversation_topic,
    )
    routing_message = query_adaptation.routing_text or normalized_message
    routing_message = _frame_bound_routing_message(
        routing_message=routing_message,
        original_message=normalized_message,
        conversation_topic=conversation_topic,
        previous_context=previous_context,
    )
    query_plan = build_assistant_query_plan(routing_message, conversation_topic=conversation_topic)
    retrieved_context_count = 0
    blocked_matches = tuple(
        sorted(
            set(
                blocked_intent_matches(config, normalized_message)
                + blocked_intent_matches(config, routing_message)
            )
        )
    )
    sensitive_matches = tuple(
        sorted(
            set(
                sensitive_input_matches(config, normalized_message)
                + sensitive_input_matches(config, routing_message)
            )
        )
    )
    local_intent = None
    tool_result = None
    tool_intent = None
    tool_response_mode = None
    tool_ids: list[str] = []
    web_search_enabled_for_turn = False
    provider_composed_from_tool = False
    provider_composition_error = ""
    transform_kind = _conversation_transform_kind(routing_message)
    transform_answer = previous_context.get("last_assistant_content") if transform_kind else ""
    if force_provider is None and transform_kind and transform_answer and not blocked_matches and not sensitive_matches:
        adapter = _adapter_for_config(config)
        if isinstance(adapter, OpenAIResponsesAssistantAdapter):
            previous_document = _previous_answer_context_document(transform_answer)
            context_documents = (*context_documents, previous_document)
            retrieved_context_count = 1
            try:
                turn = adapter.generate(
                    message=_previous_answer_transform_message(
                        operator_message=normalized_message,
                        transform_kind=transform_kind,
                    ),
                    context_documents=context_documents,
                    language_profile=language_profile,
                )
            except AgentRuntimeError as exc:
                if not _is_provider_runtime_recoverable(exc):
                    raise
                turn = _provider_failure_turn(
                    exc=exc,
                    config=config,
                    context_documents=context_documents,
                )
            tool_intent = "conversation_transform"
            tool_response_mode = "transform"
        else:
            tool_result = None

    if force_provider is None and tool_intent is None:
        local_intent = classify_mds_read_intent(routing_message, conversation_topic=conversation_topic)
        if not blocked_matches and not sensitive_matches:
            web_search_enabled_for_turn = _should_enable_web_search_for_turn(
                config=config,
                query_plan=query_plan,
                normalized_message=normalized_message,
                routing_message=routing_message,
                local_intent=local_intent,
            )
        safe_read_only_blocked_term = is_safe_blocked_term_read_only_intent(routing_message, local_intent)
        if not web_search_enabled_for_turn and local_intent is not None and (
            local_intent == "action_capability"
            or (not sensitive_matches and (not blocked_matches or safe_read_only_blocked_term))
        ):
            tool_arguments = {"question": routing_message}
            if conversation_topic:
                tool_arguments["conversation_topic"] = conversation_topic
            tool_result = execute_policy_allowed_advisory_tool(
                name=ADVISORY_ANSWER_TOOL_ID,
                arguments=tool_arguments,
                channel="agent",
                deps=deps,
                policy=policy,
            )
            if tool_result.is_error:
                tool_result = None

    if tool_intent == "conversation_transform":
        pass
    elif tool_result is not None:
        structured = tool_result.structured_content if isinstance(tool_result.structured_content, Mapping) else {}
        raw_safety_notes = structured.get("safety_notes") if isinstance(structured, Mapping) else None
        safety_notes = tuple(str(note) for note in raw_safety_notes) if isinstance(raw_safety_notes, list) else (
            "Read-only Simurgh advisory registry tool was executed.",
            "No direct drone API or raw GCS command was exposed.",
        )
        tool_intent = structured.get("intent") if isinstance(structured, Mapping) else None
        raw_tool_ids = structured.get("tool_ids") if isinstance(structured, Mapping) else None
        tool_ids = [str(tool_id) for tool_id in raw_tool_ids] if isinstance(raw_tool_ids, list) else []
        tool_response_mode = structured.get("response_mode") if isinstance(structured, Mapping) else None
        local_tool_turn = AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=READ_TOOL_PROVIDER,
            model=READ_TOOL_MODEL,
            adapter_version=READ_TOOL_ADAPTER_VERSION,
            content=tool_result.text,
            context_documents=context_documents,
            blocked_intents=(),
            safety_notes=safety_notes,
        )
        turn = local_tool_turn
        if (
            allow_provider_for_local_tools
            and config.provider == OPENAI_ASSISTANT_PROVIDER
            and not blocked_matches
            and not sensitive_matches
            and str(tool_intent or "") not in LOCAL_PROVIDER_COMPOSITION_DISABLED_INTENTS
        ):
            adapter = _adapter_for_config(config)
            if isinstance(adapter, OpenAIResponsesAssistantAdapter):
                evidence_document = _read_only_tool_evidence_context_document(
                    tool_intent=str(tool_intent or ""),
                    tool_ids=tool_ids,
                    response_mode=str(tool_response_mode or query_plan.response_mode),
                    content=local_tool_turn.content,
                )
                provider_context_documents = (*context_documents, evidence_document)
                try:
                    provider_turn = adapter.generate(
                        message=_provider_tool_composition_message(
                            operator_message=normalized_message,
                            tool_intent=str(tool_intent or ""),
                            response_mode=str(tool_response_mode or query_plan.response_mode),
                        ),
                        context_documents=provider_context_documents,
                        language_profile=language_profile,
                    )
                    turn = replace(
                        provider_turn,
                        context_documents=provider_context_documents,
                        safety_notes=(
                            "Read-only Simurgh advisory registry tool was executed before provider composition.",
                            "OpenAI Responses API composed the final text from bounded read-only MDS evidence with store=false.",
                            "No direct drone API, MAVSDK command, raw GCS command, or mission mutation was exposed.",
                        ),
                    )
                    context_documents = provider_context_documents
                    retrieved_context_count += 1
                    provider_composed_from_tool = True
                except AgentRuntimeError as exc:
                    provider_composition_error = _safe_provider_composition_error(exc)
    else:
        if (
            config.provider != "mock"
            and not web_search_enabled_for_turn
            and query_plan.domain != "general"
            and not blocked_matches
            and not sensitive_matches
        ):
            retrieved_documents = _retrieved_context_documents(
                query_plan=query_plan,
                existing_documents=context_documents,
            )
            if retrieved_documents:
                context_documents = (*context_documents, *retrieved_documents)
                retrieved_context_count = len(retrieved_documents)
        adapter = _adapter_for_config(config)
        if isinstance(adapter, OpenAIResponsesAssistantAdapter):
            try:
                turn = adapter.generate(
                    message=normalized_message,
                    context_documents=context_documents,
                    language_profile=language_profile,
                    enable_web_search=web_search_enabled_for_turn,
                )
            except AgentRuntimeError as exc:
                if not _is_provider_runtime_recoverable(exc):
                    raise
                local_fallback = None
                if not blocked_matches and not sensitive_matches:
                    local_fallback = answer_mds_read_only_question(
                        routing_message,
                        deps=deps,
                        conversation_topic=conversation_topic,
                    )
                turn = _provider_failure_turn(
                    exc=exc,
                    config=config,
                    context_documents=context_documents,
                    local_fallback=local_fallback,
                )
        else:
            turn = adapter.generate(
                message=normalized_message,
                context_documents=context_documents,
            )

    final_response_mode = str(tool_response_mode or query_plan.response_mode)
    next_topic = infer_mds_read_topic(routing_message, intent=str(tool_intent or local_intent or ""))
    if not next_topic and query_plan.domain == "general":
        next_topic = query_plan.domain
    if next_topic:
        session = sessions.update_metadata(
            session.id,
            {
                "last_domain": next_topic,
                "last_intent": str(tool_intent or local_intent or ""),
                "last_response_mode": final_response_mode,
            },
        )
    sessions.update_private_context(
        session.id,
        {
            "last_assistant_content": turn.content,
            "last_assistant_provider": turn.provider,
            "last_assistant_model": turn.model,
            "last_domain": str(next_topic or session.metadata.get("last_domain") or ""),
            "last_intent": str(tool_intent or local_intent or session.metadata.get("last_intent") or ""),
            "last_response_mode": final_response_mode,
            "last_user_message": normalized_message,
            "last_routing_message": routing_message,
            "last_tool_intent": str(tool_intent or local_intent or ""),
        },
    )

    event = audit.record(
        "assistant_turn_created",
        session_id=session.id,
        actor=normalized_actor,
        decision="allow",
        payload={
            "message": normalized_message,
            "context_resource_ids": [doc.id for doc in context_documents],
            "metadata": dict(metadata or {}),
        },
        metadata={
            "provider": turn.provider,
            "model": turn.model,
            "adapter_version": turn.adapter_version,
            "mode": session.mode,
            "context_count": len(context_documents),
            "blocked_intent_count": len(turn.blocked_intents),
            "tool_intent": tool_intent,
            "tool_id": ADVISORY_ANSWER_TOOL_ID if tool_result is not None else None,
            "tool_ids": tool_ids,
            "response_mode": final_response_mode,
            "query_domain": query_plan.domain,
            "query_confidence": round(float(query_plan.confidence), 3),
            "query_unclear": query_plan.unclear,
            "query_reason": query_plan.reason,
            "retrieved_context_count": retrieved_context_count,
            "web_search_enabled": web_search_enabled_for_turn,
            "provider_composed_from_tool": provider_composed_from_tool,
            "provider_composition_error": provider_composition_error,
            "query_adaptation": query_adaptation.public_metadata(),
            "routing_strategy": query_adaptation.strategy,
            "routing_language": query_adaptation.routing_language,
            "routing_rule_count": len(query_adaptation.applied_rules),
            "language_profile": language_profile.public_metadata(),
            "input_language": language_profile.language,
            "input_script": language_profile.script,
            "input_tone": language_profile.tone,
            "localization_strategy": language_profile.localization_strategy,
        },
    )
    return AssistantTurnRecord(session=session, turn=turn, audit_event=event)


def create_mock_assistant_turn(
    *,
    sessions: AgentSessionStore,
    audit: InMemoryAuditSink,
    actor: str,
    message: str,
    deps: Any | None = None,
    session_id: str | None = None,
    mode: str | None = None,
    context_resource_ids: tuple[str, ...] | None = None,
    metadata: Mapping[str, object] | None = None,
) -> AssistantTurnRecord:
    """Create one deterministic mock assistant turn without executing tools."""

    return create_assistant_turn(
        sessions=sessions,
        audit=audit,
        actor=actor,
        message=message,
        deps=deps,
        session_id=session_id,
        mode=mode,
        context_resource_ids=context_resource_ids,
        metadata=metadata,
        force_provider=SUPPORTED_ASSISTANT_PROVIDER,
    )
