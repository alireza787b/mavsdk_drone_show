import pytest

from px4_param_store import import_qgc_parameter_file
from src.px4_param_models import Px4ParamImportRequest
from src.px4_param_models import Px4ParamDiffRequest, Px4ParamSnapshotResponse
from px4_param_store import build_param_diff_response, save_snapshot


@pytest.mark.parametrize("value,type_id", [
    ("1.9", 6), ("NaN", 6), ("Infinity", 6), ("2147483648", 6),
    ("12invalid", 6), ("NaN", 9), ("Infinity", 9), ("1e9999", 9),
])
def test_import_never_truncates_or_accepts_nonfinite_values(value, type_id):
    parsed = import_qgc_parameter_file(Px4ParamImportRequest(content=f"1\t1\tTEST_PARAM\t{value}\t{type_id}"))
    assert parsed.total_entries == 0
    assert parsed.skipped_count == 1
    assert parsed.warnings[0].line == 1


@pytest.mark.parametrize("value,expected", [("2", 2), ("2.0", 2), ("2e1", 20), ("-2147483648", -2147483648)])
def test_import_accepts_exact_whole_integer_representations(value, expected):
    parsed = import_qgc_parameter_file(Px4ParamImportRequest(content=f"1\t1\tTEST_PARAM\t{value}\t6"))
    assert parsed.skipped_count == 0
    assert parsed.entries[0].value == expected


@pytest.mark.parametrize("desired,current,changed", [(0.1, 0.10000000149011612, False), (1e-7, 0.0, True)])
def test_import_diff_uses_same_wire_value_identity_as_native(desired, current, changed):
    snapshot_id = f"precision-diff-{desired}"
    save_snapshot(Px4ParamSnapshotResponse.model_validate({
        "snapshot": {"snapshot_id": snapshot_id, "hw_id": "1", "component_id": 1,
                     "px4_docs_version": "main", "total_params": 1, "created_at": 1, "stale_after_ms": 60000},
        "rows": [{"component_id": 1, "name": "TEST_PARAM", "value_type": "float", "value": current}],
    }))
    diff = build_param_diff_response(Px4ParamDiffRequest(snapshot_id=snapshot_id,
        desired_entries=[{"component_id": 1, "name": "TEST_PARAM", "value_type": "float", "value": desired}],
        include_unchanged=True))
    assert diff.differences[0].changed is changed
