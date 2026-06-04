"""Governed operator-query adaptation for Simurgh routing.

The adapter turns noisy operator text into a safer routing string for intent
classification and retrieval. It is deliberately deterministic, config-driven,
and metadata-only: it does not translate full answers, call a model, or bypass
policy gates.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

from .language import LanguageProfile, detect_language_profile
from .models import AgentRuntimeError


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUERY_ADAPTATION_CONFIG_PATH = REPO_ROOT / "config" / "agent_query_adaptation.yaml"
QUERY_ADAPTATION_CONFIG_ENV = "MDS_AGENT_QUERY_ADAPTATION_FILE"
QUERY_ADAPTATION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class QueryReplacementRule:
    """One reviewed alias-to-canonical routing rule."""

    id: str
    canonical: str
    aliases: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "QueryReplacementRule":
        rule = cls(
            id=str(payload.get("id") or "").strip(),
            canonical=_normalize_for_matching(str(payload.get("canonical") or "")).strip(),
            aliases=tuple(
                _normalize_for_matching(str(alias or "")).strip()
                for alias in payload.get("aliases") or ()
                if str(alias or "").strip()
            ),
        )
        rule.validate()
        return rule

    def validate(self) -> None:
        if not self.id:
            raise AgentRuntimeError("query adaptation rule id is required")
        if not self.canonical:
            raise AgentRuntimeError(f"query adaptation rule {self.id} canonical is required")
        if not self.aliases:
            raise AgentRuntimeError(f"query adaptation rule {self.id} aliases are required")


@dataclass(frozen=True)
class QueryAdaptationConfig:
    """Versioned query-adaptation configuration."""

    version: int
    path: Path
    max_rule_applications: int
    rules: tuple[QueryReplacementRule, ...]

    @classmethod
    def from_file(cls, path: str | Path = DEFAULT_QUERY_ADAPTATION_CONFIG_PATH) -> "QueryAdaptationConfig":
        config_path = Path(path)
        try:
            payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError as exc:
            raise AgentRuntimeError(f"query adaptation config not found: {config_path}") from exc
        if not isinstance(payload, Mapping):
            raise AgentRuntimeError("query adaptation config root must be an object")
        return cls.from_mapping(payload, path=config_path)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, path: Path | None = None) -> "QueryAdaptationConfig":
        raw_rules = payload.get("term_replacements") or ()
        if not isinstance(raw_rules, list):
            raise AgentRuntimeError("query adaptation term_replacements must be a list")
        config = cls(
            version=int(payload.get("version") or 0),
            path=path or DEFAULT_QUERY_ADAPTATION_CONFIG_PATH,
            max_rule_applications=int(payload.get("max_rule_applications") or 80),
            rules=tuple(QueryReplacementRule.from_mapping(item) for item in raw_rules if isinstance(item, Mapping)),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.version != QUERY_ADAPTATION_SCHEMA_VERSION:
            raise AgentRuntimeError(f"unsupported query adaptation config version: {self.version}")
        if self.max_rule_applications <= 0:
            raise AgentRuntimeError("query adaptation max_rule_applications must be positive")
        if not self.rules:
            raise AgentRuntimeError("query adaptation rules must not be empty")
        seen: set[str] = set()
        for rule in self.rules:
            if rule.id in seen:
                raise AgentRuntimeError(f"duplicate query adaptation rule id: {rule.id}")
            seen.add(rule.id)


@dataclass(frozen=True)
class QueryAdaptation:
    """Safe routing view of an operator message."""

    schema_version: int
    routing_text: str
    normalized_text: str
    input_language: str
    input_script: str
    input_tone: str
    routing_language: str
    strategy: str
    confidence: float
    applied_rules: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "input_language": self.input_language,
            "input_script": self.input_script,
            "input_tone": self.input_tone,
            "routing_language": self.routing_language,
            "strategy": self.strategy,
            "confidence": round(float(self.confidence), 3),
            "applied_rules": list(self.applied_rules[:20]),
            "applied_rule_count": len(self.applied_rules),
            "notes": list(self.notes),
        }


def load_default_query_adaptation_config() -> QueryAdaptationConfig:
    """Load the configured query-adaptation rules."""

    raw = os.environ.get(QUERY_ADAPTATION_CONFIG_ENV)
    path = Path(raw) if raw else DEFAULT_QUERY_ADAPTATION_CONFIG_PATH
    if not path.is_absolute():
        path = REPO_ROOT / path
    return _load_query_adaptation_config_from_path(str(path))


@lru_cache(maxsize=8)
def _load_query_adaptation_config_from_path(path: str) -> QueryAdaptationConfig:
    """Load and cache a reviewed adaptation config for one resolved path."""

    return QueryAdaptationConfig.from_file(path)


def adapt_operator_query(
    message: str,
    *,
    language_profile: LanguageProfile | None = None,
    conversation_topic: str | None = None,
    config: QueryAdaptationConfig | None = None,
) -> QueryAdaptation:
    """Return a safe routing text and metadata for one operator query."""

    profile = language_profile or detect_language_profile(message)
    active_config = config or load_default_query_adaptation_config()
    normalized = _normalize_for_matching(message)
    routing_text, applied_rules = _apply_replacement_rules(normalized, active_config)
    notes: list[str] = []
    if conversation_topic:
        notes.append("conversation-topic-available")
    if routing_text != normalized:
        notes.append("canonical-routing-applied")
    if profile.language != "en" or profile.script != "latin":
        notes.append("non-english-or-non-latin-input")
    strategy = _strategy_for(profile=profile, changed=routing_text != normalized)
    return QueryAdaptation(
        schema_version=QUERY_ADAPTATION_SCHEMA_VERSION,
        routing_text=routing_text,
        normalized_text=normalized,
        input_language=profile.language,
        input_script=profile.script,
        input_tone=profile.tone,
        routing_language="en" if applied_rules else profile.language,
        strategy=strategy,
        confidence=_confidence_for(profile=profile, changed=routing_text != normalized, applied_count=len(applied_rules)),
        applied_rules=tuple(applied_rules),
        notes=tuple(dict.fromkeys(notes)),
    )


def normalize_operator_query_text(message: str) -> str:
    """Return just the adapted routing text for legacy classifiers."""

    return adapt_operator_query(message).routing_text


def normalize_matching_text(value: str) -> str:
    """Return cheap deterministic normalization for static aliases and labels."""

    return _normalize_for_matching(value)


def _apply_replacement_rules(value: str, config: QueryAdaptationConfig) -> tuple[str, list[str]]:
    routed = value
    applied: list[str] = []
    applications = 0
    for rule in _rules_longest_alias_first(config.rules):
        for alias in sorted(rule.aliases, key=len, reverse=True):
            if not alias or alias == rule.canonical:
                continue
            pattern = _alias_pattern(alias)
            routed, count = re.subn(pattern, rule.canonical, routed)
            if count:
                applied.append(rule.id)
                applications += count
                if applications >= config.max_rule_applications:
                    return _cleanup_spacing(routed), list(dict.fromkeys(applied))
                break
    return _cleanup_spacing(routed), list(dict.fromkeys(applied))


def _rules_longest_alias_first(rules: tuple[QueryReplacementRule, ...]) -> list[QueryReplacementRule]:
    return sorted(rules, key=lambda rule: max((len(alias) for alias in rule.aliases), default=0), reverse=True)


def _alias_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias)
    if re.fullmatch(r"[a-z0-9][a-z0-9_ -]*", alias):
        return re.compile(rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])")
    return re.compile(escaped)


def _strategy_for(*, profile: LanguageProfile, changed: bool) -> str:
    if profile.language == "en" and profile.script == "latin":
        return "english-canonical-routing" if changed else "english-direct-routing"
    if changed:
        return "config-governed-cross-language-routing"
    if profile.localization_strategy == "provider-rewrite-before-routing-required":
        return "provider-rewrite-needed-for-routing"
    return "provider-or-clarify-for-routing"


def _confidence_for(*, profile: LanguageProfile, changed: bool, applied_count: int) -> float:
    base = float(profile.confidence or 0.0)
    if changed:
        base = max(base, min(0.9, 0.45 + (0.08 * applied_count)))
    return min(1.0, base)


def _normalize_for_matching(value: str) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    text = text.replace("’", "'").replace("`", "'")
    text = _strip_latin_diacritics(text)
    text = re.sub(r"[؟?！!]+", " ", text)
    text = re.sub(r"[,:;()\[\]{}]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _strip_latin_diacritics(value: str) -> str:
    chars: list[str] = []
    decomposed = unicodedata.normalize("NFKD", value)
    for char in decomposed:
        if unicodedata.combining(char):
            continue
        chars.append(char)
    return unicodedata.normalize("NFC", "".join(chars))


def _cleanup_spacing(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
