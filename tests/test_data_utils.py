# tests/test_data_utils.py
"""
Data Utilities Tests
====================
Tests for safe type conversion functions in functions/data_utils.py.
"""

import pytest


class TestSafeInt:
    """Test safe_int function"""

    def test_valid_int(self):
        """Test conversion of valid integer"""
        from functions.data_utils import safe_int

        assert safe_int(42) == 42
        assert safe_int(0) == 0
        assert safe_int(-10) == -10

    def test_valid_string_int(self):
        """Test conversion of string to int"""
        from functions.data_utils import safe_int

        assert safe_int("42") == 42
        assert safe_int("-10") == -10

    def test_valid_float_to_int(self):
        """Test conversion of float to int (truncates)"""
        from functions.data_utils import safe_int

        assert safe_int(3.7) == 3
        assert safe_int(3.2) == 3

    def test_none_returns_default(self):
        """Test None returns default value"""
        from functions.data_utils import safe_int

        assert safe_int(None) == 0
        assert safe_int(None, default=99) == 99

    def test_invalid_string_returns_default(self):
        """Test invalid string returns default"""
        from functions.data_utils import safe_int

        assert safe_int("not_a_number") == 0
        assert safe_int("abc", default=5) == 5

    def test_invalid_type_returns_default(self):
        """Test invalid types return default"""
        from functions.data_utils import safe_int

        assert safe_int([1, 2, 3]) == 0
        assert safe_int({'key': 'value'}) == 0


class TestSafeFloat:
    """Test safe_float function"""

    def test_valid_float(self):
        """Test conversion of valid float"""
        from functions.data_utils import safe_float

        assert safe_float(3.14) == 3.14
        assert safe_float(0.0) == 0.0
        assert safe_float(-2.5) == -2.5

    def test_valid_int_to_float(self):
        """Test conversion of int to float"""
        from functions.data_utils import safe_float

        assert safe_float(42) == 42.0
        assert safe_float(-10) == -10.0

    def test_valid_string_float(self):
        """Test conversion of string to float"""
        from functions.data_utils import safe_float

        assert safe_float("3.14") == 3.14
        assert safe_float("-2.5") == -2.5

    def test_none_returns_default(self):
        """Test None returns default value"""
        from functions.data_utils import safe_float

        assert safe_float(None) == 0.0
        assert safe_float(None, default=1.5) == 1.5

    def test_invalid_string_returns_default(self):
        """Test invalid string returns default"""
        from functions.data_utils import safe_float

        assert safe_float("not_a_number") == 0.0
        assert safe_float("abc", default=9.9) == 9.9

    def test_invalid_type_returns_default(self):
        """Test invalid types return default"""
        from functions.data_utils import safe_float

        assert safe_float([1.0, 2.0]) == 0.0
        assert safe_float({'key': 1.5}) == 0.0

    def test_nonfinite_returns_default(self):
        """Non-finite values must not masquerade as valid telemetry numbers."""
        import math
        from functions.data_utils import safe_float

        assert safe_float(math.nan) == 0.0
        assert safe_float(float("nan"), default=1.5) == 1.5
        assert safe_float(math.inf) == 0.0
        assert safe_float(-math.inf, default=-1.0) == -1.0


class TestSafeGet:
    """Test safe_get function"""

    def test_existing_key(self):
        """Test getting existing key from dict"""
        from functions.data_utils import safe_get

        data = {'name': 'drone1', 'id': 42}
        assert safe_get(data, 'name') == 'drone1'
        assert safe_get(data, 'id') == 42

    def test_missing_key_returns_default(self):
        """Test missing key returns default"""
        from functions.data_utils import safe_get

        data = {'name': 'drone1'}
        assert safe_get(data, 'missing') is None
        assert safe_get(data, 'missing', default='unknown') == 'unknown'

    def test_none_dict_returns_default(self):
        """Test None dict returns default"""
        from functions.data_utils import safe_get

        assert safe_get(None, 'key') is None
        assert safe_get(None, 'key', default='fallback') == 'fallback'

    def test_empty_dict_returns_default(self):
        """Test empty dict returns default for any key"""
        from functions.data_utils import safe_get

        assert safe_get({}, 'key') is None
        assert safe_get({}, 'key', default=0) == 0

    def test_non_dict_returns_default(self):
        """Test non-dict types return default"""
        from functions.data_utils import safe_get

        assert safe_get("not_a_dict", 'key') is None
        assert safe_get([1, 2, 3], 'key') is None
        assert safe_get(42, 'key', default='error') == 'error'

    def test_nested_value(self):
        """Test getting nested dict value"""
        from functions.data_utils import safe_get

        data = {'position': {'lat': 37.7749, 'lon': -122.4194}}
        position = safe_get(data, 'position')
        assert position == {'lat': 37.7749, 'lon': -122.4194}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
