"""Language and tone profiling for Simurgh assistant turns.

This module intentionally does not translate operator content or call a model.
It produces small, non-secret metadata that downstream routing, retrieval,
provider prompts, evals, and future localization adapters can use without
hardcoding individual demo prompts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


SUPPORTED_LANGUAGE_CODES = frozenset({"en", "fr", "es", "pt", "it", "fa", "ar", "cjk", "ru", "unknown"})
SUPPORTED_SCRIPTS = frozenset({"latin", "arabic", "cjk", "cyrillic", "mixed", "unknown"})
SUPPORTED_TONES = frozenset({"operator", "technical", "executive", "casual", "unknown"})

_LANGUAGE_MARKERS: dict[str, tuple[str, ...]] = {
    "en": (
        "the", "what", "how", "where", "which", "show", "drone", "drones", "configured", "status",
        "logs", "warning", "error", "setup", "connect", "mode", "runtime", "ready",
    ),
    "fr": (
        "combien", "quel", "quelle", "quels", "quelles", "est", "sont", "avons", "configuré",
        "configure", "configures", "drones", "journal", "journaux", "erreur", "erreurs", "avertissement",
        "essaim", "spectacle", "pret", "prêt", "connexion",
    ),
    "es": (
        "cuantos", "cuántos", "cual", "cuál", "que", "qué", "tenemos", "configurado", "configurados",
        "drones", "registro", "registros", "error", "errores", "enjambre", "modo", "simulacion", "simulación",
    ),
    "pt": (
        "quantos", "qual", "quais", "temos", "configurado", "configurados", "drones", "registro",
        "registros", "erro", "erros", "enxame", "modo", "simulacao", "simulação",
    ),
    "it": (
        "quanti", "quale", "quali", "abbiamo", "configurato", "configurati", "droni", "registro",
        "registri", "errore", "errori", "sciame", "modalita", "modalità",
    ),
}

_TECHNICAL_TERMS = (
    "api", "mcp", "px4", "mavlink", "qgc", "rtk", "sys_id", "sys id", "udp", "endpoint",
    "openapi", "fastapi", "json", "log", "logs", "trace", "401", "500", "gpt", "model",
)
_OPERATOR_TERMS = (
    "status", "ready", "connected", "check", "show", "fleet", "drone", "drones", "mission",
    "flight", "backend", "warning", "error", "readiness", "health",
)
_EXECUTIVE_TERMS = (
    "pm", "report", "client", "demo", "handoff", "audience", "manager", "summary", "brief",
)
_CASUAL_TERMS = (
    "please", "pls", "thanks", "ok", "hey", "hi", "can you", "could you",
)


@dataclass(frozen=True)
class LanguageProfile:
    """Small, safe profile for query routing and response adaptation."""

    language: str
    script: str
    tone: str
    confidence: float
    localization_strategy: str
    notes: tuple[str, ...] = ()

    def public_metadata(self) -> dict[str, object]:
        return {
            "language": self.language,
            "script": self.script,
            "tone": self.tone,
            "confidence": round(float(self.confidence), 3),
            "localization_strategy": self.localization_strategy,
            "notes": list(self.notes),
        }


def detect_language_profile(message: str) -> LanguageProfile:
    """Infer language/script/tone without storing or returning raw text."""

    text = str(message or "").strip()
    if not text:
        return LanguageProfile(
            language="unknown",
            script="unknown",
            tone="unknown",
            confidence=0.0,
            localization_strategy="clarify-before-localization",
            notes=("empty message",),
        )

    script, script_confidence, script_notes = _detect_script(text)
    language, language_confidence, language_notes = _detect_language(text, script=script)
    tone = _detect_tone(text)
    strategy = _localization_strategy(language=language, script=script, confidence=language_confidence)
    return LanguageProfile(
        language=language if language in SUPPORTED_LANGUAGE_CODES else "unknown",
        script=script if script in SUPPORTED_SCRIPTS else "unknown",
        tone=tone if tone in SUPPORTED_TONES else "unknown",
        confidence=min(1.0, max(script_confidence, language_confidence)),
        localization_strategy=strategy,
        notes=tuple(dict.fromkeys((*script_notes, *language_notes))),
    )


def provider_language_guidance(profile: LanguageProfile) -> str:
    """Return safe provider-facing instructions derived from the profile."""

    metadata = profile.public_metadata()
    return "\n".join(
        [
            "Simurgh language/tone profile:",
            f"- Detected language: {metadata['language']} (confidence {metadata['confidence']})",
            f"- Script: {metadata['script']}",
            f"- Tone: {metadata['tone']}",
            f"- Localization strategy: {metadata['localization_strategy']}",
            "- If the detected language is not English and confidence is reasonable, answer in that same language while keeping MDS technical names, API paths, commands, and doc links exact.",
            "- If language confidence is weak, answer in concise English and ask one short clarification only if needed.",
            "- Match the operator's level: technical for technical prompts, practical/operator-first for field prompts, executive summary for PM/report prompts.",
        ]
    )


def _detect_script(text: str) -> tuple[str, float, tuple[str, ...]]:
    counts = {
        "latin": len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]", text)),
        "arabic": len(re.findall(r"[\u0600-\u06FF]", text)),
        "cjk": len(re.findall(r"[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uAC00-\uD7AF]", text)),
        "cyrillic": len(re.findall(r"[\u0400-\u04FF]", text)),
    }
    total = sum(counts.values())
    if total == 0:
        return "unknown", 0.0, ("no alphabetic script signal",)
    nonzero = [script for script, count in counts.items() if count]
    if len(nonzero) > 1:
        dominant, dominant_count = max(counts.items(), key=lambda item: item[1])
        if dominant_count / total < 0.75:
            return "mixed", dominant_count / total, ("mixed script input",)
        return dominant, dominant_count / total, ("secondary script present",)
    script = nonzero[0]
    return script, counts[script] / total, ()


def _detect_language(text: str, *, script: str) -> tuple[str, float, tuple[str, ...]]:
    normalized = _normalize_text(text)
    tokens = set(re.findall(r"[a-zà-öø-ÿ0-9_]+", normalized))
    if script == "arabic":
        if re.search(r"[\u067E\u0686\u0698\u06AF\u06A9\u06CC]", text):
            return "fa", 0.82, ("persian-specific script signal",)
        return "ar", 0.68, ("arabic-script signal",)
    if script == "cjk":
        return "cjk", 0.65, ("cjk script signal",)
    if script == "cyrillic":
        return "ru", 0.62, ("cyrillic script signal",)
    if script not in {"latin", "mixed"}:
        return "unknown", 0.0, ("no supported language signal",)

    scores: dict[str, float] = {language: 0.0 for language in _LANGUAGE_MARKERS}
    for language, markers in _LANGUAGE_MARKERS.items():
        for marker in markers:
            marker_norm = _normalize_text(marker)
            if " " in marker_norm:
                if marker_norm in normalized:
                    scores[language] += 1.8
            elif marker_norm in tokens:
                scores[language] += 1.0
    best_language, best_score = max(scores.items(), key=lambda item: (item[1], item[0]))
    if best_score <= 0:
        return "unknown", 0.15, ("latin script without clear language markers",)
    confidence = min(0.92, 0.25 + best_score / max(5.0, len(tokens) or 1))
    return best_language, confidence, ()


def _detect_tone(text: str) -> str:
    normalized = _normalize_text(text)
    scores = {
        "technical": _term_score(normalized, _TECHNICAL_TERMS),
        "operator": _term_score(normalized, _OPERATOR_TERMS),
        "executive": _term_score(normalized, _EXECUTIVE_TERMS),
        "casual": _term_score(normalized, _CASUAL_TERMS),
    }
    best_tone, best_score = max(scores.items(), key=lambda item: (item[1], item[0]))
    if best_score <= 0:
        return "unknown"
    return best_tone


def _localization_strategy(*, language: str, script: str, confidence: float) -> str:
    if language == "en" and confidence >= 0.35:
        return "english-direct"
    if language != "unknown" and confidence >= 0.45:
        return "same-language-provider-response"
    if script in {"arabic", "cjk", "cyrillic", "mixed"}:
        return "provider-rewrite-before-routing-required"
    return "english-with-clarification-if-needed"


def _term_score(normalized: str, terms: tuple[str, ...]) -> float:
    score = 0.0
    for term in terms:
        marker = _normalize_text(term)
        if not marker:
            continue
        if re.fullmatch(r"[a-z0-9_]+", marker):
            if re.search(rf"\b{re.escape(marker)}\b", normalized):
                score += 1.0
        elif marker in normalized:
            score += 1.0
    return score


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())
