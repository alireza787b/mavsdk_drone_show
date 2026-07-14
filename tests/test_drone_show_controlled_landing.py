import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_controlled_landing_uses_dedicated_timeout_constant():
    source = (REPO_ROOT / "drone_show.py").read_text()
    module = ast.parse(source)

    controlled_landing = next(
        node for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "controlled_landing"
    )

    attribute_names = {
        node.attr
        for node in ast.walk(controlled_landing)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "Params"
    }

    assert "CONTROLLED_LANDING_TIMEOUT" in attribute_names
