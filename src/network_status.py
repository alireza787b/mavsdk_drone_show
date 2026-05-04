"""Node network status helpers used by heartbeat and drone API surfaces."""

from __future__ import annotations

import os
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Any


_INTERNET_CACHE: dict[str, Any] = {"checked_at": 0, "payload": None}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float, minimum: float | None = None) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value) if minimum is not None else value


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    try:
        value = int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value) if minimum is not None else value


def _split_nmcli_line(line: str) -> list[str]:
    placeholder = "\0COLON\0"
    escaped = line.replace(r"\:", placeholder)
    return [part.replace(placeholder, ":").replace(r"\\", "\\") for part in escaped.split(":")]


def _run_text(command: list[str], timeout: float = 2.0) -> str:
    return subprocess.check_output(command, universal_newlines=True, timeout=timeout)


def _is_usb_backed_interface(device: str) -> bool:
    if not device:
        return False
    try:
        sysfs_path = os.path.realpath(os.path.join("/sys/class/net", device, "device"))
    except (OSError, TypeError, ValueError):
        return False
    return "/usb" in sysfs_path.lower()


def _default_route_interface() -> str:
    try:
        output = _run_text(["ip", "-4", "route", "show", "default"], timeout=1.0)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""
    for line in output.splitlines():
        parts = line.split()
        if "dev" in parts:
            dev_index = parts.index("dev") + 1
            if dev_index < len(parts):
                return parts[dev_index].strip()
    return ""


def _classify_device(device: str, nm_type: str) -> str:
    dev = device.lower()
    kind = nm_type.lower()
    if kind in {"wifi", "wireless", "802-11-wireless"} or dev.startswith(("wl", "wifi")):
        return "wifi"
    if kind in {"gsm", "cdma", "wwan"} or dev.startswith(("wwan", "ppp", "cdc-wdm")):
        return "cellular"
    if dev.startswith("usb") or (
        (dev.startswith("enx") or kind in {"ethernet", "802-3-ethernet"})
        and _is_usb_backed_interface(device)
    ):
        return "usb_modem"
    if dev.startswith(("eth", "enp", "ens", "eno", "enx")) or kind in {"ethernet", "802-3-ethernet"}:
        return "ethernet"
    if dev.startswith(("wt", "tun", "tap")) or kind in {"tun", "vpn", "wireguard"}:
        return "vpn"
    return kind or "unknown"


def _link_label(link_type: str) -> str:
    return {
        "wifi": "Wi-Fi",
        "ethernet": "Ethernet",
        "usb_modem": "4G USB",
        "cellular": "Cellular",
        "vpn": "VPN",
    }.get(link_type, "Network")


@dataclass(frozen=True)
class _WifiReport:
    ssid: str
    signal: int | str
    device: str


def _active_wifi() -> _WifiReport | None:
    commands = [
        ["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,DEVICE", "dev", "wifi"],
        ["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"],
    ]
    for command in commands:
        try:
            output = _run_text(command, timeout=2.0)
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            continue
        for line in output.splitlines():
            parts = _split_nmcli_line(line)
            if len(parts) >= 3 and parts[0].lower() == "yes":
                signal: int | str = int(parts[2]) if parts[2].isdigit() else "Unknown"
                return _WifiReport(ssid=parts[1], signal=signal, device=parts[3] if len(parts) >= 4 else "")
    return None


def _active_links(wifi: _WifiReport | None) -> list[dict[str, Any]]:
    try:
        output = _run_text(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"], timeout=2.0)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return []

    links: list[dict[str, Any]] = []
    for line in output.splitlines():
        parts = _split_nmcli_line(line)
        if len(parts) < 4:
            continue
        device, nm_type, state, connection = [part.strip() for part in parts[:4]]
        if state.lower() != "connected" or not device:
            continue
        link_type = _classify_device(device, nm_type)
        link: dict[str, Any] = {
            "type": link_type,
            "label": _link_label(link_type),
            "interface": device,
            "connection_name": connection,
        }
        if link_type == "wifi" and wifi:
            link["ssid"] = wifi.ssid
            link["signal_strength_percent"] = wifi.signal
        links.append(link)
    return links


def _internet_status() -> dict[str, Any]:
    enabled = _env_flag("MDS_INTERNET_CHECK_ENABLED", True)
    target = os.getenv("MDS_INTERNET_CHECK_HOST", "1.1.1.1").strip() or "1.1.1.1"
    timeout_sec = _env_float("MDS_INTERNET_CHECK_TIMEOUT_SEC", 1.5, minimum=0.2)
    interval_sec = _env_float("MDS_INTERNET_CHECK_INTERVAL_SEC", 30.0, minimum=1.0)
    port = _env_int("MDS_INTERNET_CHECK_PORT", 0, minimum=0)
    now = _now_ms()

    if not enabled:
        return {
            "enabled": False,
            "reachable": None,
            "method": "disabled",
            "target": target,
            "checked_at": now,
            "error": None,
        }

    cached = _INTERNET_CACHE.get("payload")
    if cached and (now - int(_INTERNET_CACHE.get("checked_at") or 0)) < interval_sec * 1000:
        return dict(cached)

    payload: dict[str, Any] = {
        "enabled": True,
        "reachable": None,
        "method": "tcp" if port else "icmp",
        "target": f"{target}:{port}" if port else target,
        "checked_at": now,
        "error": None,
    }
    try:
        if port:
            with socket.create_connection((target, port), timeout=timeout_sec):
                payload["reachable"] = True
        else:
            completed = subprocess.run(
                ["ping", "-c", "1", "-W", str(max(1, int(timeout_sec))), target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout_sec + 0.5,
                check=False,
            )
            payload["reachable"] = completed.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError, OSError, socket.error) as exc:
        payload["reachable"] = False
        payload["error"] = str(exc)

    _INTERNET_CACHE["checked_at"] = now
    _INTERNET_CACHE["payload"] = dict(payload)
    return payload


def build_network_info() -> dict[str, Any]:
    """Return compact, backward-compatible node network metadata."""
    timestamp = _now_ms()
    wifi = _active_wifi()
    active_links = _active_links(wifi)
    default_interface = _default_route_interface()
    internet = _internet_status()

    wifi_payload = None
    if wifi:
        wifi_payload = {
            "ssid": wifi.ssid,
            "signal_strength_percent": wifi.signal,
        }
        if wifi.device:
            wifi_payload["interface"] = wifi.device

    ethernet_link = next((link for link in active_links if link.get("type") == "ethernet"), None)
    usb_modem_link = next((link for link in active_links if link.get("type") == "usb_modem"), None)
    cellular_link = next((link for link in active_links if link.get("type") == "cellular"), None)

    default_link = next((link for link in active_links if link.get("interface") == default_interface), None)
    if not default_link:
        default_link = next((link for link in active_links if link.get("type") in {"wifi", "usb_modem", "cellular", "ethernet"}), None)

    primary_link = None
    if default_link:
        primary_link = {
            **default_link,
            "is_default_route": default_link.get("interface") == default_interface,
            "internet_reachable": internet.get("reachable"),
        }

    return {
        "wifi": wifi_payload,
        "ethernet": {
            "interface": ethernet_link["interface"],
            "connection_name": ethernet_link.get("connection_name", ""),
        } if ethernet_link else None,
        "usb_modem": {
            "interface": usb_modem_link["interface"],
            "connection_name": usb_modem_link.get("connection_name", ""),
        } if usb_modem_link else None,
        "cellular": {
            "interface": cellular_link["interface"],
            "connection_name": cellular_link.get("connection_name", ""),
        } if cellular_link else None,
        "primary_link": primary_link,
        "active_links": active_links,
        "default_route_interface": default_interface,
        "internet": internet,
        "timestamp": timestamp,
    }
