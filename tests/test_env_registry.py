import re
from pathlib import Path

import pytest

from src.settings.env_registry import EnvRegistryError, coerce_value, load_env_registry
from tools.audit_mds_env_registry import audit_mds_env_references
from tools.generate_mds_env_reference import DEFAULT_OUTPUT_PATH, build_env_reference_markdown


REPO_ROOT = Path(__file__).resolve().parents[1]


def _extract_mds_keys(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"\bMDS_[A-Z0-9_]+\b", text))


def test_env_registry_loads_without_raw_secret_entries():
    registry = load_env_registry()

    assert registry.version >= 1
    assert registry.content_hash
    assert registry.require("MDS_AUTH_ENABLED").domain == "auth"
    assert not [entry.name for entry in registry.entries.values() if entry.secret]


def test_env_registry_covers_active_templates():
    registry = load_env_registry()
    expected_keys = set()
    expected_keys.update(_extract_mds_keys(REPO_ROOT / "deployment" / "defaults.env"))
    expected_keys.update(_extract_mds_keys(REPO_ROOT / "tools" / "local.env.template"))

    missing = sorted(key for key in expected_keys if registry.get(key) is None)

    assert missing == []


def test_env_registry_docs_links_exist():
    registry = load_env_registry()

    missing_docs = sorted(
        {entry.docs for entry in registry.entries.values() if not (REPO_ROOT / entry.docs).exists()}
    )

    assert missing_docs == []


def test_active_mds_env_references_are_registered_or_classified():
    result = audit_mds_env_references()

    assert result.unclassified == {}


def test_generated_env_registry_reference_is_current():
    expected = build_env_reference_markdown(load_env_registry())

    assert DEFAULT_OUTPUT_PATH.read_text(encoding="utf-8") == expected


def test_env_registry_classifies_unknown_keys():
    registry = load_env_registry()

    result = registry.classify_keys(
        {
            "MDS_AUTH_ENABLED": "true",
            "MDS_GCS_API_TOKEN": "raw-token",
            "GCS_PORT": "5030",
        }
    )

    assert result["known"] == ["MDS_AUTH_ENABLED"]
    assert "GCS_PORT" in result["deprecated"]
    assert result["unknown"] == ["MDS_GCS_API_TOKEN"]


def test_env_registry_coerces_and_validates_values():
    registry = load_env_registry()

    assert coerce_value(registry.require("MDS_AUTH_ENABLED"), "yes") == "true"
    assert coerce_value(registry.require("MDS_AUTH_SESSION_TTL_HOURS"), "24") == "24"
    assert coerce_value(registry.require("MDS_MODE"), "real") == "real"

    with pytest.raises(EnvRegistryError):
        coerce_value(registry.require("MDS_AUTH_ENABLED"), "maybe")

    with pytest.raises(EnvRegistryError):
        coerce_value(registry.require("MDS_MODE"), "lab")

    with pytest.raises(KeyError):
        registry.require("MDS_GCS_API_TOKEN")
