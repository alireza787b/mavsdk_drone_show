import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PACKAGE_JSON = REPO_ROOT / "app" / "dashboard" / "drone-dashboard" / "package.json"


def test_dashboard_production_build_uses_absolute_public_url():
    package_json = json.loads(DASHBOARD_PACKAGE_JSON.read_text(encoding="utf-8"))

    assert package_json["homepage"] == "/"
