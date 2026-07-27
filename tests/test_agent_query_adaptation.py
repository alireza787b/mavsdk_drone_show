from __future__ import annotations

from agent_runtime.query_adaptation import (
    adapt_operator_query,
    normalize_operator_query_text,
)
from agent_runtime.mds_read_tools import build_mds_read_only_plan, classify_mds_read_intent
from agent_runtime.language import detect_language_profile


def test_query_adaptation_does_not_guess_typo_semantics():
    adaptation = adapt_operator_query("waht is the scoute droen IP?")

    assert adaptation.routing_text == "waht is the scoute droen ip"
    assert adaptation.normalized_text == adaptation.routing_text
    assert adaptation.strategy == "english-direct-routing"
    assert adaptation.applied_rules == ()
    metadata = adaptation.public_metadata()
    assert metadata["applied_rule_count"] == 0
    assert "waht" not in str(metadata)


def test_query_adaptation_delegates_french_semantics_to_provider():
    profile = detect_language_profile("Combien de drones sont configurés maintenant ?")
    adaptation = adapt_operator_query(
        "Combien de drones sont configurés maintenant ?",
        language_profile=profile,
    )

    assert adaptation.input_language == "fr"
    assert adaptation.routing_language == "fr"
    assert adaptation.strategy == "provider-semantic-routing-required"
    assert adaptation.routing_text == "combien de drones sont configures maintenant"
    assert adaptation.applied_rules == ()


def test_query_adaptation_delegates_persian_semantics_to_provider():
    adaptation = adapt_operator_query("نمایش پهپاد آپلود شده و آماده است؟")

    assert adaptation.input_language == "fa"
    assert adaptation.routing_language == "fa"
    assert adaptation.strategy == "provider-semantic-routing-required"
    assert adaptation.routing_text == "نمایش پهپاد اپلود شده و اماده است"
    assert adaptation.applied_rules == ()
    assert "non-english-or-non-latin-input" in adaptation.notes
    assert "semantic-provider-required" in adaptation.notes


def test_normalize_operator_query_text_is_lexical_only():
    assert normalize_operator_query_text("  Circuit BREAKER?!  ") == "circuit breaker"
    assert normalize_operator_query_text("waht is the scoute droen IP?") == "waht is the scoute droen ip"
    assert normalize_operator_query_text("take of now to 10m") == "take of now to 10m"


def test_sitl_created_vehicle_readiness_routes_to_live_telemetry():
    message = normalize_operator_query_text(
        "give me a summary of the drone sitl we created and if its ready for flight or not ?"
    )

    plan = build_mds_read_only_plan(message, conversation_topic="sitl")

    assert plan.intent == "fleet_connectivity"
    assert plan.tool_ids == (
        "mds.fleet.heartbeats.read",
        "mds.fleet.telemetry.read",
        "mds.fleet.network_status.read",
    )


def test_sitl_created_vehicle_health_followup_routes_to_live_telemetry():
    message = normalize_operator_query_text(
        "you created a drone SITL; now check whether its telemetry is healthy and ready"
    )

    plan = build_mds_read_only_plan(message, conversation_topic="sitl")

    assert plan.intent == "fleet_connectivity"


def test_sitl_setup_help_still_routes_to_docs():
    message = normalize_operator_query_text("how do I create a SITL demo before trying this for real?")

    assert classify_mds_read_intent(message, conversation_topic="sitl") == "sitl_help"
