"""Ground-test safety acknowledgement contract tests."""

import pytest
from pydantic import ValidationError

from src.command_contract import (
    DroneCommandRequest,
    GroundTestSafetyAcknowledgement,
    GroundTestSafetyMode,
    SubmitCommandRequest,
)
from src.enums import Mission


REAL_AIRCRAFT_ACK = {
    "mode": "operator_acknowledged",
    "props_removed": True,
    "airframe_secured": True,
    "area_clear": True,
}
SITL_ACK = {"mode": "sitl_not_applicable"}


@pytest.mark.parametrize("request_type", [SubmitCommandRequest, DroneCommandRequest])
def test_test_command_requires_typed_safety_acknowledgement(request_type):
    with pytest.raises(ValidationError, match="ground_test_safety acknowledgement is required"):
        request_type(mission_type=Mission.TEST.value)


@pytest.mark.parametrize("field", ["props_removed", "airframe_secured", "area_clear"])
def test_real_aircraft_acknowledgement_requires_each_condition_true(field):
    payload = dict(REAL_AIRCRAFT_ACK)
    payload[field] = False

    with pytest.raises(ValidationError, match="all be true"):
        GroundTestSafetyAcknowledgement.model_validate(payload)


def test_sitl_acknowledgement_cannot_claim_physical_conditions():
    with pytest.raises(ValidationError, match="must omit"):
        GroundTestSafetyAcknowledgement.model_validate(
            {"mode": "sitl_not_applicable", "props_removed": True}
        )


def test_safety_acknowledgement_is_for_test_only():
    with pytest.raises(ValidationError, match="only valid for Mission.TEST"):
        SubmitCommandRequest(
            mission_type=Mission.TAKE_OFF.value,
            ground_test_safety=REAL_AIRCRAFT_ACK,
        )


def test_runtime_mode_must_match_acknowledgement_mode():
    real_ack = GroundTestSafetyAcknowledgement.model_validate(REAL_AIRCRAFT_ACK)
    sitl_ack = GroundTestSafetyAcknowledgement.model_validate(SITL_ACK)

    real_ack.validate_for_runtime(sim_mode=False)
    sitl_ack.validate_for_runtime(sim_mode=True)

    with pytest.raises(ValueError, match="Real-aircraft"):
        sitl_ack.validate_for_runtime(sim_mode=False)
    with pytest.raises(ValueError, match="SITL"):
        real_ack.validate_for_runtime(sim_mode=True)


def test_drone_payload_preserves_ack_but_strips_gcs_only_fields():
    request = SubmitCommandRequest(
        mission_type=Mission.TEST.value,
        target_drone_ids=["1"],
        operator_label="Arm/Disarm Ground Test",
        idempotency_key="ground-test-1",
        ground_test_safety=REAL_AIRCRAFT_ACK,
    )

    payload = request.to_drone_payload(command_id="cmd-ground-test")

    assert payload["command_id"] == "cmd-ground-test"
    assert payload["ground_test_safety"] == {
        **REAL_AIRCRAFT_ACK,
    }
    assert "target_drone_ids" not in payload
    assert "operator_label" not in payload
    assert "idempotency_key" not in payload


def test_action_payload_loader_uses_only_canonical_nested_contract():
    acknowledgement = GroundTestSafetyAcknowledgement.from_action_payload(
        {"ground_test_safety": SITL_ACK}
    )

    assert acknowledgement.mode == GroundTestSafetyMode.SITL_NOT_APPLICABLE
    with pytest.raises(ValueError, match="ground_test_safety acknowledgement is required"):
        GroundTestSafetyAcknowledgement.from_action_payload({"uiMeta": SITL_ACK})
