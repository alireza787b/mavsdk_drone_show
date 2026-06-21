"""Tests for GCS-to-drone log proxy logic."""
import json
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Add gcs-server to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'gcs-server'))

import httpx


class TestResolveDroneIp:
    def test_resolve_known_drone(self):
        from log_proxy import resolve_drone_ip
        drones = [
            {"hw_id": "1", "ip": "192.168.1.101"},
            {"hw_id": "5", "ip": "192.168.1.105"},
        ]
        with patch("log_proxy.load_config", return_value=drones):
            ip = resolve_drone_ip(5)
            assert ip == "192.168.1.105"

    def test_resolve_unknown_drone_returns_none(self):
        from log_proxy import resolve_drone_ip
        drones = [{"hw_id": "1", "ip": "192.168.1.101"}]
        with patch("log_proxy.load_config", return_value=drones):
            ip = resolve_drone_ip(99)
            assert ip is None

    def test_resolve_handles_string_hw_id(self):
        from log_proxy import resolve_drone_ip
        drones = [{"hw_id": "005", "ip": "192.168.1.105"}]
        with patch("log_proxy.load_config", return_value=drones):
            ip = resolve_drone_ip(5)
            assert ip == "192.168.1.105"


class TestFetchDroneSessions:
    @pytest.mark.asyncio
    async def test_fetch_sessions_success(self):
        from log_proxy import fetch_drone_sessions
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "sessions": [{"session_id": "s_20260319_100000", "size_bytes": 1024}]
        }

        with patch("log_proxy.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_response)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = client_instance

            result = await fetch_drone_sessions("192.168.1.105")
            assert result["sessions"][0]["session_id"] == "s_20260319_100000"

    @pytest.mark.asyncio
    async def test_fetch_sessions_unreachable(self):
        from log_proxy import fetch_drone_sessions

        with patch("log_proxy.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = client_instance

            result = await fetch_drone_sessions("192.168.1.105")
            assert result is None


class TestFetchDroneSessionContent:
    @pytest.mark.asyncio
    async def test_fetch_content_with_filters(self):
        from log_proxy import fetch_drone_session_content
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "session_id": "s_20260319_100000",
            "count": 1,
            "lines": [{"level": "WARNING", "msg": "test"}],
        }

        with patch("log_proxy.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_response)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = client_instance

            result = await fetch_drone_session_content(
                "192.168.1.105", "s_20260319_100000", level="WARNING"
            )
            assert result["count"] == 1
            # Verify query params were passed
            call_args = client_instance.get.call_args
            assert call_args.kwargs.get("params", {}).get("level") == "WARNING"


class TestFetchDroneJsonSync:
    def test_fetch_drone_json_sync_success(self):
        from log_proxy import fetch_drone_json_sync

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"count": 1}

        with patch("log_proxy.httpx.Client") as MockClient:
            client_instance = MagicMock()
            client_instance.get = MagicMock(return_value=mock_response)
            client_instance.__enter__ = MagicMock(return_value=client_instance)
            client_instance.__exit__ = MagicMock(return_value=None)
            MockClient.return_value = client_instance

            result = fetch_drone_json_sync("192.168.1.105", "/api/v1/ulog/files", params={"limit": 1})

        assert result == {"count": 1}
        call_args = client_instance.get.call_args
        assert call_args.args[0] == "http://192.168.1.105:7070/api/v1/ulog/files"
        assert call_args.kwargs["params"] == {"limit": 1}

    def test_fetch_drone_json_sync_maps_http_errors(self):
        from log_proxy import DroneProxyResponseError, fetch_drone_json_sync

        mock_response = MagicMock()
        mock_response.status_code = 409
        mock_response.json.return_value = {"detail": "vehicle armed"}

        with patch("log_proxy.httpx.Client") as MockClient:
            client_instance = MagicMock()
            client_instance.get = MagicMock(return_value=mock_response)
            client_instance.__enter__ = MagicMock(return_value=client_instance)
            client_instance.__exit__ = MagicMock(return_value=None)
            MockClient.return_value = client_instance

            with pytest.raises(DroneProxyResponseError) as exc_info:
                fetch_drone_json_sync("192.168.1.105", "/api/v1/ulog/files/1/summary")

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "vehicle armed"


class TestStreamDroneLogs:
    def test_stream_error_emits_structured_warning_entry(self):
        from log_proxy import stream_drone_logs

        with patch("log_proxy.httpx.Client") as MockClient:
            client_instance = MagicMock()
            client_instance.stream = MagicMock(side_effect=httpx.ConnectError("All connection attempts failed"))
            client_instance.__enter__ = MagicMock(return_value=client_instance)
            client_instance.__exit__ = MagicMock(return_value=None)
            MockClient.return_value = client_instance

            stream = stream_drone_logs("192.168.1.105", drone_id=5)
            line = next(stream)

        assert line.startswith("data: ")
        payload = json.loads(line[len("data: "):])
        assert payload["level"] == "WARNING"
        assert payload["component"] == "log_proxy"
        assert payload["source"] == "gcs"
        assert payload["drone_id"] == 5
        assert "All connection attempts failed" in payload["msg"]

    def test_stream_cancellation_exits_quietly(self):
        from log_proxy import stream_drone_logs

        class _CancelingResponse:
            def raise_for_status(self):
                return None

            def iter_lines(self):
                raise GeneratorExit
                yield  # pragma: no cover

        class _StreamContext:
            def __enter__(self):
                return _CancelingResponse()

            def __exit__(self, exc_type, exc, tb):
                return None

        with patch("log_proxy.httpx.Client") as MockClient:
            client_instance = MagicMock()
            client_instance.stream = MagicMock(return_value=_StreamContext())
            client_instance.__enter__ = MagicMock(return_value=client_instance)
            client_instance.__exit__ = MagicMock(return_value=None)
            MockClient.return_value = client_instance

            stream = stream_drone_logs("192.168.1.105", drone_id=5)
            with pytest.raises(StopIteration):
                next(stream)
