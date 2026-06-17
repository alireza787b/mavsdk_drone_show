from __future__ import annotations

import pytest

from agent_runtime.query_understanding import build_assistant_query_plan, normalize_query_text


@pytest.mark.parametrize(
    (
        "message",
        "conversation_topic",
        "expected_domain",
        "expected_mode",
        "expected_tags",
        "expected_terms",
        "expected_unclear",
    ),
    (
        (
            "waht is the scoute droen IP?",
            None,
            "fleet",
            "status",
            ("fleet",),
            ("scout", "drone", "ip"),
            False,
        ),
        (
            "what does this warning mean?",
            "logs",
            "logs",
            "interpret",
            ("logs",),
            ("warning", "mean"),
            False,
        ),
        (
            "is there any uploaded?",
            "drone_show",
            "drone_show",
            "status",
            ("show", "skybrush"),
            ("uploaded", "drone show"),
            False,
        ),
        (
            "connect n8n or claude desktop to simurgh mcp",
            None,
            "mcp",
            "workflow",
            ("mcp", "tools", "simurgh"),
            ("n8n", "claude", "mcp"),
            False,
        ),
        (
            "What's the difference between QuickScout and Swarm Trajectory?",
            None,
            "swarm",
            "compare",
            ("swarm", "trajectory"),
            ("quickscout", "swarm", "trajectory"),
            False,
        ),
        (
            "how do I create a SITL demo?",
            None,
            "sitl",
            "workflow",
            ("sitl",),
            ("sitl", "demo"),
            False,
        ),
        (
            "environment variables openai key circuit breaker always confirm",
            None,
            "runtime",
            "status",
            ("runtime", "environment", "simurgh"),
            ("openai", "circuit breaker", "always confirm"),
            False,
        ),
        (
            "what scripts and docs should I use now?",
            "setup",
            "setup",
            "workflow",
            ("setup",),
            ("scripts", "docs"),
            False,
        ),
        (
            "and the scout IP?",
            "fleet",
            "fleet",
            "status",
            ("fleet",),
            ("scout", "ip"),
            False,
        ),
        (
            "can you report any warnign if exist last 30 minutes in gcs?",
            "fleet",
            "logs",
            "status",
            ("logs",),
            ("warning", "gcs"),
            False,
        ),
        (
            "qrxzz blnk",
            None,
            "general",
            "clarify",
            (),
            ("qrxzz", "blnk"),
            True,
        ),
        (
            "what is a drone?",
            "fleet",
            "general",
            "interpret",
            (),
            ("drone",),
            False,
        ),
        (
            "how is the weather today?",
            "fleet",
            "general",
            "interpret",
            (),
            ("weather",),
            False,
        ),
    ),
)
def test_query_planner_routes_operator_prompts(
    message,
    conversation_topic,
    expected_domain,
    expected_mode,
    expected_tags,
    expected_terms,
    expected_unclear,
):
    plan = build_assistant_query_plan(message, conversation_topic=conversation_topic)

    assert plan.domain == expected_domain
    assert plan.response_mode == expected_mode
    assert plan.unclear is expected_unclear
    for tag in expected_tags:
        assert tag in plan.tags
    searchable_text = " ".join((plan.normalized_message, *plan.search_queries))
    for term in expected_terms:
        assert term in searchable_text


def test_query_planner_public_metadata_is_bounded_and_safe():
    plan = build_assistant_query_plan("connect n8n to Simurgh MCP")
    metadata = plan.public_metadata()

    assert metadata == {
        "domain": "mcp",
        "response_mode": "workflow",
        "confidence": metadata["confidence"],
        "unclear": False,
        "reason": "domain signal match",
        "tags": ["mcp", "tools", "simurgh"],
        "search_query_count": len(plan.search_queries),
    }
    assert 0 < metadata["confidence"] <= 1


def test_public_upstream_lookup_takes_precedence_over_online_connectivity_wording():
    plan = build_assistant_query_plan(
        "What is the latest stable PX4 Autopilot release? Verify it online and cite the source."
    )

    assert plan.domain == "general"
    assert plan.response_mode == "interpret"
    assert plan.reason == "general information question"


def test_query_normalization_covers_field_typo_shapes():
    assert normalize_query_text("waht is the scoute droen IP?") == "what is the scout drone ip"
    assert normalize_query_text("circuit brake") == "circuit breaker"
    assert normalize_query_text("cehck latest gxs logs") == "check latest gcs logs"
    assert normalize_query_text("whay are the differnt launch modes?") == "what are the different launch modes"
