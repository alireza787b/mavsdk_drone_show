from __future__ import annotations

from agent_runtime.query_adaptation import (
    adapt_operator_query,
    load_default_query_adaptation_config,
    normalize_operator_query_text,
)
from agent_runtime.language import detect_language_profile


def test_query_adaptation_loads_reviewed_config():
    config = load_default_query_adaptation_config()

    assert config.version == 1
    assert len(config.rules) >= 20
    assert any(rule.id == "concept.drone_show" for rule in config.rules)


def test_query_adaptation_normalizes_typos_without_raw_trace_text():
    adaptation = adapt_operator_query("waht is the scoute droen IP?")

    assert adaptation.routing_text == "what is the scout drone ip"
    assert adaptation.strategy == "english-canonical-routing"
    assert "typo.scout" in adaptation.applied_rules
    metadata = adaptation.public_metadata()
    assert metadata["applied_rule_count"] >= 3
    assert "scoute" not in str(metadata)


def test_query_adaptation_maps_french_fleet_prompt_for_routing():
    profile = detect_language_profile("Combien de drones sont configurés maintenant ?")
    adaptation = adapt_operator_query(
        "Combien de drones sont configurés maintenant ?",
        language_profile=profile,
    )

    assert adaptation.input_language == "fr"
    assert adaptation.routing_language == "en"
    assert adaptation.strategy == "config-governed-cross-language-routing"
    assert "how many" in adaptation.routing_text
    assert "drone" in adaptation.routing_text
    assert "configured" in adaptation.routing_text


def test_query_adaptation_maps_persian_show_status_prompt_for_routing():
    adaptation = adapt_operator_query("نمایش پهپاد آپلود شده و آماده است؟")

    assert adaptation.input_language == "fa"
    assert adaptation.routing_language == "en"
    assert "drone show" in adaptation.routing_text
    assert "uploaded loaded" in adaptation.routing_text
    assert "ready" in adaptation.routing_text
    assert "non-english-or-non-latin-input" in adaptation.notes


def test_normalize_operator_query_text_is_legacy_safe():
    assert normalize_operator_query_text("circuit brake") == "circuit breaker"
    assert normalize_operator_query_text("whay are the differnt modes?") == "what are the different modes"
    assert normalize_operator_query_text("does thsi mean sth is wrong?") == "does this mean something is wrong"
    assert "warning" in normalize_operator_query_text("report any warnign in gcs")
    assert "fleet status" in normalize_operator_query_text("current flee status")
    assert "swarm mission ready" in normalize_operator_query_text("searm mission reay")
    assert "have telemetry and ready" in normalize_operator_query_text("ahve telmreya nd ready")
    assert "takeoff now to 10m" == normalize_operator_query_text("take of now to 10m")
    assert "report when created and ready" in normalize_operator_query_text("reprot when created and ready")
    assert "wait there for about 10s" in normalize_operator_query_text("wait there tfor about 10s")
    assert "drone 1" in normalize_operator_query_text("dorne 1")
