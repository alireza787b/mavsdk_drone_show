"""Minimal lexical normalization for Simurgh routing.

Natural-language correction and multilingual interpretation belong to the
structured semantic provider. This module only creates a stable matching view
without guessing what the operator meant.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .language import LanguageProfile, detect_language_profile


QUERY_ADAPTATION_SCHEMA_VERSION = 2


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


def adapt_operator_query(
    message: str,
    *,
    language_profile: LanguageProfile | None = None,
    conversation_topic: str | None = None,
) -> QueryAdaptation:
    """Return a normalized matching view without semantic substitutions."""

    profile = language_profile or detect_language_profile(message)
    normalized = _normalize_for_matching(message)
    notes: list[str] = []
    if conversation_topic:
        notes.append("conversation-topic-available")
    if profile.language != "en" or profile.script != "latin":
        notes.append("non-english-or-non-latin-input")
        notes.append("semantic-provider-required")
    return QueryAdaptation(
        schema_version=QUERY_ADAPTATION_SCHEMA_VERSION,
        routing_text=normalized,
        normalized_text=normalized,
        input_language=profile.language,
        input_script=profile.script,
        input_tone=profile.tone,
        routing_language=profile.language,
        strategy=(
            "english-direct-routing"
            if profile.language == "en" and profile.script == "latin"
            else "provider-semantic-routing-required"
        ),
        confidence=min(1.0, float(profile.confidence or 0.0)),
        applied_rules=(),
        notes=tuple(dict.fromkeys(notes)),
    )


def normalize_operator_query_text(message: str) -> str:
    """Return lexical normalization for deterministic canonical fast paths."""

    return adapt_operator_query(message).routing_text


def normalize_matching_text(value: str) -> str:
    """Return cheap deterministic normalization for static aliases and labels."""

    return _normalize_for_matching(value)


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
