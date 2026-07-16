"""Unit tests for Params._safe_float non-finite rejection."""

import math

import src.params as params_mod


def test_safe_float_finite():
    assert params_mod._safe_float("1.5", 0.0) == 1.5
    assert params_mod._safe_float("2", 0.0) == 2.0


def test_safe_float_invalid_uses_default():
    assert params_mod._safe_float("not-a-number", 3.25) == 3.25
    assert params_mod._safe_float(None, 9.0) == 9.0  # type: ignore[arg-type]


def test_safe_float_non_finite_uses_default():
    assert params_mod._safe_float("inf", 4.0) == 4.0
    assert params_mod._safe_float("-inf", 5.0) == 5.0
    assert params_mod._safe_float("nan", 6.0) == 6.0
    assert params_mod._safe_float("NaN", 7.0) == 7.0
    # numeric non-finite inputs if callers pass them
    assert params_mod._safe_float(math.inf, 8.0) == 8.0  # type: ignore[arg-type]
    assert params_mod._safe_float(math.nan, 1.25) == 1.25  # type: ignore[arg-type]
