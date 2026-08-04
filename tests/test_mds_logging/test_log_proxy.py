"""Tests for GCS-to-drone log proxy logic."""
import asyncio
import json
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Add gcs-server to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'gcs-server'))

import httpx


def _ulog_job(*, status="queued", size_bytes=8):
    return {
        "job": {
            "job_id": "job-12",
            "hw_id": "1",
            "pos_id": 3,
            "log_id": 12,
            "date_utc": "2026-07-23T10:00:00Z",
            "size_bytes": size_bytes,
            "status": status,
            "progress": 1.0 if status == "ready" else 0.0,
            "created_at": 1,
            "updated_at": 2,
        },
        "timestamp": 2,
    }


def _ulog_summary(**overrides):
    payload = {
        "schema_version": "1.0",
        "hw_id": "1",
        "pos_id": 3,
        "log_id": 12,
        "staged_job_deleted": None,
        "timestamp": 2,
        "source": {
            "source_kind": "drone",
            "log_id": 12,
            "date_utc": "2026-07-23T10:00:00Z",
            "size_bytes": 8,
        },
        "parser": {"status": "ok", "available": True},
        "parsed": True,
        "raw_content_included": False,
    }
    payload.update(overrides)
    return payload


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

        with (
            patch("log_proxy.httpx.Client") as MockClient,
            patch("log_proxy._authenticated_ulog_headers", return_value={}),
        ):
            client_instance = MagicMock()
            client_instance.request = MagicMock(return_value=mock_response)
            client_instance.__enter__ = MagicMock(return_value=client_instance)
            client_instance.__exit__ = MagicMock(return_value=None)
            MockClient.return_value = client_instance

            result = fetch_drone_json_sync("192.168.1.105", "/api/v1/ulog/files", params={"limit": 1})

        assert result == {"count": 1}
        call_args = client_instance.request.call_args
        assert call_args.args[:2] == (
            "GET",
            "http://192.168.1.105:7070/api/v1/ulog/files",
        )
        assert call_args.kwargs["params"] == {"limit": 1}

    def test_fetch_drone_json_sync_maps_http_errors(self):
        from log_proxy import DroneProxyResponseError, fetch_drone_json_sync

        mock_response = MagicMock()
        mock_response.status_code = 409
        mock_response.json.return_value = {"detail": "vehicle armed"}

        with (
            patch("log_proxy.httpx.Client") as MockClient,
            patch("log_proxy._authenticated_ulog_headers", return_value={}),
        ):
            client_instance = MagicMock()
            client_instance.request = MagicMock(return_value=mock_response)
            client_instance.__enter__ = MagicMock(return_value=client_instance)
            client_instance.__exit__ = MagicMock(return_value=None)
            MockClient.return_value = client_instance

            with pytest.raises(DroneProxyResponseError) as exc_info:
                fetch_drone_json_sync("192.168.1.105", "/api/v1/ulog/files/1/summary")

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "vehicle armed"

    def test_fetch_drone_json_sync_preserves_structured_node_error(self):
        from log_proxy import DroneProxyResponseError, fetch_drone_json_sync

        detail = {
            "code": "ulog_transport_timeout",
            "error": "ulog_transport_timeout",
            "message": "Timed out opening the node-local MAVSDK RPC channel.",
            "stage": "mavsdk_rpc_connect",
            "retryable": True,
        }
        mock_response = MagicMock()
        mock_response.status_code = 504
        mock_response.json.return_value = {"detail": detail}

        with (
            patch("log_proxy.httpx.Client") as MockClient,
            patch("log_proxy._authenticated_ulog_headers", return_value={}),
        ):
            client_instance = MagicMock()
            client_instance.request = MagicMock(return_value=mock_response)
            client_instance.__enter__ = MagicMock(return_value=client_instance)
            client_instance.__exit__ = MagicMock(return_value=None)
            MockClient.return_value = client_instance

            with pytest.raises(DroneProxyResponseError) as exc_info:
                fetch_drone_json_sync(
                    "192.168.1.105",
                    "/api/v1/ulog/files/1/summary",
                )

        assert exc_info.value.status_code == 504
        assert exc_info.value.detail == detail
        assert str(exc_info.value) == detail["message"]


class TestUlogProxyTimeouts:
    @pytest.mark.asyncio
    async def test_ulog_inventory_uses_canonical_mavsdk_timeout(self):
        from log_proxy import (
            DEFAULT_DRONE_ULOG_PROXY_TIMEOUT_SECONDS,
            fetch_drone_ulog_files,
        )

        with patch("log_proxy._request_json", new=AsyncMock(return_value={"files": []})) as request_json:
            await fetch_drone_ulog_files("192.168.1.105")

        assert request_json.await_args.kwargs["timeout"] == DEFAULT_DRONE_ULOG_PROXY_TIMEOUT_SECONDS

    def test_ulog_summary_timeout_falls_back_for_invalid_override(self, monkeypatch):
        from log_proxy import (
            DEFAULT_DRONE_ULOG_SUMMARY_TIMEOUT_SECONDS,
            drone_ulog_summary_timeout_seconds,
        )

        monkeypatch.setenv("MDS_ULOG_SUMMARY_TIMEOUT_SEC", "invalid")

        assert drone_ulog_summary_timeout_seconds() == DEFAULT_DRONE_ULOG_SUMMARY_TIMEOUT_SECONDS


class TestUlogSummaryFallback:
    @pytest.mark.asyncio
    async def test_async_entry_point_delegates_to_sync_implementation(self):
        from log_proxy import (
            fetch_drone_ulog_summary,
            fetch_drone_ulog_summary_sync,
        )

        direct = {"parsed": True, "parser": {"status": "ok"}, "source": {"source_kind": "drone"}}
        with patch("log_proxy.asyncio.to_thread", new=AsyncMock(return_value=direct)) as to_thread:
            result = await fetch_drone_ulog_summary("192.168.1.105", 12)

        assert result is direct
        to_thread.assert_awaited_once_with(
            fetch_drone_ulog_summary_sync,
            "192.168.1.105",
            12,
            timeout=90.0,
        )

    @pytest.mark.asyncio
    async def test_async_entry_point_maps_timeout_to_gateway_timeout(self):
        from log_proxy import DroneProxyResponseError, fetch_drone_ulog_summary

        with (
            patch("log_proxy.drone_ulog_summary_timeout_seconds", return_value=0.001),
            patch("log_proxy.asyncio.to_thread", new=AsyncMock(side_effect=asyncio.TimeoutError)),
        ):
            with pytest.raises(DroneProxyResponseError) as exc_info:
                await fetch_drone_ulog_summary("192.168.1.105", 12)

        assert exc_info.value.status_code == 504

    def test_sync_direct_summary_remains_preferred(self):
        from log_proxy import fetch_drone_ulog_summary_sync

        direct = _ulog_summary()
        with patch("log_proxy._request_json_sync", return_value=direct) as request_json:
            result = fetch_drone_ulog_summary_sync("192.168.1.105", 12)

        assert result["parsed"] is True
        assert result["hw_id"] == "1"
        assert result["log_id"] == 12
        assert result["parser"]["status"] == "ok"
        assert request_json.call_count == 1
        assert request_json.call_args.args[0] == "GET"
        assert request_json.call_args.args[2] == "/api/v1/ulog/files/12/summary"

    def test_sync_direct_summary_rejects_invalid_node_payload(self):
        from log_proxy import DroneProxyResponseError, fetch_drone_ulog_summary_sync

        invalid = _ulog_summary(unexpected_internal_value="not public")
        with patch("log_proxy._request_json_sync", return_value=invalid):
            with pytest.raises(DroneProxyResponseError) as exc_info:
                fetch_drone_ulog_summary_sync("192.168.1.105", 12)

        assert exc_info.value.status_code == 502
        assert exc_info.value.detail == "Drone returned an invalid ULog summary response."

    def test_fallback_runs_only_for_direct_404(self):
        from log_proxy import DroneProxyResponseError, fetch_drone_ulog_summary_sync

        with patch(
            "log_proxy._request_json_sync",
            side_effect=DroneProxyResponseError(409, "vehicle armed"),
        ) as request_json:
            with pytest.raises(DroneProxyResponseError) as exc_info:
                fetch_drone_ulog_summary_sync("192.168.1.105", 12)

        assert exc_info.value.status_code == 409
        assert request_json.call_count == 1

    def test_404_fallback_stages_parses_and_cleans(self):
        from log_proxy import DroneProxyResponseError, fetch_drone_ulog_summary_sync

        response = MagicMock()
        response.status_code = 200
        response.headers = {"content-length": "9"}
        response.iter_bytes.return_value = iter([b"ulog", b"-data"])
        stream_context = MagicMock()
        stream_context.__enter__.return_value = response
        client = MagicMock()
        client.__enter__.return_value = client
        client.stream.return_value = stream_context
        parsed_paths = []

        def request_json(method, _drone_ip, path, **kwargs):
            assert kwargs["timeout"] > 0
            if path.endswith("/summary"):
                raise DroneProxyResponseError(404, "not found")
            if method == "POST":
                return _ulog_job()
            if method == "GET":
                return _ulog_job(status="ready")
            if method == "DELETE":
                return {"status": "deleted"}
            raise AssertionError((method, path))

        def summarize(path, **_kwargs):
            parsed_paths.append(path)
            assert path.read_bytes() == b"ulog-data"
            return {
                "parsed": True,
                "parser": {"status": "ok"},
                "source": {},
                "correlation": {"status": "unverified", "evidence": {}},
                "raw_content_included": True,
            }

        with (
            patch("log_proxy._request_json_sync", side_effect=request_json) as requests,
            patch("log_proxy.httpx.Client", return_value=client),
            patch("log_proxy._authenticated_ulog_headers", return_value={}),
            patch(
                "log_proxy.summarize_ulog_file_with_timeout",
                side_effect=summarize,
            ) as parser,
            patch("log_proxy.time.sleep"),
        ):
            result = fetch_drone_ulog_summary_sync("192.168.1.105", 12)

        assert [call.args[0] for call in requests.call_args_list] == [
            "GET",
            "POST",
            "GET",
            "DELETE",
        ]
        assert parser.call_args.kwargs["max_bytes"] > 9
        assert parsed_paths and not parsed_paths[0].exists()
        assert result["parsed"] is True
        assert result["hw_id"] == "1"
        assert result["pos_id"] == 3
        assert result["log_id"] == 12
        assert result["source"]["source_kind"] == "drone_staged_download_fallback"
        assert result["source"]["size_bytes"] == 9
        assert result["correlation"]["evidence"]["target_drone_id"] == "1"
        assert result["staged_job_deleted"] is True
        assert result["raw_content_included"] is False
        assert "job_id" not in result

    def test_fallback_enforces_size_and_deletes_remote_job(self, monkeypatch):
        from log_proxy import DroneProxyResponseError, fetch_drone_ulog_summary_sync

        monkeypatch.setenv("MDS_ULOG_SUMMARY_MAX_BYTES", "4")

        def request_json(method, _drone_ip, path, **_kwargs):
            if path.endswith("/summary"):
                raise DroneProxyResponseError(404, "not found")
            if method == "POST":
                return _ulog_job(status="ready", size_bytes=5)
            if method == "DELETE":
                return {"status": "deleted"}
            raise AssertionError((method, path))

        with (
            patch("log_proxy._request_json_sync", side_effect=request_json) as requests,
            patch("log_proxy._stream_download_to_temp") as stream,
        ):
            with pytest.raises(DroneProxyResponseError) as exc_info:
                fetch_drone_ulog_summary_sync("192.168.1.105", 12)

        assert exc_info.value.status_code == 413
        stream.assert_not_called()
        assert requests.call_args_list[-1].args[0] == "DELETE"

    def test_fallback_cleans_local_and_remote_on_parser_error(self, tmp_path):
        from log_proxy import DroneProxyResponseError, fetch_drone_ulog_summary_sync

        staged_file = tmp_path / "invalid.ulg"
        staged_file.write_bytes(b"invalid")

        def request_json(method, _drone_ip, path, **_kwargs):
            if path.endswith("/summary"):
                raise DroneProxyResponseError(404, "not found")
            if method == "POST":
                return _ulog_job(status="ready")
            if method == "DELETE":
                return {"status": "deleted"}
            raise AssertionError((method, path))

        with (
            patch("log_proxy._request_json_sync", side_effect=request_json) as requests,
            patch(
                "log_proxy._stream_download_to_temp",
                return_value=(staged_file, 7),
            ),
            patch(
                "log_proxy.summarize_ulog_file_with_timeout",
                side_effect=ValueError("invalid ULog"),
            ),
        ):
            with pytest.raises(ValueError, match="invalid ULog"):
                fetch_drone_ulog_summary_sync("192.168.1.105", 12)

        assert not staged_file.exists()
        assert requests.call_args_list[-1].args[0] == "DELETE"

    def test_generic_sync_reader_delegates_summary_route_to_shared_entry_point(self):
        from log_proxy import fetch_drone_json_sync

        expected = {"parsed": True}
        with patch(
            "log_proxy.fetch_drone_ulog_summary_sync",
            return_value=expected,
        ) as summary:
            result = fetch_drone_json_sync(
                "192.168.1.105",
                "/api/v1/ulog/files/12/summary",
                timeout=10,
            )

        assert result is expected
        summary.assert_called_once_with("192.168.1.105", 12, timeout=10)


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
