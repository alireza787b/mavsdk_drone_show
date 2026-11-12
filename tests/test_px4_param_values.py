"""Parameter comparison follows binary32 transport, not scale-blind epsilon."""

import struct

import pytest

from src.px4_param_models import Px4ParamPatchEntry
from src.px4_param_values import FLOAT32_MAX, float32_wire_value, parameter_values_match


@pytest.mark.parametrize("value", [0.1, 1e-7, -1e-7, 1000.00001, 1e30, FLOAT32_MAX, 2**-149])
def test_decimal_to_wire_rounding_matches_at_every_scale(value):
    represented = struct.unpack("!f", struct.pack("!f", value))[0]
    assert parameter_values_match("float", value, represented)


@pytest.mark.parametrize("requested,actual", [
    (1e-7, 0.0), (1e-7, 2e-7), (-1e-7, 0.0), (-1e-7, -2e-7),
    (2**-149, 0.0), (0.0, 2**-149), (1.0, 1.0000001192092896),
])
def test_distinct_native_float_values_never_match(requested, actual):
    assert not parameter_values_match("float", requested, actual)


@pytest.mark.parametrize("value", [1e-47, -1e-47, 1e99, -1e99, float("inf"), float("nan"), True])
def test_invalid_float_wire_values_are_rejected(value):
    with pytest.raises(ValueError):
        float32_wire_value(value)
    assert not parameter_values_match("float", value, value)


def test_signed_zero_is_numerically_equal_but_subnormal_is_not_zero():
    assert parameter_values_match("float", -0.0, 0.0)
    assert not parameter_values_match("float", 2**-149, 0.0)


def test_requested_decimal_is_preserved_in_typed_entries():
    entry = Px4ParamPatchEntry(name="MPC_XY_CRUISE", value_type="float", value=0.1, expected_current_value=0.3)
    assert entry.value == 0.1
    assert entry.expected_current_value == 0.3
    assert entry.value != float32_wire_value(0.1)


def test_non_float_values_keep_strict_type_and_exact_identity():
    assert parameter_values_match("int", 1, 1)
    assert not parameter_values_match("int", 1, True)
    assert not parameter_values_match("int", 1, 1.0)
    assert parameter_values_match("custom", "alpha", "alpha")
    assert not parameter_values_match("custom", "1", 1)
