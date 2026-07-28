"""Numeric grounding helpers for semantic plans and the local fallback parser.

Provider-backed interpretation is language-neutral and only uses numeric-token
grounding from this module. The small English identity matcher remains solely
for the deterministic provider-outage fallback in ``action_planner``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


_SINGULAR_TARGET_RE = re.compile(
    r"\b(?:drone|vehicle|aircraft|hw|hardware|instance|container|sys[_\s-]*id)"
    r"\s*[-#:=]?\s*(?P<id>\d+)\b",
    re.IGNORECASE,
)
_PLURAL_TARGET_RE = re.compile(
    r"\b(?:drones|vehicles|aircraft|instances|containers)\s+"
    r"(?P<ids>\d+(?:\s*(?:,|and|&|\+)\s*\d+)*)",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?")
_TARGET_ID_PLACEHOLDER = "{id}"
_CONTEXTUAL_TARGET_RE = re.compile(
    r"\b(?:"
    r"it|its|them|their|"
    r"this|that|these|those|"
    r"the\s+(?:drone|vehicle|aircraft)|"
    r"this\s+(?:drone|vehicle|aircraft)|"
    r"that\s+(?:drone|vehicle|aircraft)|"
    r"same\s+(?:drone|vehicle|aircraft)|"
    r"previous\s+(?:drone|vehicle|aircraft|target)|"
    r"last\s+(?:drone|vehicle|aircraft|target)"
    r")\b",
    re.IGNORECASE,
)
_ALL_TARGETS_RE = re.compile(
    r"\b(?:all|every|both|multiple|several)\s+"
    r"(?:drone|drones|vehicle|vehicles|aircraft|targets)\b",
    re.IGNORECASE,
)


def canonical_target_id(value: object) -> str:
    """Return the canonical positive integer identity used by fleet targets."""

    stripped = str(value or "").strip().lstrip("+")
    if not stripped.isdigit():
        return ""
    target = int(stripped)
    return str(target) if target > 0 else ""


def canonical_numeric_token(value: object) -> str:
    """Return a script-neutral comparison key for a numeric token."""

    try:
        numeric = float(str(value).strip())
        if numeric == 0:
            numeric = 0.0
        return f"{numeric:g}"
    except (TypeError, ValueError):
        return ""


def extract_numeric_tokens(messages: Iterable[str]) -> tuple[str, ...]:
    """Return every numeric occurrence without assigning language semantics."""

    values: list[str] = []
    for raw_message in messages:
        for match in _NUMBER_RE.finditer(str(raw_message or "")):
            value = canonical_numeric_token(match.group(0))
            if value:
                values.append(value)
    return tuple(values)


def extract_explicit_target_ids(messages: Iterable[str]) -> tuple[str, ...]:
    """Return English-marked IDs for the deterministic offline fallback only."""

    values: list[str] = []
    for raw_message in messages:
        message = str(raw_message or "")
        for match in _SINGULAR_TARGET_RE.finditer(message):
            target = canonical_target_id(match.group("id"))
            if target and target not in values:
                values.append(target)
        for match in _PLURAL_TARGET_RE.finditer(message):
            for item in re.findall(r"\d+", match.group("ids")):
                target = canonical_target_id(item)
                if target and target not in values:
                    values.append(target)
    return tuple(values)


def refers_to_contextual_target(message: str) -> bool:
    """Return whether a read/action prompt refers back to an existing target.

    This is the small deterministic English fallback. Provider-backed semantic
    routing handles multilingual references, while local routing uses this only
    with already-grounded structured target IDs.
    """

    text = str(message or "")
    return bool(_CONTEXTUAL_TARGET_RE.search(text)) and not explicitly_requests_all_targets(text)


def explicitly_requests_all_targets(message: str) -> bool:
    """Return whether a prompt explicitly broadens scope beyond prior targets."""

    text = str(message or "")
    return bool(
        _ALL_TARGETS_RE.search(text)
        or re.search(r"\b(?:whole|entire)\s+fleet\b", text, flags=re.IGNORECASE)
    )


def structured_target_ids(payload: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Extract target identities from typed action/runtime fields only."""

    if not isinstance(payload, Mapping):
        return ()
    values: list[str] = []

    def append(raw: object) -> None:
        target = canonical_target_id(raw)
        if target and target not in values:
            values.append(target)

    for key in ("target_drone_ids", "target_drones", "inferred_target_drone_ids"):
        raw_values = payload.get(key)
        if isinstance(raw_values, (list, tuple)):
            for item in raw_values:
                append(item)

    instance_names = payload.get("instance_names")
    if isinstance(instance_names, (list, tuple)):
        for name in instance_names:
            match = re.fullmatch(r"drone-(\d+)", str(name or "").strip(), flags=re.IGNORECASE)
            if match:
                append(match.group(1))

    for key in ("instance_id", "hw_id"):
        append(payload.get(key))
    return tuple(values)


def materialize_target_binding(
    binding: Mapping[str, Any] | None,
    target_ids: Iterable[object],
) -> tuple[str, list[str]]:
    """Map canonical runtime target IDs into a registry-declared string array."""

    if not isinstance(binding, Mapping):
        return "", []
    argument = str(binding.get("argument") or "").strip()
    template = str(binding.get("value_template") or "").strip()
    if not argument or template.count(_TARGET_ID_PLACEHOLDER) != 1:
        return "", []
    values: list[str] = []
    for raw_target_id in target_ids:
        target_id = str(raw_target_id or "").strip()
        if not target_id:
            continue
        value = template.replace(_TARGET_ID_PLACEHOLDER, target_id)
        if value and value not in values:
            values.append(value)
    return argument, values
