"""Fail-closed finite checks for precision-move command contract."""

import math

import pytest
from pydantic import ValidationError

from src.command_contract import PrecisionMoveRequest


def _base_body(**overrides):
    payload = {
        "frame": "body",
        "translation_m": {"forward": 1.0, "right": 0.0, "up": 0.0},
    }
    payload.update(overrides)
    return payload


def test_precision_move_accepts_finite_translation():
    req = PrecisionMoveRequest.model_validate(_base_body())
    assert req.translation_m["forward"] == pytest.approx(1.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "nan", "inf"])
def test_precision_move_rejects_nonfinite_translation(bad):
    with pytest.raises((ValidationError, ValueError), match="finite"):
        PrecisionMoveRequest.model_validate(
            _base_body(translation_m={"forward": bad, "right": 0.0, "up": 0.0})
        )


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), "inf"])
def test_precision_move_rejects_nonfinite_speed(bad):
    with pytest.raises(ValidationError):
        PrecisionMoveRequest.model_validate(_base_body(speed_m_s=bad))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "nan"])
def test_precision_move_rejects_nonfinite_yaw_degrees(bad):
    with pytest.raises((ValidationError, ValueError)):
        PrecisionMoveRequest.model_validate(
            _base_body(
                translation_m={"forward": 0.0, "right": 0.0, "up": 0.0},
                yaw={"mode": "absolute_heading", "degrees": bad},
            )
        )


def test_precision_move_happy_yaw_absolute():
    req = PrecisionMoveRequest.model_validate(
        _base_body(
            translation_m={"forward": 0.0, "right": 0.0, "up": 0.0},
            yaw={"mode": "absolute_heading", "degrees": 90.0},
        )
    )
    assert req.yaw.degrees == pytest.approx(90.0)
    assert math.isfinite(req.yaw.degrees)
