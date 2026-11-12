"""Typed PX4 parameter values and exact native binary32 wire comparison.

Keep the operator's requested decimal value intact. Only comparisons use the
IEEE-754 value that the MAVSDK/MAVLink float parameter transport can carry.
"""

from __future__ import annotations

import math
import struct


ParameterValue = int | float | str
FLOAT32_MAX = 3.4028234663852886e38


def float32_wire_value(value: int | float) -> float:
    """Return the finite transmitted value, rejecting overflow/zero underflow."""
    if type(value) not in (int, float) or abs(value) > FLOAT32_MAX or not math.isfinite(value):
        raise ValueError("float parameters require a finite 32-bit numeric value")
    represented = struct.unpack("!f", struct.pack("!f", float(value)))[0]
    if value != 0 and represented == 0:
        raise ValueError("float parameter value underflows to zero in the 32-bit transport")
    return represented


def validate_parameter_value(value_type: str, value: ParameterValue) -> ParameterValue:
    """Validate without replacing the requested decimal with its wire rounding."""
    if value_type == "int":
        if type(value) is not int or not -(2**31) <= value <= 2**31 - 1:
            raise ValueError("int parameters require a signed 32-bit integer")
    elif value_type == "float":
        float32_wire_value(value)
        return float(value)
    elif value_type == "custom":
        if not isinstance(value, str) or len(value) > 1024:
            raise ValueError("custom parameters require a string value of at most 1024 characters")
    else:
        raise ValueError("unsupported PX4 parameter value type")
    return value


def parameter_values_match(value_type: str, requested_value: ParameterValue, actual_value: ParameterValue) -> bool:
    """Compare typed values; different float32 values are never verified equal.

    An absolute tolerance would hide meaningful differences at small scales.
    Known decimal-to-wire rounding is accepted, but neither a global epsilon
    nor a parameter-name exception can widen native wire-value identity.
    """
    try:
        if value_type == "float":
            return float32_wire_value(requested_value) == float32_wire_value(actual_value)
        return validate_parameter_value(value_type, requested_value) == validate_parameter_value(value_type, actual_value)
    except (TypeError, ValueError, OverflowError):
        return False
