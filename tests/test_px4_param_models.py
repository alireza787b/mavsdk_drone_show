"""Strict shared PX4 parameter contracts; no vehicle/runtime discovery."""

import pytest
from pydantic import ValidationError

from src.px4_param_models import (
    Px4ParamDiffRequest,
    Px4ParamFleetSnapshotRequest,
    Px4ParamPatchApplyRequest,
    Px4ParamPatchEntry,
    Px4ParamPatchJobRequest,
    Px4ParamSetRequest,
)


@pytest.mark.parametrize("model", [Px4ParamPatchEntry, Px4ParamSetRequest])
@pytest.mark.parametrize("value_type,value", [
    ("int", True), ("float", False), ("int", "12"), ("float", "1.2oops"),
    ("float", "1.2"), ("int", 1.5), ("int", 2**31), ("int", -(2**31)-1),
    ("float", float("nan")), ("float", float("inf")), ("float", -float("inf")),
    ("float", 3.5e38), ("float", 10**1000), ("float", 5e-47), ("float", -5e-47),
    ("custom", 123), ("custom", "a"*1025),
])
def test_write_models_reject_invalid_numeric_values(model, value_type, value):
    fields = {"name": "MAV_SYS_ID"} if model is Px4ParamPatchEntry else {}
    with pytest.raises(ValidationError):
        model(value_type=value_type, value=value, **fields)


@pytest.mark.parametrize("value", [-(2**31), 2**31-1])
def test_int32_boundary_values_are_accepted(value):
    assert Px4ParamPatchEntry(name="MAV_SYS_ID", value_type="int", value=value).value == value


def test_expected_values_are_validated_as_strict_runtime_type():
    with pytest.raises(ValidationError):
        Px4ParamPatchEntry(name="MAV_SYS_ID", value_type="int", value=2, expected_current_value=True)


@pytest.mark.parametrize("component_id", [True, "1", 1.5, 0, 256])
def test_component_contract_requires_mavlink_integer_range(component_id):
    with pytest.raises(ValidationError):
        Px4ParamPatchEntry(component_id=component_id, name="MAV_SYS_ID", value_type="int", value=2)


@pytest.mark.parametrize("model,extra,entry_field", [
    (Px4ParamPatchApplyRequest, {}, "entries"),
    (Px4ParamPatchJobRequest, {"hw_ids": ["1"]}, "entries"),
    (Px4ParamDiffRequest, {"snapshot_id": "snap"}, "desired_entries"),
])
def test_duplicate_normalized_entries_are_rejected(model, extra, entry_field):
    with pytest.raises(ValidationError):
        model(**extra, **{entry_field: [
            {"name": "mav_sys_id", "value_type": "int", "value": 1},
            {"name": " MAV_SYS_ID ", "value_type": "int", "value": 2},
        ]})


def test_duplicate_aircraft_identities_are_rejected():
    with pytest.raises(ValidationError):
        Px4ParamFleetSnapshotRequest(hw_ids=["1", " 1 "])


@pytest.mark.parametrize("name", ["NAME WITH SPACE", "ÄBC", "ſ", "A"*17, "A/B", ""])
def test_invalid_parameter_names_are_rejected(name):
    with pytest.raises(ValidationError):
        Px4ParamPatchEntry(name=name, value_type="int", value=1)


def test_native_patch_entry_count_is_bounded():
    with pytest.raises(ValidationError):
        Px4ParamPatchApplyRequest(entries=[
            {"name": f"PARAM_{index}", "value_type": "int", "value": 1}
            for index in range(4097)
        ])
