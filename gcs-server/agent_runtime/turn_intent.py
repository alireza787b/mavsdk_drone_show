"""Turn-level semantic routing frame for Simurgh assistant requests.

This module is intentionally provider-neutral. It does not answer questions,
execute tools, approve actions, or bypass the circuit breaker. Its job is to
build one structured interpretation of the operator turn so downstream routing
does not ask several brittle classifiers independently and make inconsistent
decisions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .action_planner import (
    ActionDraft,
    build_flight_action_draft,
    build_sitl_reconcile_action_draft,
    is_action_confirmation_message,
    is_action_rejection_message,
    looks_like_action_replay_request,
    looks_like_direct_flight_action_request,
    looks_like_direct_sitl_lifecycle_request,
    looks_like_flight_followup_action_request,
)
from .mds_read_tools import MdsReadOnlyPlan, build_mds_read_only_plan
from .query_adaptation import normalize_operator_query_text
from .query_understanding import AssistantQueryPlan, build_assistant_query_plan


TURN_INTENT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ActionIntentFrame:
    """Structured action interpretation for one operator turn."""

    request_message: str
    routing_message: str
    draft: ActionDraft | None
    direct_flight_request: bool
    flight_followup_request: bool
    sitl_lifecycle_request: bool
    replayed_previous_request: bool

    @property
    def has_action_request(self) -> bool:
        return bool(
            self.draft is not None
            or self.direct_flight_request
            or self.flight_followup_request
            or self.sitl_lifecycle_request
            or self.replayed_previous_request
        )

    def public_metadata(self) -> dict[str, Any]:
        return {
            "request_message_replayed": self.replayed_previous_request,
            "direct_flight_request": self.direct_flight_request,
            "flight_followup_request": self.flight_followup_request,
            "sitl_lifecycle_request": self.sitl_lifecycle_request,
            "draft_ready": bool(self.draft.ready) if self.draft is not None else False,
            "draft_type": (
                self.draft.public_payload().get("draft_type")
                if self.draft is not None
                else None
            ),
            "draft_tool_id": (
                self.draft.public_payload().get("tool_id")
                if self.draft is not None
                else None
            ),
            "draft_missing_arguments": (
                list(self.draft.public_payload().get("missing_arguments") or [])
                if self.draft is not None
                else []
            ),
        }


@dataclass(frozen=True)
class TurnIntentFrame:
    """One coherent interpretation used by Simurgh route orchestration."""

    schema_version: int
    original_message: str
    routing_message: str
    conversation_topic: str
    query_plan: AssistantQueryPlan
    read_only_plan: MdsReadOnlyPlan
    confirmation_message: bool
    rejection_message: bool
    explicit_action_draft_id: str
    action: ActionIntentFrame
    route: str
    confidence: float
    reasons: tuple[str, ...]

    @property
    def is_action_route(self) -> bool:
        return self.route == "action_draft"

    @property
    def is_confirmation_route(self) -> bool:
        return self.route == "action_confirmation"

    @property
    def is_rejection_route(self) -> bool:
        return self.route == "action_rejection"

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "route": self.route,
            "confidence": round(float(self.confidence), 3),
            "reasons": list(self.reasons),
            "conversation_topic": self.conversation_topic,
            "confirmation_message": self.confirmation_message,
            "rejection_message": self.rejection_message,
            "explicit_action_draft_id": self.explicit_action_draft_id,
            "query": self.query_plan.public_metadata(),
            "read_only": self.read_only_plan.public_metadata(),
            "action": self.action.public_metadata(),
        }


def build_turn_intent_frame(
    message: str,
    *,
    conversation_topic: str | None = None,
    previous_action: Mapping[str, Any] | None = None,
    previous_action_request_message: str = "",
    semantic_routing_message: str | None = None,
    draft_id_factory: Callable[[], str] | None = None,
) -> TurnIntentFrame:
    """Return the single routing frame for an assistant turn.

    The frame deliberately gives fresh action requests priority over bare
    confirmation wording. Operators often say "send it to test flight..." when
    they are introducing a new plan, not approving an old draft.
    """

    original_message = str(message or "")
    semantic_message = str(semantic_routing_message or "").strip()
    routing_message = normalize_operator_query_text(semantic_message or original_message)
    topic = str(conversation_topic or "").strip()
    query_plan = build_assistant_query_plan(routing_message, conversation_topic=topic)
    read_only_plan = build_mds_read_only_plan(routing_message, conversation_topic=topic)

    replayed_message = ""
    if looks_like_action_replay_request(routing_message):
        replayed_message = str(previous_action_request_message or "").strip()
    action_message = replayed_message or semantic_message or original_message
    action_routing_message = normalize_operator_query_text(action_message)

    direct_flight = looks_like_direct_flight_action_request(action_routing_message)
    flight_followup = looks_like_flight_followup_action_request(
        action_routing_message,
        conversation_topic=topic,
    )
    sitl_lifecycle = looks_like_direct_sitl_lifecycle_request(
        action_routing_message,
        conversation_topic=topic,
    )
    action_requested = bool(replayed_message or direct_flight or flight_followup or sitl_lifecycle)
    draft = None
    if action_requested:
        draft_id = _new_draft_id(draft_id_factory)
        draft = build_flight_action_draft(
            action_message,
            draft_id=draft_id,
            previous_action=previous_action,
        )
        if draft is None:
            draft = build_sitl_reconcile_action_draft(
                action_message,
                draft_id=draft_id,
                conversation_topic=topic,
            )

    explicit_draft_id = _extract_action_draft_id(routing_message)
    confirmation = _is_semantic_confirmation_message(
        routing_message,
        read_only_plan=read_only_plan,
        action_requested=action_requested,
        explicit_draft_id=explicit_draft_id,
    )
    rejection = is_action_rejection_message(routing_message)

    action_frame = ActionIntentFrame(
        request_message=action_message,
        routing_message=action_routing_message,
        draft=draft,
        direct_flight_request=direct_flight,
        flight_followup_request=flight_followup,
        sitl_lifecycle_request=sitl_lifecycle,
        replayed_previous_request=bool(replayed_message),
    )
    route, confidence, reasons = _choose_route(
        action=action_frame,
        confirmation=confirmation,
        rejection=rejection,
        read_only_plan=read_only_plan,
    )
    return TurnIntentFrame(
        schema_version=TURN_INTENT_SCHEMA_VERSION,
        original_message=original_message,
        routing_message=routing_message,
        conversation_topic=topic,
        query_plan=query_plan,
        read_only_plan=read_only_plan,
        confirmation_message=confirmation,
        rejection_message=rejection,
        explicit_action_draft_id=explicit_draft_id,
        action=action_frame,
        route=route,
        confidence=confidence,
        reasons=reasons,
    )


def _choose_route(
    *,
    action: ActionIntentFrame,
    confirmation: bool,
    rejection: bool,
    read_only_plan: MdsReadOnlyPlan,
) -> tuple[str, float, tuple[str, ...]]:
    reasons: list[str] = []
    if action.draft is not None:
        reasons.append("fresh-action-draft-built")
        if action.replayed_previous_request:
            reasons.append("previous-action-request-replayed")
        return "action_draft", 0.95, tuple(reasons)
    if rejection:
        return "action_rejection", 0.9, ("operator-rejected-action",)
    if confirmation:
        return "action_confirmation", 0.9, ("operator-confirmed-action",)
    if action.has_action_request:
        return "action_draft", 0.65, ("action-request-missing-details",)
    if read_only_plan.intent:
        return "read_only", max(0.4, min(0.95, read_only_plan.confidence)), ("read-only-plan",)
    return "provider_or_registry", 0.25, ("provider-or-registry-routing",)


def _is_semantic_confirmation_message(
    routing_message: str,
    *,
    read_only_plan: MdsReadOnlyPlan,
    action_requested: bool,
    explicit_draft_id: str,
) -> bool:
    """Return whether this turn is truly approving an existing draft.

    This intentionally narrows the older keyword detector. In operator chat,
    phrases such as "go ahead and check status" or "yes, run that same check"
    are task instructions, not action approvals. Exact draft-id approvals and
    short bare approvals remain deterministic.
    """

    if explicit_draft_id:
        return is_action_confirmation_message(routing_message, draft_id=explicit_draft_id)
    if action_requested:
        return False
    if not is_action_confirmation_message(routing_message):
        return False
    normalized = re.sub(r"\s+", " ", str(routing_message or "").casefold()).strip()
    if _looks_like_non_confirmation_task(normalized, read_only_plan=read_only_plan):
        return False
    return True


def _looks_like_non_confirmation_task(normalized: str, *, read_only_plan: MdsReadOnlyPlan) -> bool:
    if not normalized:
        return False
    # Keep short acknowledgements as approvals; longer turns with task language
    # should route through read/action planning instead of approving old drafts.
    task_verbs = (
        "check",
        "show",
        "read",
        "report",
        "summarize",
        "summary",
        "status",
        "inspect",
        "look",
        "find",
        "search",
        "tell me",
        "explain",
        "what",
        "how",
        "why",
    )
    if any(term in normalized for term in task_verbs):
        return True
    if read_only_plan.intent and len(normalized.split()) > 3:
        return True
    return False


def _new_draft_id(factory: Callable[[], str] | None) -> str:
    if factory is not None:
        value = str(factory()).strip()
        if value:
            return value
    import uuid

    return f"act-{uuid.uuid4().hex[:8]}"


def _extract_action_draft_id(message: str) -> str:
    match = re.search(r"\b(act-[0-9a-f]{6,})\b", str(message or "").casefold())
    return match.group(1) if match else ""
