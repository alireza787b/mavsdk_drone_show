from src import flight_timeout_utils as timeouts


def test_calculate_land_disarm_timeout_defaults_to_minimum_when_altitude_unknown():
    assert timeouts.calculate_land_disarm_timeout(None) == timeouts.Params.LAND_ACTION_MIN_DISARM_WAIT_SEC


def test_calculate_land_disarm_timeout_scales_with_altitude_and_respects_cap():
    timeout = timeouts.calculate_land_disarm_timeout(1200.0)

    assert timeout > timeouts.Params.LAND_ACTION_MIN_DISARM_WAIT_SEC
    assert timeout <= timeouts.Params.LAND_ACTION_MAX_DISARM_WAIT_SEC


def test_calculate_controlled_landing_timeout_scales_with_precision_descent_rate():
    timeout = timeouts.calculate_controlled_landing_timeout(2.0)

    assert timeout >= timeouts.Params.CONTROLLED_LANDING_TIMEOUT
    assert timeout <= timeouts.Params.CONTROLLED_LANDING_MAX_TIMEOUT_SEC


def test_calculate_swarm_rtl_completion_timeout_wraps_landing_timeout_with_rtl_buffer():
    rtl_timeout = timeouts.calculate_swarm_rtl_completion_timeout(250.0)
    land_timeout = timeouts.calculate_land_disarm_timeout(250.0)

    assert rtl_timeout >= land_timeout + timeouts.Params.SWARM_TRAJECTORY_RTL_COMPLETION_BUFFER_SEC
    assert rtl_timeout <= timeouts.Params.SWARM_TRAJECTORY_RTL_COMPLETION_MAX_TIMEOUT
