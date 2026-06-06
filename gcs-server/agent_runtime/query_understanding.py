"""Top-level query understanding for Simurgh assistant turns.

This module intentionally stays deterministic and provider-neutral. It does not
answer questions and it does not execute tools; it builds a small retrieval plan
that the assistant can use before provider generation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from .query_adaptation import normalize_operator_query_text


QUERY_DOMAINS = frozenset(
    {
        "drone_show",
        "fleet",
        "sar",
        "swarm",
        "sitl",
        "setup",
        "logs",
        "runtime",
        "capabilities",
        "safety",
        "mcp",
        "ui",
        "docs",
        "general",
    }
)

QUERY_RESPONSE_MODES = frozenset({"status", "interpret", "workflow", "compare", "capability", "clarify"})

STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "can",
    "do",
    "for",
    "from",
    "give",
    "have",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "the",
    "there",
    "this",
    "to",
    "we",
    "what",
    "where",
    "with",
    "you",
}

DOMAIN_SIGNALS: Mapping[str, tuple[str, ...]] = {
    "drone_show": ("drone show", "skybrush", "show design", "show package", "upload", "uploaded", "launch mode"),
    "fleet": (
        "fleet",
        "drone",
        "drones",
        "vehicle",
        "vehicles",
        "board",
        "boards",
        "cm4",
        "scout",
        "ip",
        "sys_id",
        "configured",
        "connected",
        "online",
        "telemetry",
        "gps",
        "coordinate",
        "coordinates",
        "latitude",
        "longitude",
        "altitude",
    ),
    "sar": (
        "sar",
        "search and rescue",
        "quickscout",
        "quick scout",
        "quick scoute",
        "mission workspace",
        "mission finding",
        "mission findings",
        "mission status",
        "search area",
        "coverage",
        "handoff",
        "reconnaissance",
        "scout mission",
    ),
    "swarm": ("swarm", "formation", "cluster", "offset", "follow", "geometry", "trajectory"),
    "sitl": ("sitl", "simulation", "simulator", "demo"),
    "setup": ("setup", "set up", "install", "companion", "raspberry", "cm4", "board", "third drone", "new drone"),
    "logs": ("log", "logs", "warning", "error", "backend", "trace", "audit"),
    "runtime": ("runtime", "mode", "real", "provider", "model", "circuit breaker", "always confirm"),
    "capabilities": (
        "capability",
        "capabilities",
        "tool",
        "tools",
        "api capabilities",
        "mcp tools",
        "what can simurgh",
        "what can you do",
    ),
    "safety": ("safe", "safety", "policy", "approval", "confirm", "risk", "circuit breaker"),
    "mcp": ("mcp", "claude", "n8n", "client", "connector", "tools/list", "resources/list"),
    "ui": ("dashboard", "page", "button", "chat", "copy", "screen", "ui", "ux", "sidebar"),
    "docs": ("doc", "docs", "documentation", "guide", "manual", "link", "read"),
}

DOMAIN_TAGS: Mapping[str, tuple[str, ...]] = {
    "drone_show": ("show", "drone-show", "skybrush", "mission"),
    "fleet": ("fleet", "config", "telemetry"),
    "sar": ("sar", "quickscout", "mission"),
    "swarm": ("swarm", "trajectory", "mission"),
    "sitl": ("sitl",),
    "setup": ("setup", "fleet", "environment"),
    "logs": ("logs",),
    "runtime": ("runtime", "environment", "simurgh"),
    "capabilities": ("simurgh", "tools", "mcp"),
    "safety": ("safety", "policy"),
    "mcp": ("mcp", "tools", "simurgh"),
    "ui": ("dashboard", "operator"),
    "docs": (),
    "general": (),
}

DOMAIN_EXPANSIONS: Mapping[str, str] = {
    "drone_show": "drone show SkyBrush upload readiness duration validation safety report launch modes",
    "fleet": "fleet drone board configuration IP SYS_ID connectivity telemetry GPS coordinates altitude presence",
    "sar": "QuickScout SAR search rescue mission status workspace findings coverage handoff",
    "swarm": "swarm formation cluster offsets trajectory mission planning",
    "sitl": "SITL simulation demo runtime startup",
    "setup": "MDS setup companion computer fleet enrollment environment keys",
    "logs": "GCS logs warning error backend audit operation meaning",
    "runtime": "MDS runtime mode real SITL provider model circuit breaker always confirm",
    "capabilities": "Simurgh capabilities MCP tools API actions read only",
    "safety": "Simurgh safety policy approval circuit breaker operational boundaries",
    "mcp": "MCP clients tools resources n8n Claude Desktop VS Code connector",
    "ui": "dashboard Simurgh page settings chat user interface",
    "docs": "MDS documentation guide manual reference",
    "general": "Simurgh MDS operator assistant help capabilities docs",
}


@dataclass(frozen=True)
class AssistantQueryPlan:
    """Small, safe plan for retrieval and provider context assembly."""

    domain: str
    response_mode: str
    normalized_message: str
    search_queries: tuple[str, ...]
    tags: tuple[str, ...]
    confidence: float
    unclear: bool
    reason: str

    def public_metadata(self) -> dict[str, object]:
        return {
            "domain": self.domain,
            "response_mode": self.response_mode,
            "confidence": round(float(self.confidence), 3),
            "unclear": self.unclear,
            "reason": self.reason,
            "tags": list(self.tags),
            "search_query_count": len(self.search_queries),
        }


def build_assistant_query_plan(message: str, *, conversation_topic: str | None = None) -> AssistantQueryPlan:
    """Infer a bounded retrieval plan from an operator message."""

    normalized = normalize_query_text(message)
    tokens = _query_terms(normalized)
    topic = normalize_query_text(conversation_topic or "")
    domain, confidence, reason = _infer_domain(normalized, tokens, topic=topic)
    response_mode = _infer_response_mode(normalized, domain=domain, token_count=len(tokens))
    unclear = _looks_unclear(normalized, tokens, confidence=confidence)
    if unclear:
        response_mode = "clarify"
        if confidence < 0.2:
            domain = "general"
            reason = "low-signal prompt"
    tags = DOMAIN_TAGS.get(domain, ())
    search_queries = _build_search_queries(normalized, domain=domain, tokens=tokens)
    return AssistantQueryPlan(
        domain=domain if domain in QUERY_DOMAINS else "general",
        response_mode=response_mode if response_mode in QUERY_RESPONSE_MODES else "status",
        normalized_message=normalized,
        search_queries=search_queries,
        tags=tags,
        confidence=confidence,
        unclear=unclear,
        reason=reason,
    )


def normalize_query_text(value: str) -> str:
    return normalize_operator_query_text(value)


def _infer_domain(normalized: str, tokens: tuple[str, ...], *, topic: str) -> tuple[str, float, str]:
    if _looks_like_general_information_query(normalized):
        return "general", 0.85, "general information question"
    scores: dict[str, float] = {domain: 0.0 for domain in DOMAIN_SIGNALS}
    for domain, signals in DOMAIN_SIGNALS.items():
        for signal in signals:
            if _signal_in_query(normalized, signal):
                scores[domain] += 2.0 if " " in signal else 1.0
    if topic in QUERY_DOMAINS:
        competing_signal = any(
            score > 0 and domain not in {topic, "docs", "general"}
            for domain, score in scores.items()
        )
        if not competing_signal:
            scores[topic] = scores.get(topic, 0.0) + 1.5
        elif scores.get(topic, 0.0) > 0:
            scores[topic] = scores.get(topic, 0.0) + 0.5
    if not tokens:
        return "general", 0.0, "no searchable terms"
    best_domain, best_score = max(scores.items(), key=lambda item: (item[1], item[0]))
    if best_score <= 0:
        return "general", 0.15, "no domain signal"
    confidence = min(1.0, best_score / max(3.0, len(tokens)))
    return best_domain, confidence, "domain signal match"


def _infer_response_mode(normalized: str, *, domain: str, token_count: int) -> str:
    if domain == "general" and _looks_like_general_information_query(normalized):
        return "interpret"
    if token_count <= 1:
        return "clarify"
    if _has_any(normalized, ("what does", "what mean", "meaning", "explain", "why", "impact", "should i worry")):
        return "interpret"
    if _has_any(normalized, ("how", "what should", "workflow", "step", "steps", "next step", "next steps", "setup", "set up", "script", "scripts", "where", "guide", "doc", "docs", "link", "connect", "configure", "configuration", "integrate", "integration")):
        return "workflow"
    if _has_any(normalized, ("difference", "different", "compare", "versus", " vs ")):
        return "compare"
    if domain in {"capabilities", "mcp"} and _has_any(
        normalized,
        ("capability", "capabilities", "tool", "tools", "api capabilities", "mcp", "what can simurgh", "what can you do"),
    ):
        return "capability"
    return "status"


def _looks_unclear(normalized: str, tokens: tuple[str, ...], *, confidence: float) -> bool:
    if not normalized or len(tokens) == 0:
        return True
    if len(tokens) == 1 and confidence < 0.5:
        return True
    letters = re.findall(r"[a-z]", normalized)
    if len(letters) >= 6:
        vowels = sum(1 for letter in letters if letter in "aeiou")
        if vowels / max(1, len(letters)) < 0.2:
            return True
    if confidence < 0.2 and tokens:
        weak_tokens = 0
        for token in tokens:
            if len(token) >= 4 and not re.search(r"[aeiou]", token):
                weak_tokens += 1
        if weak_tokens == len(tokens):
            return True
    return False


def _build_search_queries(normalized: str, *, domain: str, tokens: tuple[str, ...]) -> tuple[str, ...]:
    queries: list[str] = []
    if normalized:
        queries.append(normalized)
    if domain in DOMAIN_EXPANSIONS:
        token_prefix = " ".join(tokens[:8])
        queries.append((token_prefix + " " + DOMAIN_EXPANSIONS[domain]).strip())
    if domain != "general":
        queries.append(DOMAIN_EXPANSIONS[domain])
    else:
        queries.append(" ".join(tokens[:8]) or DOMAIN_EXPANSIONS["general"])
    return tuple(dict.fromkeys(query for query in queries if query))


def _query_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    for term in re.findall(r"[a-z0-9][a-z0-9_-]{1,}", query.lower()):
        normalized = term.replace("_", "-")
        if normalized not in STOPWORDS:
            terms.append(normalized)
    return tuple(dict.fromkeys(terms))


def _has_any(value: str, terms: tuple[str, ...]) -> bool:
    for term in terms:
        term = term.strip()
        if not term:
            continue
        if re.fullmatch(r"[a-z0-9_-]+", term):
            if re.search(rf"\b{re.escape(term)}\b", value):
                return True
            continue
        if term in value:
            return True
    return False


def _looks_like_general_information_query(normalized: str) -> bool:
    if _has_any(
        normalized,
        (
            "status",
            "current status",
            "configured",
            "connected",
            "online",
            "offline",
            "heartbeat",
            "telemetry",
            "ip",
            "fleet",
            "swarm",
            "drone show",
            "logs",
            "warning",
            "error",
            "runtime",
        ),
    ):
        return False
    if _has_any(normalized, ("weather", "forecast", "wind today", "rain today")):
        return True
    if _looks_like_external_reference_query(normalized):
        return True
    if not _has_any(
        normalized,
        ("what is", "what are", "define", "definition", "meaning of", "explain", "tell me about"),
    ):
        return False
    return _has_any(normalized, ("drone", "drones", "uav", "uavs", "uas", "mavlink", "mavlink protocol"))


def _looks_like_external_reference_query(normalized: str) -> bool:
    if _looks_like_public_upstream_reference_query(normalized):
        return True
    if _has_any(
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
        ),
    ):
        return False
    return _has_any(
        normalized,
        (
            "how far",
            "how many km",
            "how many kilometer",
            "how many kilometers",
            "kilometer",
            "kilometers",
            " km",
            " miles",
            "distance from",
            "distance between",
            "latitude",
            "longitude",
            "lat long",
            "lat lon",
            "lat/lon",
            "lat and long",
            "lat/long",
            "wgs84",
            "altitude",
            "elevation",
            "height",
            "coordinates",
            "coordinate of",
            "mountain",
            "peak",
            "damavand",
            "tehran",
            "new york",
            "capital of",
            "population of",
            "who is",
            "when is",
            "where is",
            "calculate",
            "convert",
            "regulation",
            "regulations",
            "law",
            "rules",
            "internet",
            "web search",
            "search the web",
            "search internet",
        ),
    )


def _looks_like_public_upstream_reference_query(normalized: str) -> bool:
    if not _has_any(
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
            "latest docs",
            "latest documentation",
        ),
    ):
        return False
    if _has_any(
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
    return _has_any(
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


def _signal_in_query(value: str, signal: str) -> bool:
    marker = str(signal or "").strip()
    if not marker:
        return False
    if re.fullmatch(r"[a-z0-9_-]+", marker):
        return re.search(rf"\b{re.escape(marker)}\b", value) is not None
    return marker in value
