import pytest

from src.px4_preflight_telemetry import current_preflight_report, relay_preflight_report


def state():
    return dict(telemetry_available=True, is_armed=False, landed_state=1, flight_mode=50593792,
                px4_arming_report=dict(source='px4_events', mode='Hold', custom_mode=50593792,
                                       can_arm=False, remaining_valid_ms=4000,
                                       mode_problems=[dict(message='No valid position estimate', severity='ERROR')]))


def test_report_preserves_the_native_negative_verdict_and_reason():
    report = current_preflight_report(state())
    assert report.can_arm is False
    assert report.mode_problems[0].message == 'No valid position estimate'


@pytest.mark.parametrize('overrides', [dict(is_armed=True), dict(is_armed=None),
    dict(landed_state=2), dict(landed_state=True), dict(telemetry_available=False),
    dict(flight_mode=131072), dict(px4_arming_report=None)])
def test_no_verdict_without_matching_ground_state(overrides):
    assert current_preflight_report({**state(), **overrides}) is None


@pytest.mark.parametrize('overrides', [dict(source='px4'), dict(can_arm='true'),
    dict(remaining_valid_ms=0), dict(remaining_valid_ms=5001), dict(mode_problems=None)])
def test_older_or_invalid_reports_do_not_color_the_card(overrides):
    packet = state()
    packet['px4_arming_report'].update(overrides)
    assert current_preflight_report(packet) is None


def test_relay_uses_source_lease_not_fleet_cache_age():
    assert relay_preflight_report(state(), node_sent_at_ms=1000, received_at_ms=3000).expires_at_gcs_ms == 5000
    assert relay_preflight_report(state(), node_sent_at_ms=1000, received_at_ms=4999).expires_at_gcs_ms == 5000
    assert relay_preflight_report(state(), node_sent_at_ms=1000, received_at_ms=5000) is None
    assert relay_preflight_report(state(), node_sent_at_ms=6000, received_at_ms=5000) is None
    assert relay_preflight_report(state(), node_sent_at_ms=None, received_at_ms=5000) is None
