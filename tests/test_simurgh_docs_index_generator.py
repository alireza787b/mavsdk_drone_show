from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = REPO_ROOT / "tools" / "generate_simurgh_docs_index.py"
ARTIFACT_PATH = REPO_ROOT / "docs" / "agent-context" / "generated" / "simurgh-docs-index.json"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_simurgh_docs_index", GENERATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generated_docs_index_is_current_public_and_bounded():
    generator = _load_generator()
    artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    assert artifact["version"] == 1
    assert artifact["schema"] == "mds.simurgh.docs_index.v1"
    assert artifact["resource_count"] == len(artifact["resources"])
    assert artifact["chunk_count"] == len(artifact["chunks"])
    assert artifact["chunk_count"] > 100
    assert generator.main(["--check"]) == 0

    resource_ids = {resource["id"] for resource in artifact["resources"]}
    assert {"mds.drone_show", "mds.quickscout", "mds.environment_registry", "simurgh.mcp_client_recipes"}.issubset(resource_ids)
    mcp_clients = next(resource for resource in artifact["resources"] if resource["id"] == "simurgh.mcp_client_recipes")
    assert mcp_clients["route_hint"] == "/simurgh"
    assert "simurgh.foundation_evals" not in resource_ids
    assert "simurgh.docs_index" not in resource_ids
    assert "mds.node_bootstrap_design" not in resource_ids

    for collection in (artifact["resources"], artifact["chunks"]):
        for item in collection:
            assert item["canonical_url"].startswith("/api/v1/simurgh/context/")
            assert not item["path"].startswith("docs/agent-context/generated/")
            assert not item["path"].startswith("docs/plans/")
            assert "evals" not in set(item.get("tags", []))
            serialized = json.dumps(item)
            assert "sk-proj-" not in serialized
            assert "sk-or-v1-" not in serialized
            assert "github_pat_" not in serialized
            assert "ghp_" not in serialized


def test_docs_index_requires_explicit_searchable_public_resources(monkeypatch, tmp_path):
    generator = _load_generator()
    monkeypatch.setattr(generator, "REPO_ROOT", tmp_path)
    (tmp_path / "docs" / "quickscout.md").parent.mkdir(parents=True)
    (tmp_path / "docs" / "quickscout.md").write_text("# QuickScout\n\nSearch and rescue planning.", encoding="utf-8")
    (tmp_path / "docs" / "reference").mkdir(parents=True)
    (tmp_path / "docs" / "reference" / "auto.generated.md").write_text(
        "# Generated\n\nNot explicitly approved.", encoding="utf-8"
    )
    (tmp_path / "docs" / "reference" / "safe.generated.md").write_text(
        "# Generated Safe\n\nExplicitly approved generated reference.", encoding="utf-8"
    )
    (tmp_path / "docs" / "eval.yaml").write_text("case: should-not-index\n", encoding="utf-8")
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    (tmp_path / "docs" / "plans" / "design.md").write_text("# Design\n\nPublic but not searchable.", encoding="utf-8")
    context_index = tmp_path / "context-index.yaml"
    context_index.write_text(
        """version: 1
resources:
  - id: mds.quickscout
    title: QuickScout
    path: docs/quickscout.md
    mime_type: text/markdown
    audience: operator
    sensitivity: public
    summary: QuickScout docs.
    tags: [mission]
    searchable: true
  - id: simurgh.foundation_evals
    title: Evals
    path: docs/eval.yaml
    mime_type: application/yaml
    audience: developer
    sensitivity: public
    summary: Evals.
    tags: [evals]
  - id: mds.generated_skip
    title: Generated Skip
    path: docs/reference/auto.generated.md
    mime_type: text/markdown
    audience: operator
    sensitivity: public
    summary: Generated file without explicit search approval.
    tags: [environment]
    searchable: true
  - id: mds.safe_generated
    title: Safe Generated
    path: docs/reference/safe.generated.md
    mime_type: text/markdown
    audience: operator
    sensitivity: public
    summary: Explicitly approved generated reference.
    tags: [environment]
    docs_search: include
    generated_safe_for_search: true
  - id: mds.node_bootstrap_design
    title: Design
    path: docs/plans/design.md
    mime_type: text/markdown
    audience: developer
    sensitivity: public
    summary: Design.
    tags: [setup]
    searchable: true
""",
        encoding="utf-8",
    )

    artifact = generator.build_index(context_index)

    assert [resource["id"] for resource in artifact["resources"]] == ["mds.quickscout", "mds.safe_generated"]
    assert {chunk["resource_id"] for chunk in artifact["chunks"]} == {"mds.quickscout", "mds.safe_generated"}


@pytest.mark.parametrize(
    "secret_text",
    (
        "".join(("sk-", "proj-", "abcdefghijklmnopqrstuvwxyz1234567890")),
        "".join(("sk-", "or-v1-", "abcdefghijklmnopqrstuvwxyz1234567890")),
        "".join(("ghp_", "abcdefghijklmnopqrstuvwxyz1234567890")),
        "".join(("github_pat_", "abcdefghijklmnopqrstuvwxyz1234567890")),
        "".join(("-----BEGIN ", "OPENSSH PRIVATE KEY-----")),
        "".join(("Authorization: Bearer ", "abcdefghijklmnopqrstuvwxyz1234567890")),
        "".join(("api_key=", "abcdefghijklmnopqrstuvwxyz1234567890")),
        "".join(("netbird_setup_key=", "abcdefghijklmnopqrstuvwxyz1234567890")),
    ),
)
def test_docs_index_refuses_raw_secret_patterns(monkeypatch, tmp_path, secret_text):
    generator = _load_generator()
    monkeypatch.setattr(generator, "REPO_ROOT", tmp_path)
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "docs" / "secret.md").write_text(
        f"# Bad\n\n{secret_text}", encoding="utf-8"
    )
    context_index = tmp_path / "context-index.yaml"
    context_index.write_text(
        """version: 1
resources:
  - id: mds.bad
    title: Bad
    path: docs/secret.md
    mime_type: text/markdown
    audience: operator
    sensitivity: public
    summary: Bad.
    tags: [bad]
    searchable: true
""",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="raw secret pattern"):
        generator.build_index(context_index)
