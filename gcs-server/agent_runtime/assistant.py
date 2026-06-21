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
    build_mds_read_only_plan,
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
OPENAI_SEMANTIC_REWRITE_ADAPTER_VERSION = "openai-semantic-rewrite-v1"
DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
ALLOWED_OPENAI_BASE_URLS = (DEFAULT_OPENAI_BASE_URL,)
DEFAULT_OPENAI_TIMEOUT_SECONDS = 30.0
DEFAULT_OPENAI_MAX_OUTPUT_TOKENS = 900
DEFAULT_OPENAI_REASONING_EFFORT = "medium"
DEFAULT_OPENAI_TEXT_VERBOSITY = "low"
DEFAULT_OPENAI_WEB_SEARCH_CONTEXT_SIZE = "medium"
LOCAL_PROVIDER_COMPOSITION_DISABLED_INTENTS = frozenset(
    {
        "drone_log_summary",
        "registry_domain_tool_summary",
    }
)
SAFE_READ_ONLY_SENSITIVE_MATCHES_BY_INTENT = {
    "drone_log_summary": frozenset({"ULog artifact"}),
}
UNSAFE_ULOG_INVENTORY_TERMS = (
    "archive",
    "attach",
    "attached",
    "below",
    "content",
    "customer",
    "delete",
    "download",
    "erase",
    "excerpt",
    "open",
    "pasted",
    "raw",
    "remove",
    "stream",
    "upload",
)
SAFE_ULOG_INVENTORY_TERMS = (
    "analyze",
    "available",
    "check",
    "count",
    "do we have",
    "does it have",
    "have",
    "latest",
    "list",
    "log",
    "logs",
    "metadata",
    "parse",
    "report",
    "see",
    "show",
    "stored",
    "summary",
)
WEB_SEARCH_SOURCE_REQUIREMENTS = """Public web-search source requirements:
- Use the web-search evidence for current/public factual claims.
- Prefer official or otherwise reputable sources, and keep the answer concise.
- Preserve citation/source URLs when the web-search response returns them.
- Do not invent URLs. If no citation URLs are available, say the answer needs manual source verification."""
WEB_SEARCH_NO_CITATION_NOTE = (
    "Source note: Public web search ran, but the provider did not return citation URLs for this response. "
    "Verify current/public facts against a trusted source before operational use."
)
DEFAULT_RETRIEVED_CONTEXT_LIMIT = 4
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
    provider_tools: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssistantTurnRecord:
    """Assistant turn plus session and audit metadata."""

    session: AgentSession
    turn: AssistantTurnResult
    audit_event: AuditEvent


@dataclass(frozen=True)
class ProviderToolCompositionResult:
    """Result of optional provider composition over read-only MDS evidence."""

    turn: AssistantTurnResult
    context_documents: tuple[AssistantContextDocument, ...]
    retrieved_context_count_delta: int = 0
    provider_composed_from_tool: bool = False
    provider_composition_error: str = ""


@dataclass(frozen=True)
class ProviderSemanticRewrite:
    """Provider-backed semantic routing rewrite.

    The rewrite is advisory routing evidence only. It is not an answer, approval,
    target authority, or executable tool payload.
    """

    normalized_message: str
    language: str
    route_hint: str
    confidence: float
    needs_clarification: bool = False
    clarification_question: str = ""
    notes: tuple[str, ...] = ()
    provider: str = OPENAI_ASSISTANT_PROVIDER
    model: str = ""
    adapter_version: str = OPENAI_SEMANTIC_REWRITE_ADAPTER_VERSION

    @property
    def usable_for_routing(self) -> bool:
        if self.needs_clarification:
            return False
        if self.confidence < 0.62:
            return False
        return bool(self.normalized_message.strip())

    def public_metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "adapter_version": self.adapter_version,
            "language": self.language,
            "route_hint": self.route_hint,
            "confidence": round(float(self.confidence), 3),
            "needs_clarification": self.needs_clarification,
            "clarification_question_present": bool(self.clarification_question),
            "notes": list(self.notes[:8]),
            "usable_for_routing": self.usable_for_routing,
        }


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


def filter_safe_read_only_sensitive_input_matches(
    matches: tuple[str, ...],
    *,
    message: str,
    routing_message: str = "",
    local_intent: str | None = None,
) -> tuple[str, ...]:
    """Allow safe local inventory questions without weakening provider blocking.

    Raw field artifacts must never be sent to an external provider. A short
    operator question such as "do we have a ULog stored?" or "summarize the
    latest ULog" is different: it asks MDS to inspect already-owned metadata or
    derived local metrics through local read-only tools. Keep that path local
    and deterministic, while still blocking pasted archives, excerpts, raw
    content, downloads, deletes, streams, or customer field evidence.
    """

    if not matches:
        return ()
    intent = str(local_intent or "").strip()
    allowed = SAFE_READ_ONLY_SENSITIVE_MATCHES_BY_INTENT.get(intent)
    if not allowed or any(match not in allowed for match in matches):
        return matches
    text = " ".join((message or "", routing_message or "")).casefold()
    if not (re.search(r"\bulogs?\b", text) or ".ulg" in text):
        return matches
    if any(term in text for term in UNSAFE_ULOG_INVENTORY_TERMS):
        return matches
    if not any(term in text for term in SAFE_ULOG_INVENTORY_TERMS):
        return matches
    return ()


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
        citations = _url_citations_from_response(response_payload)
        citation_count = len(citations)
        if enable_web_search and web_search_used and citation_count == 0:
            content = _append_web_search_no_citation_note(content)

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
            provider_tools={
                "web_search_requested": bool(enable_web_search),
                "web_search_returned": bool(web_search_used),
                "citation_count": citation_count,
                "source_status": _web_search_source_status(
                    requested=bool(enable_web_search),
                    returned=bool(web_search_used),
                    citation_count=citation_count,
                ),
            },
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
            input_text = f"{input_text}\n\n{WEB_SEARCH_SOURCE_REQUIREMENTS}"
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


def rewrite_operator_message_with_provider(
    *,
    config: AssistantConfig,
    message: str,
    conversation_topic: str = "",
    runtime_mode: str = "",
    previous_action_summary: str = "",
) -> ProviderSemanticRewrite | None:
    """Use OpenAI as a semantic routing normalizer for authenticated chat.

    The provider receives no fleet telemetry, logs, IPs, coordinates, secrets, or
    runtime evidence. It only sees the operator message and a small public
    vocabulary/route contract so it can correct typos, language, tone, and
    wrong-but-inferable technical wording. The returned text is fed back into
    the local typed planner; it does not execute or approve anything.
    """

    if config.provider != OPENAI_ASSISTANT_PROVIDER:
        return None
    adapter = _adapter_for_config(config)
    if not isinstance(adapter, OpenAIResponsesAssistantAdapter):
        return None
    original = str(message or "").strip()
    if not original:
        return None

    request_payload = {
        "operator_message": original[:4000],
        "conversation_topic": str(conversation_topic or "")[:80],
        "runtime_mode": str(runtime_mode or "")[:40],
        "previous_action_summary": str(previous_action_summary or "")[:240],
        "routing_contract": {
            "allowed_task_kinds": [
                "read_status",
                "general_question",
                "draft_sitl_lifecycle_action",
                "draft_flight_action",
                "confirm_pending_action",
                "reject_pending_action",
                "clarify",
            ],
            "important_domains": [
                "MDS",
                "Simurgh",
                "GCS",
                "SITL",
                "PX4",
                "MAVLink",
                "fleet",
                "drone telemetry",
                "ULog",
                "logs",
                "Smart Swarm",
                "QuickScout",
                "MCP",
            ],
            "action_boundary": "Only normalize intent text. Do not approve, execute, or create tool payloads.",
        },
    }
    payload = {
        "model": config.openai.model,
        "instructions": _semantic_rewrite_instructions(),
        "input": json.dumps(request_payload, ensure_ascii=False, sort_keys=True),
        "max_output_tokens": min(max(config.openai.max_output_tokens, 200), 700),
        "reasoning": {"effort": "low"},
        "text": {"format": {"type": "text"}, "verbosity": "low"},
        "store": False,
        "include": [],
        "tools": [],
        "tool_choice": "none",
        "parallel_tool_calls": False,
        "metadata": {
            "mds_component": "simurgh_semantic_rewrite",
            "mds_execution": "none",
            "mds_web_search": "disabled",
        },
    }
    response = adapter._post_response(payload, api_key=config.openai.read_api_key())
    text = adapter._extract_response_text(response)
    decoded = _extract_semantic_rewrite_json(text)
    if not decoded:
        raise AgentRuntimeError("OpenAI semantic rewrite did not return valid JSON")
    return _semantic_rewrite_from_payload(decoded, config=config)


def _semantic_rewrite_instructions() -> str:
    return """You are the semantic-understanding layer for Simurgh, an MDS drone GCS assistant.

Return exactly one JSON object and no Markdown.

Your job:
- infer what the operator means across typos, wrong technical words, mixed language, casual tone, and expert shorthand;
- rewrite the operator request into concise English routing text that preserves all numbers, units, directions, drone IDs, draft IDs, wait times, and ordering;
- classify only the task kind; never answer the user and never execute or approve anything.

Rules:
- If the operator intends Simurgh to make a SITL/simulator/drone instance available for testing, normalize that as a draft_sitl_lifecycle_action.
- If the operator is only asking how to do something, for docs, or for a procedure, do not convert it into an action.
- If the operator gives a flight sequence, preserve the full sequence in normalized_message.
- If the operator asks for status/readiness/telemetry/log/ULog/system state, normalize as read_status.
- If the operator says confirm/cancel with a draft id, preserve that exact id.
- If multiple safety-relevant meanings are genuinely possible, set needs_clarification=true and ask one short clarification.
- Do not include private state, tool payloads, code blocks, or explanations.

JSON schema:
{
  "normalized_message": "string",
  "language": "BCP47 or short language label",
  "route_hint": "read_status|general_question|draft_sitl_lifecycle_action|draft_flight_action|confirm_pending_action|reject_pending_action|clarify",
  "confidence": 0.0,
  "needs_clarification": false,
  "clarification_question": "",
  "notes": ["short-safe-note"]
}"""


def _extract_semantic_rewrite_json(text: str) -> Mapping[str, Any] | None:
    candidate = str(text or "").strip()
    if not candidate:
        return None
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate).strip()
    try:
        decoded = json.loads(candidate)
    except ValueError:
        match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
        if not match:
            return None
        try:
            decoded = json.loads(match.group(0))
        except ValueError:
            return None
    return decoded if isinstance(decoded, Mapping) else None


def _semantic_rewrite_from_payload(
    payload: Mapping[str, Any],
    *,
    config: AssistantConfig,
) -> ProviderSemanticRewrite:
    normalized = re.sub(r"\s+", " ", str(payload.get("normalized_message") or "")).strip()
    language = str(payload.get("language") or "").strip()[:40]
    route_hint = str(payload.get("route_hint") or "").strip().lower().replace("-", "_")[:80]
    try:
        confidence = float(payload.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    notes_raw = payload.get("notes")
    notes: list[str] = []
    if isinstance(notes_raw, list):
        notes = [str(item).strip()[:120] for item in notes_raw if str(item).strip()]
    if route_hint not in {
        "read_status",
        "general_question",
        "draft_sitl_lifecycle_action",
        "draft_flight_action",
        "confirm_pending_action",
        "reject_pending_action",
        "clarify",
    }:
        route_hint = "clarify" if bool(payload.get("needs_clarification")) else "general_question"
    return ProviderSemanticRewrite(
        normalized_message=normalized,
        language=language or "unknown",
        route_hint=route_hint,
        confidence=confidence,
        needs_clarification=bool(payload.get("needs_clarification")),
        clarification_question=str(payload.get("clarification_question") or "").strip()[:240],
        notes=tuple(notes),
        model=config.openai.model,
    )


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


def _append_web_search_no_citation_note(text: str) -> str:
    clean = str(text or "").rstrip()
    if not clean or WEB_SEARCH_NO_CITATION_NOTE in clean:
        return clean
    return f"{clean}\n\n{WEB_SEARCH_NO_CITATION_NOTE}"


def _web_search_source_status(*, requested: bool, returned: bool, citation_count: int) -> str:
    if not requested:
        return "not_requested"
    if citation_count > 0:
        return "citations_returned"
    if returned:
        return "search_returned_without_citations"
    return "search_requested_without_returned_call"


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
    if _has_public_upstream_lookup_signal(normalized):
        return True
    if _has_mds_private_or_state_signal(normalized):
        return False
    if _has_public_current_or_lookup_signal(normalized):
        return True
    return local_intent is None and query_plan.domain == "general" and query_plan.confidence < 0.4


def _has_public_upstream_lookup_signal(normalized: str) -> bool:
    """Allow current public upstream lookups without leaking MDS installation state."""

    if not _has_any_text(
        normalized,
        (
            "latest",
            "newest",
            "upstream",
            "official release",
            "release version",
            "stable version",
            "current release",
            "current version",
        ),
    ):
        return False
    if _has_any_text(
        normalized,
        (
            "our drone",
            "our drones",
            "this drone",
            "this gcs",
            "this mds",
            "installed",
            "running on",
            "configured",
            "fleet",
            "telemetry",
            "heartbeat",
            "netbird",
            "ip",
            "drone 1",
            "drone 2",
            "drone 3",
        ),
    ):
        return False
    return _has_any_text(
        normalized,
        (
            "px4",
            "ardupilot",
            "mavlink",
            "mavsdk",
            "qgroundcontrol",
            "qgc",
            "gazebo",
            "ros 2",
            "ros2",
            "mapbox",
            "openai",
            "n8n",
            "mcp",
        ),
    )


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


def _previous_evidence_followup_kind(message: str) -> str | None:
    """Detect answer-level follow-ups that should bind to prior evidence.

    This is intentionally generic conversation plumbing. It gives authenticated
    dashboard chat a chance to reason over the previous assistant answer instead
    of re-entering stale topic routing for short prompts like "is that bad?".
    """

    normalized = re.sub(r"\s+", " ", str(message or "").strip().casefold())
    if not normalized or len(normalized) > 240:
        return None
    if _conversation_transform_kind(normalized):
        return None
    if _previous_evidence_source_followup_signal(normalized):
        return "source_previous_evidence"
    if _previous_evidence_open_followup_signal(normalized):
        return "open_previous_evidence"
    if _has_any_text(
        normalized,
        (
            "field instruction",
            "field instructions",
            "operator checklist",
            "field checklist",
            "make a checklist",
            "make this a checklist",
            "summarize as checklist",
            "summarise as checklist",
            "summarize this as field",
            "summarise this as field",
            "tell the field team",
            "send to field team",
            "handoff instruction",
            "handoff instructions",
            "handoff to operator",
            "brief the operator",
            "brief the pilot",
            "brief the field tester",
        ),
    ):
        return "field_brief_previous_evidence"
    if _has_any_text(
        normalized,
        (
            "what does this mean",
            "what does it mean",
            "what does that mean",
            "what do they mean",
            "what are these",
            "what are those",
            "explain this",
            "explain that",
            "explain these",
            "explain those",
            "interpret this",
            "interpret that",
            "meaning",
            "why is this",
            "why did it",
        ),
    ):
        return "explain_previous_evidence"
    if _has_any_text(
        normalized,
        (
            "is that bad",
            "is this bad",
            "is it bad",
            "is that wrong",
            "is this wrong",
            "does this mean something is wrong",
            "does it mean something is wrong",
            "does thsi mean sth is wrong",
            "something wrong",
            "should i worry",
            "should we worry",
            "is this a blocker",
            "is it a blocker",
            "is it safe",
            "safe to continue",
            "severity",
            "impact",
            "flight blocker",
        ),
    ):
        return "assess_previous_evidence"
    if _has_any_text(
        normalized,
        (
            "what should i do",
            "what should we do",
            "what do i do",
            "what do we do",
            "what next",
            "next step",
            "next steps",
            "how to fix",
            "how should i fix",
            "recommendation",
            "recommend",
            "what is the plan",
        ),
    ):
        return "next_steps_previous_evidence"
    return None


def _previous_evidence_source_followup_signal(normalized: str) -> bool:
    if _looks_like_capability_catalog_query(normalized):
        return False
    if _has_any_text(
        normalized,
        (
            "exact source",
            "source exactly",
            "where did you get",
            "where did this come from",
            "source link",
            "show source",
            "show me the source",
        ),
    ):
        return True
    if re.search(r"\b(api|apis|endpoint|endpoints|route|routes|tool|tools|doc|docs|source)(?:/source)?\b.{0,80}\bdid you use\b", normalized):
        return True
    if re.search(r"\bwhich\s+(api|endpoint|route|tool|doc|source)s?\b.{0,80}\bdid you use\b", normalized):
        return True
    return False


def _previous_evidence_open_followup_signal(normalized: str) -> bool:
    if _looks_like_capability_catalog_query(normalized):
        return False
    if _has_any_text(
        normalized,
        (
            "where can i open",
            "where can we open",
            "where do i open",
            "where do we open",
            "where can i check",
            "where can we check",
            "where should i check",
            "where should we check",
            "open this",
            "open it",
            "open that",
            "give me link",
            "give me the link",
            "send link",
        ),
    ):
        return True
    return bool(re.search(r"\b(which|what)\s+(page|screen)\b.{0,80}\b(did you use|shows? (this|it|that)|can i check|can we check)\b", normalized))


def _looks_like_capability_catalog_query(normalized: str) -> bool:
    if _has_any_text(normalized, ("did you use", "exact source", "where did you get", "source link", "show source")):
        return False
    if _looks_like_mcp_client_setup_query(normalized):
        return True
    return _has_any_text(
        normalized,
        (
            "what read-only api",
            "what read only api",
            "what apis/tools",
            "what api/tools",
            "what tools can",
            "what apis can",
            "what api can",
            "which tools can",
            "which apis can",
            "capability surface",
            "capability menu",
            "capabilities",
            "tool catalog",
            "tool menu",
            "mcp menu",
            "can simurgh use",
            "can you use",
        ),
    )


def _looks_like_mcp_client_setup_query(normalized: str) -> bool:
    if not _has_any_text(normalized, ("mcp", "model context protocol")):
        return False
    if not _has_any_text(
        normalized,
        (
            "n8n",
            "claude",
            "claude desktop",
            "vs code",
            "vscode",
            "custom agent",
            "custom ai agent",
            "client",
            "connector",
            "external agent",
        ),
    ):
        return False
    return _has_any_text(
        normalized,
        (
            "connect",
            "address",
            "url",
            "endpoint",
            "port",
            "auth",
            "token",
            "scope",
            "consideration",
            "considerations",
            "setup",
            "configure",
            "use",
        ),
    )


def is_previous_evidence_followup_message(message: str) -> bool:
    """Return whether a short operator message should bind to prior evidence."""

    return _previous_evidence_followup_kind(message) is not None


def _previous_read_only_evidence_context_document(previous_evidence: str) -> AssistantContextDocument | None:
    raw = str(previous_evidence or "").strip()
    if not raw:
        return None
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"raw": raw[:1000]}
    if isinstance(parsed, Mapping):
        compact = _compact_read_only_evidence_metadata(parsed)
        text = json.dumps(compact or parsed, sort_keys=True, indent=2, default=str)
    else:
        text = json.dumps(parsed, sort_keys=True, indent=2, default=str)
    return AssistantContextDocument(
        id="session.previous_read_only_mds_evidence",
        title="Previous read-only MDS evidence metadata in this chat",
        uri="mds://simurgh/session/previous-read-only-mds-evidence",
        mime_type="application/json",
        summary="Bounded private metadata for the previous read-only MDS evidence used to answer a follow-up.",
        tags=("session", "conversation", "previous-evidence", "read-only"),
        content_hash=stable_payload_hash({"previous_read_only_evidence": text}),
        text=text[:DEFAULT_RETRIEVED_CONTEXT_MAX_CHARS],
    )


def _previous_evidence_followup_message(
    *,
    operator_message: str,
    followup_kind: str,
    previous_domain: str,
    previous_intent: str,
) -> str:
    domain_label = previous_domain or "unknown"
    intent_label = previous_intent or "unknown"
    return "\n".join(
        [
            f"Operator follow-up: {operator_message}",
            f"Conversation task: {followup_kind}.",
            f"Previous MDS topic: {domain_label}.",
            f"Previous read-only intent: {intent_label}.",
            "Use `session.previous_assistant_answer` as the primary source because it is what the operator just saw.",
            "Use `session.previous_read_only_mds_evidence` only as supporting metadata about the previous read-only tool/evidence source.",
            "If the task is source_previous_evidence, name the exact prior evidence source, registry tool ids, docs paths, and API route metadata present in context. Do not invent links or sources.",
            "If the task is open_previous_evidence, provide only real dashboard links already present in the previous answer plus docs paths present in evidence; keep API paths as inline code unless a known docs link is present.",
            "If the task is field_brief_previous_evidence, turn the previous answer into a concise operator checklist with preconditions, checks, caution, and no-action status. Do not add new facts.",
            "Answer the follow-up directly and conversationally. Do not repeat the full prior table/list unless the operator explicitly asks to see it again.",
            "Preserve exact numbers, IPs, routes, timestamps, modes, safety caveats, and no-action statements already present in the previous answer.",
            "Do not invent live state, do not claim a new check was performed, do not expose hidden secrets, and do not imply any drone/config action was executed.",
        ]
    )


def _read_only_tool_evidence_context_document(
    *,
    tool_intent: str,
    tool_ids: list[str],
    response_mode: str,
    content: str,
    evidence_metadata: Mapping[str, object] | None = None,
) -> AssistantContextDocument:
    evidence = str(content or "").strip()
    intent = str(tool_intent or "read_only_mds_tool").strip() or "read_only_mds_tool"
    mode = str(response_mode or "status").strip() or "status"
    tool_ids_text = ", ".join(tool_ids) or "none"
    compact_evidence = _compact_read_only_evidence_metadata(evidence_metadata)
    evidence_summary = str(compact_evidence.get("summary") or "").strip()
    document_text = evidence
    if evidence_summary:
        document_text = f"Structured evidence summary: {evidence_summary}\n\n{evidence}"
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
                "evidence": compact_evidence,
                "content": evidence,
            }
        ),
        text=document_text[:DEFAULT_RETRIEVED_CONTEXT_BUDGET_BYTES],
    )


def _compact_read_only_evidence_metadata(value: Mapping[str, object] | None) -> dict[str, object]:
    """Return audit/session-safe evidence metadata without copying raw answer text."""

    if not isinstance(value, Mapping):
        return {}
    raw_items = value.get("items")
    first_item = raw_items[0] if isinstance(raw_items, list) and raw_items and isinstance(raw_items[0], Mapping) else {}
    compact_items: list[dict[str, object]] = []
    source_refs: list[dict[str, object]] = []
    if isinstance(raw_items, list):
        for raw_item in raw_items[:6]:
            if not isinstance(raw_item, Mapping):
                continue
            item_metadata = raw_item.get("metadata") if isinstance(raw_item.get("metadata"), Mapping) else {}
            compact_item: dict[str, object] = {
                "id": str(raw_item.get("id") or "")[:160],
                "title": str(raw_item.get("title") or "")[:200],
                "summary": str(raw_item.get("summary") or "")[:360],
                "source": str(raw_item.get("source") or "")[:120],
                "kind": str(raw_item.get("kind") or "")[:120],
                "tool_ids": [str(tool_id)[:160] for tool_id in raw_item.get("tool_ids", [])]
                if isinstance(raw_item.get("tool_ids"), list)
                else [],
            }
            if isinstance(item_metadata, Mapping):
                safe_metadata: dict[str, object] = {}
                for key in ("route_method", "route_path", "route_template", "status_code", "truncated", "response_mode", "content_hash", "content_chars", "safety_note_count"):
                    metadata_value = item_metadata.get(key)
                    if metadata_value in (None, ""):
                        continue
                    if isinstance(metadata_value, bool):
                        safe_metadata[key] = metadata_value
                    elif isinstance(metadata_value, int):
                        safe_metadata[key] = metadata_value
                    else:
                        safe_metadata[key] = str(metadata_value)[:240]
                raw_source_refs = item_metadata.get("source_refs")
                if isinstance(raw_source_refs, list):
                    item_refs = _compact_source_refs(raw_source_refs)
                    if item_refs:
                        safe_metadata["source_refs"] = item_refs
                        source_refs.extend(item_refs)
                if safe_metadata:
                    compact_item["metadata"] = safe_metadata
            compact_items.append(compact_item)
    deduped_source_refs: list[dict[str, object]] = []
    seen_source_refs: set[str] = set()
    for ref in source_refs:
        key = json.dumps(ref, sort_keys=True, separators=(",", ":"), default=str)
        if key in seen_source_refs:
            continue
        seen_source_refs.add(key)
        deduped_source_refs.append(ref)
        if len(deduped_source_refs) >= 8:
            break
    return {
        "intent": str(value.get("intent") or ""),
        "response_mode": str(value.get("response_mode") or ""),
        "tool_ids": [str(tool_id) for tool_id in value.get("tool_ids", [])] if isinstance(value.get("tool_ids"), list) else [],
        "source": str(value.get("source") or ""),
        "content_hash": str(value.get("content_hash") or ""),
        "item_count": int(value.get("item_count") or 0),
        "summary": str(first_item.get("summary") or "")[:280] if isinstance(first_item, Mapping) else "",
        "items": compact_items,
        "source_refs": deduped_source_refs,
    }


def _compact_source_refs(raw_refs: object) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    if not isinstance(raw_refs, list):
        return refs
    for raw_ref in raw_refs[:8]:
        if not isinstance(raw_ref, Mapping):
            continue
        ref: dict[str, object] = {}
        for key in ("tool_id", "title", "source", "route_method", "route_path", "route_template"):
            value = str(raw_ref.get(key) or "").strip()
            if value:
                ref[key] = value[:240]
        status_code = raw_ref.get("status_code")
        if isinstance(status_code, int):
            ref["status_code"] = status_code
        if "truncated" in raw_ref:
            ref["truncated"] = bool(raw_ref.get("truncated"))
        docs = raw_ref.get("docs")
        if isinstance(docs, list):
            safe_docs = [str(doc)[:240] for doc in docs[:6] if str(doc or "").startswith("docs/")]
            if safe_docs:
                ref["docs"] = safe_docs
        if ref:
            refs.append(ref)
    return refs


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


def compose_read_only_tool_turn_with_provider(
    *,
    config: AssistantConfig,
    operator_message: str,
    base_turn: AssistantTurnResult,
    context_documents: tuple[AssistantContextDocument, ...],
    tool_intent: str,
    tool_ids: list[str],
    response_mode: str,
    evidence_metadata: Mapping[str, object] | None,
    language_profile: LanguageProfile | None = None,
    first_safety_note: str = "Read-only Simurgh advisory registry tool was executed before provider composition.",
) -> ProviderToolCompositionResult:
    """Optionally compose a natural final answer from read-only tool evidence.

    This helper is intentionally outside MCP/tool execution. MCP remains a
    deterministic evidence surface; dashboard chat may ask the provider to turn
    that evidence into a clearer operator answer when the request is
    authenticated and the configured provider is available.
    """

    if config.provider != OPENAI_ASSISTANT_PROVIDER:
        return ProviderToolCompositionResult(turn=base_turn, context_documents=context_documents)
    if str(tool_intent or "") in LOCAL_PROVIDER_COMPOSITION_DISABLED_INTENTS:
        return ProviderToolCompositionResult(turn=base_turn, context_documents=context_documents)

    adapter = _adapter_for_config(config)
    if not isinstance(adapter, OpenAIResponsesAssistantAdapter):
        return ProviderToolCompositionResult(turn=base_turn, context_documents=context_documents)

    evidence_document = _read_only_tool_evidence_context_document(
        tool_intent=str(tool_intent or ""),
        tool_ids=tool_ids,
        response_mode=str(response_mode or "status"),
        content=base_turn.content,
        evidence_metadata=evidence_metadata,
    )
    provider_context_documents = (*context_documents, evidence_document)
    try:
        provider_turn = adapter.generate(
            message=_provider_tool_composition_message(
                operator_message=operator_message,
                tool_intent=str(tool_intent or ""),
                response_mode=str(response_mode or "status"),
            ),
            context_documents=provider_context_documents,
            language_profile=language_profile or detect_language_profile(operator_message),
        )
    except AgentRuntimeError as exc:
        return ProviderToolCompositionResult(
            turn=base_turn,
            context_documents=context_documents,
            provider_composition_error=_safe_provider_composition_error(exc),
        )

    return ProviderToolCompositionResult(
        turn=replace(
            provider_turn,
            context_documents=provider_context_documents,
            safety_notes=(
                first_safety_note,
                "OpenAI Responses API composed the final text from bounded read-only MDS evidence with store=false.",
                "No direct drone API, MAVSDK command, raw GCS command, or mission mutation was exposed.",
            ),
        ),
        context_documents=provider_context_documents,
        retrieved_context_count_delta=1,
        provider_composed_from_tool=True,
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


def _looks_like_public_geography_frame_followup(message: str) -> bool:
    """Detect geography follow-ups that depend on the previous public place.

    Operators often ask "how long would that loop be?" or "10 km around it?"
    after a coordinate answer. The routing layer should bind those pronouns to
    the current public-geography frame without exposing raw chat history.
    """

    normalized = re.sub(r"\s+", " ", str(message or "").strip().casefold())
    if not normalized or len(normalized) > 180:
        return False
    if not _has_any_text(normalized, ("it", "that", "there", "same place", "same peak", "same point")):
        return False
    return _has_any_text(
        normalized,
        (
            "km",
            "kilometer",
            "kilometers",
            "radius",
            "around",
            "circle",
            "loop",
            "orbit",
            "circumference",
            "distance",
            "flight around",
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
    if not (
        _looks_like_public_geography_frame_reply(original_message)
        or _looks_like_public_geography_frame_followup(original_message)
    ):
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


def _previous_evidence_followup_fallback_turn(
    *,
    config: AssistantConfig,
    followup_kind: str,
    previous_answer: str,
    context_documents: tuple[AssistantContextDocument, ...],
) -> AssistantTurnResult:
    """Deterministic fallback when prior evidence exists but provider cannot compose."""

    compact_lines = []
    for raw_line in str(previous_answer or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("|") or line.lower().startswith("time\t"):
            continue
        compact_lines.append(line)
        if len(compact_lines) >= 4:
            break
    quoted = "\n".join(f"- {line}" for line in compact_lines) or "- Previous read-only answer is available in this chat session."
    if followup_kind == "assess_previous_evidence":
        lead = "Based only on the previous read-only Simurgh answer, I would treat this as something to interpret before acting, not as proof of a new drone action or live-state change."
    elif followup_kind == "next_steps_previous_evidence":
        lead = "Based only on the previous read-only Simurgh answer, the next step is to verify the relevant GCS page/log/source before changing anything."
    elif followup_kind in {"source_previous_evidence", "open_previous_evidence"}:
        lead = "Based only on the previous read-only Simurgh answer, these are the source clues I can safely carry forward. I cannot invent a new source or claim a fresh check."
    elif followup_kind == "field_brief_previous_evidence":
        lead = "Field brief from the previous read-only Simurgh answer only. Treat this as an operator checklist, not as a new live check or action approval."
    else:
        lead = "Based only on the previous read-only Simurgh answer, here is the relevant context I can safely carry forward."
    content = "\n\n".join(
        (
            lead,
            quoted,
            "No fresh check, config write, mission action, or drone command was attempted for this follow-up.",
        )
    )
    return AssistantTurnResult(
        id=f"turn-{uuid.uuid4().hex}",
        created_at=utc_now().isoformat(),
        provider=READ_TOOL_PROVIDER if config.provider == OPENAI_ASSISTANT_PROVIDER else config.provider,
        model=READ_TOOL_MODEL if config.provider == OPENAI_ASSISTANT_PROVIDER else MOCK_ASSISTANT_MODEL,
        adapter_version="previous-evidence-fallback-v1",
        content=content,
        context_documents=context_documents,
        blocked_intents=(),
        safety_notes=(
            "Previous read-only Simurgh evidence was interpreted locally because provider composition was unavailable.",
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
    read_only_plan = build_mds_read_only_plan(routing_message, conversation_topic=conversation_topic)
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
    sensitive_matches = filter_safe_read_only_sensitive_input_matches(
        sensitive_matches,
        message=normalized_message,
        routing_message=routing_message,
        local_intent=read_only_plan.intent,
    )
    local_intent = None
    tool_result = None
    tool_intent = None
    tool_response_mode = None
    tool_ids: list[str] = []
    read_only_evidence: dict[str, object] = {}
    web_search_enabled_for_turn = False
    provider_composed_from_tool = False
    provider_composition_error = ""
    provider_composed_from_previous_evidence = False
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

    evidence_followup_kind = _previous_evidence_followup_kind(routing_message)
    evidence_followup_answer = previous_context.get("last_assistant_content") if evidence_followup_kind else ""
    evidence_followup_metadata = previous_context.get("last_read_only_evidence") if evidence_followup_kind else ""
    if (
        force_provider is None
        and tool_intent is None
        and allow_provider_for_local_tools
        and evidence_followup_kind
        and evidence_followup_answer
        and evidence_followup_metadata
        and not blocked_matches
        and not sensitive_matches
    ):
        previous_document = _previous_answer_context_document(evidence_followup_answer)
        evidence_document = _previous_read_only_evidence_context_document(evidence_followup_metadata)
        followup_context_documents = (*context_documents, previous_document)
        followup_session_context_count = 1
        if evidence_document is not None:
            followup_context_documents = (*followup_context_documents, evidence_document)
            followup_session_context_count += 1
        adapter = _adapter_for_config(config)
        if isinstance(adapter, OpenAIResponsesAssistantAdapter):
            try:
                turn = adapter.generate(
                    message=_previous_evidence_followup_message(
                        operator_message=normalized_message,
                        followup_kind=evidence_followup_kind,
                        previous_domain=str(previous_context.get("last_domain") or conversation_topic or ""),
                        previous_intent=str(previous_context.get("last_tool_intent") or previous_context.get("last_intent") or ""),
                    ),
                    context_documents=followup_context_documents,
                    language_profile=language_profile,
                )
            except AgentRuntimeError as exc:
                if not _is_provider_runtime_recoverable(exc):
                    raise
                turn = _previous_evidence_followup_fallback_turn(
                    config=config,
                    followup_kind=evidence_followup_kind,
                    previous_answer=evidence_followup_answer,
                    context_documents=followup_context_documents,
                )
                provider_composition_error = _safe_provider_composition_error(exc)
            context_documents = followup_context_documents
            retrieved_context_count = followup_session_context_count
            provider_composed_from_previous_evidence = turn.provider == OPENAI_ASSISTANT_PROVIDER
            tool_intent = "evidence_followup"
            tool_response_mode = "followup"
            try:
                parsed_previous_evidence = json.loads(evidence_followup_metadata)
            except json.JSONDecodeError:
                parsed_previous_evidence = {}
            read_only_evidence = _compact_read_only_evidence_metadata(
                parsed_previous_evidence if isinstance(parsed_previous_evidence, Mapping) else None
            )
        else:
            tool_result = None

    if force_provider is None and tool_intent is None:
        local_intent = read_only_plan.intent
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

    if tool_intent in {"conversation_transform", "evidence_followup"}:
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
        raw_evidence = structured.get("evidence") if isinstance(structured, Mapping) else None
        read_only_evidence = _compact_read_only_evidence_metadata(
            raw_evidence if isinstance(raw_evidence, Mapping) else None
        )
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
            composition = compose_read_only_tool_turn_with_provider(
                config=config,
                operator_message=normalized_message,
                base_turn=local_tool_turn,
                context_documents=context_documents,
                tool_intent=str(tool_intent or ""),
                tool_ids=tool_ids,
                response_mode=str(tool_response_mode or query_plan.response_mode),
                evidence_metadata=raw_evidence if isinstance(raw_evidence, Mapping) else None,
                language_profile=language_profile,
            )
            turn = composition.turn
            context_documents = composition.context_documents
            retrieved_context_count += composition.retrieved_context_count_delta
            provider_composed_from_tool = composition.provider_composed_from_tool
            provider_composition_error = composition.provider_composition_error
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
            "last_read_only_evidence": json.dumps(read_only_evidence, sort_keys=True, separators=(",", ":"))
            if read_only_evidence
            else "",
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
            "read_only_evidence": read_only_evidence,
            "response_mode": final_response_mode,
            "query_domain": query_plan.domain,
            "query_confidence": round(float(query_plan.confidence), 3),
            "query_unclear": query_plan.unclear,
            "query_reason": query_plan.reason,
            "read_only_plan": read_only_plan.public_metadata(),
            "retrieved_context_count": retrieved_context_count,
            "web_search_enabled": web_search_enabled_for_turn,
            "provider_tools": dict(turn.provider_tools or {}),
            "provider_composed_from_tool": provider_composed_from_tool,
            "provider_composed_from_previous_evidence": provider_composed_from_previous_evidence,
            "evidence_followup_kind": evidence_followup_kind if tool_intent == "evidence_followup" else None,
            "provider_composition_error": provider_composition_error,
            "turn_intent": (
                dict(metadata.get("turn_intent") or {})
                if isinstance(metadata, Mapping) and isinstance(metadata.get("turn_intent"), Mapping)
                else {}
            ),
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
