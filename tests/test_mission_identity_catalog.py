import json
from pathlib import Path

from src.enums import Mission


def test_generated_dashboard_mission_identities_match_python_authority():
    repo_root = Path(__file__).resolve().parents[1]
    generated_path = (
        repo_root
        / "app/dashboard/drone-dashboard/src/generated/missionIdentities.generated.json"
    )
    generated = json.loads(generated_path.read_text(encoding="utf-8"))

    assert list(Mission.__members__) == [mission.name for mission in Mission]
    assert generated == [
        {"key": mission.name, "value": mission.value}
        for mission in Mission
    ]
