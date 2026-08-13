"""Shared support helpers for runtime validation tooling."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from src.gcs_api_routes import GCS_SYSTEM_RUNTIME_STATUS_ROUTE


def read_bearer_token_file(path: Path | str | None) -> str:
    """Load an API bearer token from a file without supporting raw token inputs."""

    if path in (None, ""):
        return ""
    token_path = Path(path).expanduser()
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Cannot read API token file {token_path}: {exc}") from exc
    require(token, f"API token file is empty: {token_path}")
    return token


class ValidationApiClient:
    """Small shared JSON client for runtime validators.

    Authentication is intentionally file-backed only. Validation commands do
    not accept raw bearer tokens through command-line arguments or environment
    variables, which keeps secrets out of process listings and shell history.
    """

    def __init__(
        self,
        base_url: str,
        *,
        bearer_token_file: Path | str | None = None,
        timeout_sec: float = 30.0,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.timeout_sec = float(timeout_sec)
        self._bearer_token = read_bearer_token_file(bearer_token_file)

    @property
    def authorization_headers(self) -> dict[str, str]:
        if not self._bearer_token:
            return {}
        return {"Authorization": f"Bearer {self._bearer_token}"}

    def request_json(
        self,
        method: str,
        path: str,
        payload: Any = None,
        *,
        timeout_sec: float | None = None,
    ) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json", **self.authorization_headers}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=str(method).upper(),
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_sec if timeout_sec is None else float(timeout_sec),
            ) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                body_text = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                body_text = ""
            detail = body_text or str(getattr(exc, "reason", "") or "request failed")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            raise RuntimeError(
                f"{str(method).upper()} {path} failed against {self.base_url}: {exc}"
            ) from exc

    def get_json(self, path: str, *, timeout_sec: float | None = None) -> Any:
        return self.request_json("GET", path, timeout_sec=timeout_sec)

    def post_json(
        self,
        path: str,
        payload: Any,
        *,
        timeout_sec: float | None = None,
    ) -> Any:
        return self.request_json("POST", path, payload, timeout_sec=timeout_sec)

    def put_json(
        self,
        path: str,
        payload: Any,
        *,
        timeout_sec: float | None = None,
    ) -> Any:
        return self.request_json("PUT", path, payload, timeout_sec=timeout_sec)

    def patch_json(
        self,
        path: str,
        payload: Any,
        *,
        timeout_sec: float | None = None,
    ) -> Any:
        return self.request_json("PATCH", path, payload, timeout_sec=timeout_sec)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def normalize_drone_ids(ids: Iterable[int]) -> list[int]:
    """Return sorted unique hardware IDs."""
    normalized = sorted({int(drone_id) for drone_id in ids})
    require(normalized, "No drone IDs supplied.")
    return normalized


def contiguous_fleet_reset_parameters(drone_ids: Iterable[int]) -> dict[str, int]:
    """Return the canonical contiguous-fleet reset parameters."""
    selected_ids = normalize_drone_ids(drone_ids)
    expected_ids = list(range(selected_ids[0], selected_ids[0] + len(selected_ids)))
    require(
        selected_ids == expected_ids,
        f"SITL reset only supports contiguous drone IDs today, got {selected_ids}",
    )
    return {
        "target_count": len(selected_ids),
        "start_id": selected_ids[0],
        "start_ip": selected_ids[0] + 1,
    }


def parse_csv_drone_ids(raw: str) -> list[int]:
    ids = [int(part.strip()) for part in str(raw).split(",") if part.strip()]
    return normalize_drone_ids(ids)


def build_sitl_reset_command(drone_ids: Iterable[int]) -> list[str]:
    """Build the contiguous-fleet recreate command used for clean SITL resets."""
    params = contiguous_fleet_reset_parameters(drone_ids)

    command = ["bash", "multiple_sitl/create_dockers.sh", str(params["target_count"])]
    if params["start_id"] != 1:
        command.extend(["--start-id", str(params["start_id"]), "--start-ip", str(params["start_ip"])])
    return command


def require_sitl_runtime_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Fail closed unless the target process and configured runtime are SITL."""

    mode = str(payload.get("mode") or "").strip().lower()
    configured_mode = str(payload.get("configured_mode") or "").strip().lower()
    configured_sim_mode = payload.get("configured_sim_mode")
    restart_required = bool(payload.get("restart_required"))
    require(mode == "sitl", f"Refusing SITL validation against target runtime mode {mode or 'unknown'}")
    require(
        configured_mode == "sitl" and configured_sim_mode is True,
        "Refusing SITL validation because the configured runtime is not canonical SITL",
    )
    require(
        not restart_required,
        "Refusing SITL validation because the configured and running runtime modes are not reconciled",
    )
    return payload


def fetch_and_require_sitl_runtime(
    base_url: str,
    *,
    timeout_sec: float = 5.0,
    client: ValidationApiClient | None = None,
) -> dict[str, Any]:
    """Read and validate the target runtime identity before test-side mutations."""

    url = f"{str(base_url).rstrip('/')}{GCS_SYSTEM_RUNTIME_STATUS_ROUTE}"
    if client is not None:
        try:
            payload = client.get_json(GCS_SYSTEM_RUNTIME_STATUS_ROUTE, timeout_sec=timeout_sec)
        except Exception as exc:
            raise RuntimeError(f"Cannot verify SITL target identity at {url}: {exc}") from exc
        require(isinstance(payload, dict), "SITL runtime-status response must be a JSON object")
        return require_sitl_runtime_status(payload)

    try:
        with urllib.request.urlopen(url, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise RuntimeError(f"Cannot verify SITL target identity at {url}: {exc}") from exc
    require(isinstance(payload, dict), "SITL runtime-status response must be a JSON object")
    return require_sitl_runtime_status(payload)


def write_json_report(path: Path | str | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
