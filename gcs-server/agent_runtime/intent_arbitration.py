"""Provider-neutral route commitment rules for Simurgh turns.

The local parser and semantic provider are complementary evidence sources. This
module defines when a locally typed route is complete enough to own the turn,
when provider refinement is still useful, and when a provider outage may fall
back to a guarded local draft without losing conditions or ordered steps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_READ_OPENING_RE = re.compile(
    r"^\s*(?:"
    r"what|which|where|when|why|how|who|"
    r"is|are|am|was|were|do|does|did|has|have|can|could|would|should|"
    r"check|show|report|list|describe|explain|compare|verify|inspect|review|"
    r"tell\s+me|give\s+me"
    r")\b",
    re.IGNORECASE,
)
_READ_CLAUSE_RE = re.compile(
    r"(?:^|[.!?;,]\s*|\b(?:i\s+mean|please)\s+)"
    r"(?:what|which|where|when|why|how|who|is|are|was|were|do|does|did|"
    r"has|have|can|could|would|should)\b",
    re.IGNORECASE,
)
_EMBEDDED_READ_CLAUSE_RE = re.compile(
    r"\b(?:is|are|was|were|do|does|did|has|have|can|could|would|should)\s+"
    r"(?:it|this|that|there|the|a|an|drone|vehicle|aircraft|sitl|simulator)\b",
    re.IGNORECASE,
)
_CONDITIONAL_RE = re.compile(
    r"\b(?:if|unless|when|provided(?:\s+that)?|only\s+if)\b",
    re.IGNORECASE,
)
_REPORTING_WHEN_RE = re.compile(
    r"\b(?:report|notify|monitor|tell\s+me)\s+when\b",
    re.IGNORECASE,
)
_ORDERED_ACTION_RE = re.compile(
    r"\b(?:then|after(?:wards)?|before|next|followed\s+by|wait)\b",
    re.IGNORECASE,
)
_PROVIDER_FIRST_READ_INTENTS = frozenset({"general_knowledge"})
_LOCAL_AUTHORITATIVE_READ_INTENTS = frozenset(
    {
        # These contracts own the operator's current-state question. A
        # provider may not replace live telemetry with origin/configuration
        # prose or turn a readiness question into a command draft.
        "coordinate_geography",
        "fleet_connectivity",
        "fleet_status",
        "origin_status",
    }
)


@dataclass(frozen=True)
class RouteCommitment:
    """The locally proven routing posture for one turn."""

    kind: str
    authoritative: bool
    provider_refinement_needed: bool
    fallback_allowed: bool
    reason: str

    def public_metadata(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "authoritative": self.authoritative,
            "provider_refinement_needed": self.provider_refinement_needed,
            "fallback_allowed": self.fallback_allowed,
            "reason": self.reason,
        }


def analyze_route_commitment(turn_intent: Any) -> RouteCommitment:
    """Return the arbitration posture for a typed turn frame."""

    route = str(getattr(turn_intent, "route", "") or "")
    routing_message = str(getattr(turn_intent, "routing_message", "") or "")
    action = getattr(turn_intent, "action", None)
    draft = getattr(action, "draft", None)
    read_plan = getattr(turn_intent, "read_only_plan", None)

    if route == "action_draft" and draft is not None:
        preconditions = tuple(getattr(draft, "preconditions", ()) or ())
        post_actions = tuple(getattr(draft, "post_actions", ()) or ())
        if _has_unmodeled_action_condition(routing_message) and not preconditions:
            return RouteCommitment(
                kind="action",
                authoritative=False,
                provider_refinement_needed=True,
                fallback_allowed=False,
                reason="local-action-condition-unmodeled",
            )
        if _ORDERED_ACTION_RE.search(routing_message) and not post_actions:
            return RouteCommitment(
                kind="action",
                authoritative=False,
                provider_refinement_needed=True,
                fallback_allowed=False,
                reason="local-action-sequence-unmodeled",
            )
        return RouteCommitment(
            kind="action",
            authoritative=True,
            provider_refinement_needed=True,
            fallback_allowed=True,
            reason="typed-guarded-action-complete",
        )

    if route == "read_only" and read_plan is not None:
        read_intent = str(getattr(read_plan, "intent", "") or "").strip()
        if not read_intent or bool(getattr(read_plan, "unclear", True)):
            return RouteCommitment(
                kind="read",
                authoritative=False,
                provider_refinement_needed=True,
                fallback_allowed=False,
                reason="typed-read-incomplete",
            )
        if read_intent in _PROVIDER_FIRST_READ_INTENTS:
            return RouteCommitment(
                kind="read",
                authoritative=False,
                provider_refinement_needed=True,
                fallback_allowed=True,
                reason="provider-first-general-read",
            )
        if read_intent not in _LOCAL_AUTHORITATIVE_READ_INTENTS:
            return RouteCommitment(
                kind="read",
                authoritative=False,
                provider_refinement_needed=True,
                fallback_allowed=True,
                reason="typed-read-provider-refinement",
            )
        if not _explicit_read_speech_act(routing_message):
            return RouteCommitment(
                kind="read",
                authoritative=False,
                provider_refinement_needed=True,
                fallback_allowed=True,
                reason="typed-read-without-explicit-read-speech-act",
            )
        return RouteCommitment(
            kind="read",
            authoritative=True,
            provider_refinement_needed=False,
            fallback_allowed=True,
            reason="typed-local-read-complete",
        )

    return RouteCommitment(
        kind="semantic",
        authoritative=False,
        provider_refinement_needed=True,
        fallback_allowed=False,
        reason="no-complete-typed-route",
    )


def _explicit_read_speech_act(message: str) -> bool:
    normalized = " ".join(str(message or "").split())
    if not normalized:
        return False
    return bool(
        "?" in normalized
        or _READ_OPENING_RE.search(normalized)
        or _READ_CLAUSE_RE.search(normalized)
        or _EMBEDDED_READ_CLAUSE_RE.search(normalized)
    )


def _has_unmodeled_action_condition(message: str) -> bool:
    """Exclude completion-reporting clauses from true action conditions."""

    normalized = " ".join(str(message or "").split())
    without_reporting = _REPORTING_WHEN_RE.sub("report-on-completion", normalized)
    return bool(_CONDITIONAL_RE.search(without_reporting))
