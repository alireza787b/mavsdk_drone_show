from types import SimpleNamespace

import pytest

from px4_param_store import get_repo_profile, list_repo_profiles


def test_list_repo_profiles_reads_repo_backed_profiles(tmp_path):
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    (profile_dir / "fleet_guard.json").write_text(
        """
        {
          "profile_id": "fleet_guard",
          "name": "Fleet Guard",
          "description": "Starter profile",
          "recommended_scope": "fleet",
          "tags": ["starter"],
          "entries": [
            {"component_id": 1, "name": "GF_ACTION", "value_type": "int", "value": 3}
          ]
        }
        """,
        encoding="utf-8",
    )
    params = SimpleNamespace(PX4_PARAMETER_PROFILE_DIR=str(profile_dir))

    response = list_repo_profiles(params)

    assert response.total_profiles == 1
    assert response.profiles[0].profile_id == "fleet_guard"
    assert response.profiles[0].entry_count == 1
    assert response.profiles[0].recommended_scope == "fleet"


def test_get_repo_profile_returns_typed_profile_entries(tmp_path):
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    (profile_dir / "sitl_demo.json").write_text(
        """
        {
          "profile_id": "sitl_demo",
          "name": "SITL Demo",
          "description": "Validation profile",
          "recommended_scope": "selected",
          "tags": ["sitl"],
          "entries": [
            {"component_id": 1, "name": "COM_DL_LOSS_T", "value_type": "float", "value": 0}
          ]
        }
        """,
        encoding="utf-8",
    )
    params = SimpleNamespace(PX4_PARAMETER_PROFILE_DIR=str(profile_dir))

    profile = get_repo_profile(params, "sitl_demo")

    assert profile is not None
    assert profile.profile_id == "sitl_demo"
    assert profile.entries[0].name == "COM_DL_LOSS_T"
    assert profile.entries[0].value_type == "float"
    assert profile.entries[0].value == 0.0


def test_get_repo_profile_rejects_profile_id_filename_mismatch(tmp_path):
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    (profile_dir / "fleet_guard.json").write_text(
        """
        {
          "profile_id": "other_profile",
          "name": "Fleet Guard",
          "entries": [
            {"component_id": 1, "name": "GF_ACTION", "value_type": "int", "value": 3}
          ]
        }
        """,
        encoding="utf-8",
    )
    params = SimpleNamespace(PX4_PARAMETER_PROFILE_DIR=str(profile_dir))

    with pytest.raises(ValueError, match="must match filename"):
        get_repo_profile(params, "fleet_guard")
