from tools.validate_px4_params_runtime import build_qgc_file, choose_param_value


def test_choose_param_value_advances_float_within_bounds():
    row = {
        "name": "MPC_XY_VEL_MAX",
        "value_type": "float",
        "value": 12.0,
        "min_value": 0.0,
        "max_value": 20.0,
    }

    assert choose_param_value(row, delta=1.0) == 13.0


def test_choose_param_value_flips_direction_when_upper_bound_would_be_exceeded():
    row = {
        "name": "MPC_XY_VEL_MAX",
        "value_type": "float",
        "value": 19.8,
        "min_value": 0.0,
        "max_value": 20.0,
    }

    assert choose_param_value(row, delta=1.0) == 18.8


def test_build_qgc_file_uses_qgroundcontrol_header_and_types():
    payload = build_qgc_file(
        hw_id="2",
        component_id=1,
        name="MPC_XY_VEL_MAX",
        value=12.5,
        value_type="float",
    )

    assert payload.startswith("# QGroundControl Parameter File")
    assert "2\t1\tMPC_XY_VEL_MAX\t12.5\t9" in payload
