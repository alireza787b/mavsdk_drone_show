from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.enums import Mission
from src.launch_preparation_protocol import (
    LaunchPreparationBinding,
    LaunchPreparationConsumeStatus,
    LaunchPreparationRequest,
    LaunchPreparationStore,
    calculate_launch_preparation_token_ttl_sec,
)


def _launch_command(**overrides):
    payload = {
        "mission_type": Mission.TAKE_OFF.value,
        "trigger_time": 0,
        "command_id": "command-one",
        "target_hw_id": "1",
        "command_report_capability": "cap-" + ("x" * 39),
        "takeoff_altitude": 10.0,
    }
    payload.update(overrides)
    return payload


class _Clock:
    def __init__(self, value: float = 100.0):
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_token_is_one_use_and_bound_to_exact_command_target_and_payload():
    store = LaunchPreparationStore(ttl_sec=60.0)
    command = _launch_command()
    token, ttl_ms = store.issue(LaunchPreparationBinding.from_command(command))

    assert ttl_ms == 60_000
    assert store.consume(token, command).status is LaunchPreparationConsumeStatus.CONSUMED
    assert store.consume(token, command).status is LaunchPreparationConsumeStatus.REPLAYED


@pytest.mark.parametrize(
    "changed",
    [
        {"command_id": "command-two"},
        {"target_hw_id": "2"},
        {"mission_type": Mission.HOVER_TEST.value},
        {"takeoff_altitude": 11.0},
        {"command_report_capability": "cap-" + ("y" * 39)},
    ],
)
def test_mismatch_consumes_authority_atomically(changed):
    store = LaunchPreparationStore(ttl_sec=60.0)
    command = _launch_command()
    token, _ = store.issue(LaunchPreparationBinding.from_command(command))

    mismatch = store.consume(token, _launch_command(**changed))
    replay = store.consume(token, command)

    assert mismatch.status is LaunchPreparationConsumeStatus.MISMATCH
    assert replay.status is LaunchPreparationConsumeStatus.REPLAYED


def test_expiry_uses_node_monotonic_clock_and_consumes_expired_token():
    clock = _Clock()
    store = LaunchPreparationStore(ttl_sec=5.0, monotonic=clock)
    command = _launch_command()
    token, _ = store.issue(LaunchPreparationBinding.from_command(command))
    clock.value += 5.0

    expired = store.consume(token, command)
    repeated = store.consume(token, command)

    assert expired.status is LaunchPreparationConsumeStatus.EXPIRED
    assert repeated.status is LaunchPreparationConsumeStatus.MISSING


def test_new_process_store_cannot_consume_old_process_token():
    command = _launch_command()
    old_store = LaunchPreparationStore(ttl_sec=60.0)
    token, _ = old_store.issue(LaunchPreparationBinding.from_command(command))

    restarted_store = LaunchPreparationStore(ttl_sec=60.0)

    assert (
        restarted_store.consume(token, command).status
        is LaunchPreparationConsumeStatus.MISSING
    )


def test_strict_sync_zero_trigger_allows_bounded_post_barrier_trigger():
    prepared = _launch_command(
        mission_type=Mission.HOVER_TEST.value,
        takeoff_altitude=None,
    )
    store = LaunchPreparationStore(
        ttl_sec=60.0,
        wall_clock=lambda: 100.0,
    )
    token, _ = store.issue(LaunchPreparationBinding.from_command(prepared))

    committed = dict(prepared, trigger_time=130)

    assert store.consume(token, committed).consumed is True


def test_strict_sync_zero_trigger_rejects_trigger_outside_preparation_lease():
    prepared = _launch_command(
        mission_type=Mission.HOVER_TEST.value,
        takeoff_altitude=None,
    )
    store = LaunchPreparationStore(
        ttl_sec=60.0,
        wall_clock=lambda: 100.0,
    )
    token, _ = store.issue(LaunchPreparationBinding.from_command(prepared))

    result = store.consume(token, dict(prepared, trigger_time=161))

    assert result.status is LaunchPreparationConsumeStatus.MISMATCH
    assert "outside this preparation lease" in result.detail


def test_non_strict_trigger_change_is_rejected():
    prepared = _launch_command()
    store = LaunchPreparationStore(ttl_sec=60.0)
    token, _ = store.issue(LaunchPreparationBinding.from_command(prepared))

    result = store.consume(token, dict(prepared, trigger_time=2_000_000_000))

    assert result.status is LaunchPreparationConsumeStatus.MISMATCH


def test_post_barrier_trigger_must_retain_node_warmup_and_guard_lead():
    prepared = _launch_command(
        mission_type=Mission.HOVER_TEST.value,
        takeoff_altitude=None,
    )
    late_store = LaunchPreparationStore(
        ttl_sec=60.0,
        wall_clock=lambda: 100.0,
        minimum_post_barrier_lead_sec=5.0,
    )
    late_token, _ = late_store.issue(LaunchPreparationBinding.from_command(prepared))

    late = late_store.consume(late_token, dict(prepared, trigger_time=105))

    assert late.status is LaunchPreparationConsumeStatus.MISMATCH
    assert "no longer safely in the future" in late.detail

    safe_store = LaunchPreparationStore(
        ttl_sec=60.0,
        wall_clock=lambda: 100.0,
        minimum_post_barrier_lead_sec=5.0,
    )
    safe_token, _ = safe_store.issue(LaunchPreparationBinding.from_command(prepared))
    assert safe_store.consume(
        safe_token,
        dict(prepared, trigger_time=106),
    ).consumed


def test_prepare_contract_rejects_compatibility_spellings_and_partial_identity():
    with pytest.raises(ValidationError, match="canonical command fields"):
        LaunchPreparationRequest.model_validate(
            {
                "command": {
                    **_launch_command(),
                    "triggerTime": 0,
                }
            }
        )

    with pytest.raises(ValidationError, match="command_id"):
        LaunchPreparationRequest.model_validate(
            {"command": _launch_command(command_id=None)}
        )


def test_token_ttl_reuses_typed_fleet_budgets_and_rejects_garbage_coercion():
    typed = SimpleNamespace(
        GCS_FLEET_PREPARE_DEADLINE_SEC=40.0,
        GCS_FLEET_DISPATCH_DEADLINE_SEC=20.0,
        GCS_COMMAND_HTTP_TIMEOUT_SEC=6.0,
    )
    garbage = SimpleNamespace(
        GCS_FLEET_PREPARE_DEADLINE_SEC="4000",
        GCS_FLEET_DISPATCH_DEADLINE_SEC=object(),
        GCS_COMMAND_HTTP_TIMEOUT_SEC=float("nan"),
    )

    assert calculate_launch_preparation_token_ttl_sec(params=typed) == 116.0
    assert calculate_launch_preparation_token_ttl_sec(params=garbage) == 90.0


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"ttl_sec": "60"}, "ttl_sec"),
        ({"ttl_sec": float("nan")}, "ttl_sec"),
        ({"ttl_sec": 0.5}, "at least one second"),
        ({"ttl_sec": 60.0, "max_records": True}, "max_records"),
        ({"ttl_sec": 60.0, "max_records": 0}, "max_records"),
        (
            {"ttl_sec": 60.0, "minimum_post_barrier_lead_sec": "5"},
            "minimum_post_barrier_lead_sec",
        ),
        ({"ttl_sec": 60.0, "monotonic": None}, "clocks"),
    ],
)
def test_token_store_refuses_implicitly_coerced_or_invalid_configuration(
    kwargs,
    message,
):
    with pytest.raises(ValueError, match=message):
        LaunchPreparationStore(**kwargs)
