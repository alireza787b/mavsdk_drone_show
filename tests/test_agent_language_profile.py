from __future__ import annotations

from agent_runtime.language import detect_language_profile, provider_language_guidance


def test_language_profile_detects_english_operator_prompt():
    profile = detect_language_profile("How many drones do we have configured?")

    assert profile.language == "en"
    assert profile.script == "latin"
    assert profile.tone == "operator"
    assert profile.localization_strategy == "english-direct"
    assert "How many" not in str(profile.public_metadata())


def test_language_profile_detects_french_without_translation():
    profile = detect_language_profile("Combien de drones sont configurés maintenant ?")

    assert profile.language == "fr"
    assert profile.script == "latin"
    assert profile.confidence > 0.4
    assert profile.localization_strategy == "same-language-provider-response"


def test_language_profile_detects_persian_script_for_future_provider_rewrite():
    profile = detect_language_profile("چند پهپاد در سیستم تنظیم شده است؟")

    assert profile.language == "fa"
    assert profile.script == "arabic"
    assert profile.localization_strategy == "same-language-provider-response"
    assert "same language" in provider_language_guidance(profile).lower()


def test_language_profile_marks_low_signal_as_unknown():
    profile = detect_language_profile("qrxzz blnk")

    assert profile.language == "unknown"
    assert profile.script == "latin"
    assert profile.localization_strategy == "english-with-clarification-if-needed"
