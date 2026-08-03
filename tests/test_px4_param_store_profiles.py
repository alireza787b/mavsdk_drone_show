from pathlib import Path
from types import SimpleNamespace

import pytest

from px4_param_store import get_repo_profile, list_repo_profiles


_MIGRATED_FIELD_BASELINE = [
    ("COM_RCL_EXCEPT", "int", 7),
    ("GF_ACTION", "int", 3),
    ("GF_MAX_HOR_DIST", "float", 1500.0),
    ("GF_MAX_VER_DIST", "float", 200.0),
    ("UAVCAN_PUB_RTCM", "int", 1),
    ("MAV_PROTO_VER", "int", 2),
    ("COM_OBL_RC_ACT", "int", 3),
    ("COM_OF_LOSS_T", "float", 20.0),
    ("COM_FLT_TIME_MAX", "int", 900),
    ("COM_FLTT_LOW_ACT", "int", 3),
    ("IMU_GYRO_NF0_FRQ", "float", 90.0),
    ("IMU_GYRO_NF0_BW", "float", 15.0),
    ("EKF2_GPS_P_NOISE", "float", 0.5),
    ("EKF2_GPS_V_NOISE", "float", 0.3),
    ("EKF2_GPS_P_GATE", "float", 5.0),
    ("EKF2_GPS_V_GATE", "float", 5.0),
    ("EKF2_DRAG_CTRL", "int", 0),
    ("EKF2_BCOEF_X", "float", 100.0),
    ("EKF2_BCOEF_Y", "float", 100.0),
    ("EKF2_BARO_CTRL", "int", 1),
    ("EKF2_MULTI_IMU", "int", 3),
    ("SENS_IMU_MODE", "int", 0),
]


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


def test_repo_loader_exposes_exact_migrated_multidrone_field_baseline():
    repo_root = Path(__file__).resolve().parents[1]
    params = SimpleNamespace(
        PX4_PARAMETER_PROFILE_DIR=str(repo_root / "resources" / "px4_param_profiles")
    )

    profiles = list_repo_profiles(params)
    profile = get_repo_profile(params, "mds_multidrone_field_baseline")

    assert profile is not None
    assert any(
        summary.profile_id == "mds_multidrone_field_baseline"
        and summary.entry_count == 22
        for summary in profiles.profiles
    )
    assert [
        (entry.name, entry.value_type.value, entry.value)
        for entry in profile.entries
    ] == _MIGRATED_FIELD_BASELINE
    assert all(entry.component_id == 1 for entry in profile.entries)
