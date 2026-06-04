"""Structured read-only evidence primitives for Simurgh.

The assistant should not have to reverse-engineer facts from rendered Markdown.
These models carry a compact, sanitized evidence envelope alongside local and
registry-backed read-only answers so follow-up routing, audit, MCP, and future
provider composition can share the same source-of-truth metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .models import stable_payload_hash


DEFAULT_EVIDENCE_SOURCE = "local_read_only_mds"
REGISTRY_EVIDENCE_SOURCE = "registry_read_only_mds"
DEFAULT_EVIDENCE_KIND = "read_only_answer"


@dataclass(frozen=True)
class ReadOnlyEvidenceItem:
    """One compact public-safe evidence item used by Simurgh composers."""

    id: str
    title: str
    summary: str
    source: str = DEFAULT_EVIDENCE_SOURCE
    kind: str = DEFAULT_EVIDENCE_KIND
    tool_ids: tuple[str, ...] = ()
    confidence: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def public_metadata(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "source": self.source,
            "kind": self.kind,
            "tool_ids": list(self.tool_ids),
            "confidence": round(float(self.confidence), 3),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ReadOnlyEvidenceBundle:
    """Structured evidence envelope for one read-only Simurgh answer."""

    intent: str
    response_mode: str
    tool_ids: tuple[str, ...]
    items: tuple[ReadOnlyEvidenceItem, ...]
    content_hash: str
    source: str = DEFAULT_EVIDENCE_SOURCE

    @classmethod
    def from_answer(
        cls,
        *,
        intent: str,
        response_mode: str,
        tool_ids: Sequence[str],
        content: str,
        safety_notes: Sequence[str] = (),
        source: str = DEFAULT_EVIDENCE_SOURCE,
        summary: str | None = None,
    ) -> "ReadOnlyEvidenceBundle":
        normalized_intent = _safe_identifier(intent, fallback="read_only_answer")
        normalized_mode = _safe_identifier(response_mode, fallback="status")
        normalized_tool_ids = tuple(str(tool_id).strip() for tool_id in tool_ids if str(tool_id).strip())
        text = str(content or "").strip()
        digest = stable_payload_hash(
            {
                "intent": normalized_intent,
                "response_mode": normalized_mode,
                "tool_ids": normalized_tool_ids,
                "content": text,
            }
        )
        normalized_source = str(source or DEFAULT_EVIDENCE_SOURCE).strip() or DEFAULT_EVIDENCE_SOURCE
        summary_text = str(summary or "").strip()
        if not summary_text:
            summary_text = _first_meaningful_line(text)
        summary_text = summary_text or f"Read-only Simurgh evidence for {normalized_intent}."
        item = ReadOnlyEvidenceItem(
            id=f"evidence.{normalized_intent}",
            title=_title_from_intent(normalized_intent),
            summary=summary_text[:280],
            source=normalized_source,
            kind="answer_summary",
            tool_ids=normalized_tool_ids,
            confidence=1.0,
            metadata={
                "content_hash": digest,
                "content_chars": len(text),
                "response_mode": normalized_mode,
                "safety_note_count": len(tuple(safety_notes)),
            },
        )
        return cls(
            intent=normalized_intent,
            response_mode=normalized_mode,
            tool_ids=normalized_tool_ids,
            items=(item,),
            content_hash=digest,
            source=normalized_source,
        )

    @classmethod
    def from_route_tool_result(
        cls,
        *,
        tool_id: str,
        tool_title: str,
        route_method: str | None,
        route_path: str | None,
        content: str,
        summary: str,
        status_code: int | None,
        truncated: bool,
        response_mode: str = "status",
        safety_notes: Sequence[str] = (),
    ) -> "ReadOnlyEvidenceBundle":
        """Build compact evidence for one registry-backed read-only route call."""

        normalized_tool_id = _safe_identifier(tool_id, fallback="registry_tool")
        normalized_mode = _safe_identifier(response_mode, fallback="status")
        text = str(content or "").strip()
        digest = stable_payload_hash(
            {
                "tool_id": normalized_tool_id,
                "route_method": route_method,
                "route_path": route_path,
                "status_code": status_code,
                "truncated": truncated,
                "content": text,
            }
        )
        title = str(tool_title or normalized_tool_id).strip() or normalized_tool_id
        summary_text = str(summary or "").strip() or f"Read-only registry evidence for {normalized_tool_id}."
        item = ReadOnlyEvidenceItem(
            id=f"evidence.registry.{normalized_tool_id}",
            title=title,
            summary=f"{title}: {summary_text}"[:280],
            source=REGISTRY_EVIDENCE_SOURCE,
            kind="route_result_summary",
            tool_ids=(normalized_tool_id,),
            confidence=1.0 if status_code is not None and status_code < 400 else 0.4,
            metadata={
                "content_hash": digest,
                "content_chars": len(text),
                "response_mode": normalized_mode,
                "route_method": str(route_method or "GET"),
                "route_path": str(route_path or ""),
                "status_code": status_code,
                "truncated": bool(truncated),
                "safety_note_count": len(tuple(safety_notes)),
            },
        )
        return cls(
            intent=f"registry.{normalized_tool_id}",
            response_mode=normalized_mode,
            tool_ids=(normalized_tool_id,),
            items=(item,),
            content_hash=digest,
            source=REGISTRY_EVIDENCE_SOURCE,
        )

    def public_metadata(self) -> dict[str, Any]:
        summary = self.items[0].summary if self.items else ""
        return {
            "intent": self.intent,
            "response_mode": self.response_mode,
            "tool_ids": list(self.tool_ids),
            "source": self.source,
            "summary": summary,
            "content_hash": self.content_hash,
            "item_count": len(self.items),
            "items": [item.public_metadata() for item in self.items],
        }

    def context_summary(self) -> str:
        """Return a short plain-text summary for provider/context prompts."""

        if not self.items:
            tool_text = ", ".join(self.tool_ids) or "none"
            return f"Read-only evidence: {self.intent}; tools: {tool_text}."
        first = self.items[0]
        return f"{first.title}: {first.summary}"


def _safe_identifier(value: object, *, fallback: str) -> str:
    text = re.sub(r"[^a-z0-9_.:-]+", "_", str(value or "").strip().casefold()).strip("_.:-")
    return text or fallback


def _title_from_intent(intent: str) -> str:
    return " ".join(part.capitalize() for part in str(intent or "read_only_answer").replace("_", " ").split())


def _first_meaningful_line(text: str) -> str:
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("|") or line.startswith("---"):
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        return line
    return ""
