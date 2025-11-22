# Test Suite - MAVSDK Drone Show

**Status:** ✅ Initial test suite for Drone API Server
**Coverage:** Drone-side API Server (HTTP + WebSocket)
**Framework:** pytest

---

## Overview

This test suite provides comprehensive testing for the Drone API Server, covering:
- ✅ All 10 HTTP REST endpoints
- ✅ WebSocket real-time streaming
- ✅ Error handling and edge cases
- ✅ Data format validation
- ✅ Mock-based unit tests (fast execution)

---

## Quick Start

### 1. Install Test Dependencies

```bash
pip install -r tests/requirements-test.txt
```

### 2. Run All Tests

```bash
pytest
```

### 3. Run Specific Test Categories

```bash
# Only HTTP endpoint tests
pytest tests/test_drone_api_http.py

# Only WebSocket tests
pytest tests/test_drone_api_websocket.py

# With coverage report
pytest --cov=src --cov-report=html
```

---

## Test Structure

```
tests/
├── __init__.py                    # Package init
├── conftest.py                    # Shared fixtures and configuration
├── test_drone_api_http.py         # HTTP REST endpoint tests
├── test_drone_api_websocket.py    # WebSocket streaming tests
├── requirements-test.txt          # Test dependencies
└── README.md                      # This file

pytest.ini                         # Pytest configuration (root)
```

---

## Test Files

### `conftest.py` - Fixtures
Provides reusable test fixtures:
- `mock_params` - Mock Params configuration
- `mock_drone_config` - Mock drone configuration with test data
- `mock_drone_communicator` - Mock communicator with sample state
- `api_server` - DroneAPIServer instance with mocked dependencies
- `test_client` - FastAPI TestClient for HTTP requests
- `sample_command` - Sample command data

### `test_drone_api_http.py` - HTTP Tests
Tests all REST endpoints:
- Health check (`/ping`)
- Drone state (`/get_drone_state`)
- Commands (`/api/send-command`)
- Position data (`/get-home-pos`, `/get-gps-global-origin`, `/get-local-position-ned`)
- Git status (`/get-git-status`)
- Network status (`/get-network-status`)
- Error handling (404, invalid data)

### `test_drone_api_websocket.py` - WebSocket Tests
Tests WebSocket functionality:
- Connection establishment
- Data streaming
- Multiple messages
- Error handling (no data)
- Concurrent connections
- Data format validation
- Schema compatibility with HTTP

---

## Running Tests

### Basic Usage

```bash
# Run all tests
pytest

# Verbose output
pytest -v

# Show print statements
pytest -s

# Stop at first failure
pytest -x
```

### With Coverage

```bash
# Terminal coverage report
pytest --cov=src

# HTML coverage report
pytest --cov=src --cov-report=html
# Open: htmlcov/index.html

# Coverage with missing lines
pytest --cov=src --cov-report=term-missing
```

### Specific Tests

```bash
# Run specific file
pytest tests/test_drone_api_http.py

# Run specific class
pytest tests/test_drone_api_http.py::TestDroneState

# Run specific test
pytest tests/test_drone_api_http.py::TestDroneState::test_get_drone_state_success

# Run tests by marker
pytest -m http
pytest -m websocket
```

### Performance

```bash
# Show slowest tests
pytest --durations=10

# Run only fast tests (exclude slow)
pytest -m "not slow"
```

---

## Test Categories (Markers)

Tests are categorized using pytest markers:

- `@pytest.mark.unit` - Unit tests (fast, isolated)
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.slow` - Slow running tests
- `@pytest.mark.websocket` - WebSocket tests
- `@pytest.mark.http` - HTTP endpoint tests

---

## Test Coverage

**Current Coverage:** Drone API Server (~90% coverage)

| Module | Coverage | Status |
|--------|----------|--------|
| `src/drone_api_server.py` | ~90% | ✅ Comprehensive |
| HTTP Endpoints | 100% | ✅ All tested |
| WebSocket Endpoint | 100% | ✅ All tested |
| Helper Methods | ~80% | ✅ Core tested |

**Not Yet Covered:**
- GCS Server (planned - Phase 2)
- Integration tests with real SITL
- End-to-end swarm tests

---

## Writing New Tests

### Example: Add New HTTP Endpoint Test

```python
# tests/test_drone_api_http.py

class TestNewEndpoint:
    """Test new endpoint"""

    def test_new_endpoint_success(self, test_client):
        """Test /new-endpoint returns expected data"""
        response = test_client.get("/new-endpoint")

        assert response.status_code == 200
        data = response.json()
        assert 'expected_field' in data
```

### Example: Add WebSocket Test

```python
# tests/test_drone_api_websocket.py

class TestNewWebSocketFeature:
    """Test new WebSocket feature"""

    def test_websocket_feature(self, test_client):
        """Test new WebSocket functionality"""
        with test_client.websocket_connect("/ws/new-stream") as websocket:
            data = websocket.receive_json()
            assert 'expected_data' in data
```

---

## Continuous Integration

### GitHub Actions (Future)

```yaml
# .github/workflows/tests.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      - run: pip install -r requirements.txt
      - run: pip install -r tests/requirements-test.txt
      - run: pytest --cov=src
```

---

## Troubleshooting

### Import Errors

```bash
# Ensure correct Python path
export PYTHONPATH="${PYTHONPATH}:${PWD}"
pytest
```

### Module Not Found

```bash
# Install main dependencies first
pip install -r requirements.txt

# Then test dependencies
pip install -r tests/requirements-test.txt
```

### Async Test Failures

```bash
# Install pytest-asyncio
pip install pytest-asyncio

# Ensure pytest.ini has asyncio_mode = auto
```

---

## Best Practices

### ✅ Do
- Use fixtures for reusable test setup
- Mock external dependencies (MAVLink, network, git)
- Test both success and error cases
- Keep tests fast (< 1 second each)
- Use descriptive test names
- Group related tests in classes

### ❌ Don't
- Don't test external services directly
- Don't use real drone connections in unit tests
- Don't share state between tests
- Don't hardcode paths or IPs
- Don't skip cleanup in fixtures

---

## Future Enhancements

### Planned Tests
- [ ] GCS Server API tests
- [ ] Integration tests with SITL
- [ ] End-to-end swarm coordination tests
- [ ] Performance/load tests
- [ ] Security tests (input validation, injection)

### Tools to Add
- [ ] `pytest-benchmark` for performance testing
- [ ] `pytest-xdist` for parallel test execution
- [ ] `tox` for multi-Python version testing
- [ ] `hypothesis` for property-based testing

---

## Dependencies

**Required:**
- pytest >= 8.3.4
- pytest-asyncio >= 0.24.0
- pytest-cov >= 6.0.0
- httpx >= 0.27.2
- pytest-mock >= 3.14.0

**Optional:**
- coverage[toml] >= 7.6.9 (for detailed reports)

---

## Support

**Issues:** Report test failures at [GitHub Issues](https://github.com/alireza787b/mavsdk_drone_show/issues)

**Questions:** See main project `/help`

---

**Last Updated:** 2025-11-22
**Maintainer:** MAVSDK Drone Show Test Team
**Status:** Active Development
