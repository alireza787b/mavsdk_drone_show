import importlib.util
from pathlib import Path


GENERATOR_PATH = Path(__file__).resolve().parents[1] / "tools" / "generate_release_notes.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_release_notes", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_notes_use_current_product_name(monkeypatch, tmp_path, capsys):
    module = _load_generator()
    release_tag = "v5.5.111-simurgh-operator-beta"
    (tmp_path / "VERSION").write_text("5.5\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "## [5.5.111-simurgh-operator-beta] - 2026-07-26\n\n"
        "### Added\n\n- Operator beta.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("RELEASE_TAG_OVERRIDE", release_tag)

    module.generate_release_notes()

    output = capsys.readouterr().out
    assert output.startswith(f"# MDS - Mission-Directed Swarm {release_tag}\n")
    assert "# MAVSDK Drone Show" not in output
    assert f"/tree/{release_tag}/docs" in output
