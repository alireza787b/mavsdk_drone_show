import subprocess

from src import network_status


def test_build_network_info_classifies_usb_modem_default_route(monkeypatch):
    outputs = {
        ("nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,DEVICE", "dev", "wifi"): "no:field:42:wlan0\n",
        ("nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"): "no:field:42\n",
        ("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"): (
            "usb0:ethernet:connected:Wired connection 1\n"
            "wlan0:wifi:disconnected:--\n"
            "wt0:tun:connected:netbird\n"
        ),
        ("ip", "-4", "route", "show", "default"): "default via 192.168.8.1 dev usb0 proto dhcp metric 100\n",
    }

    def fake_check_output(command, universal_newlines=True, timeout=None):
        key = tuple(command)
        if key not in outputs:
            raise AssertionError(command)
        return outputs[key]

    class Completed:
        returncode = 0

    monkeypatch.setattr(network_status.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(network_status.subprocess, "run", lambda *args, **kwargs: Completed())
    monkeypatch.setattr(network_status, "_INTERNET_CACHE", {"checked_at": 0, "payload": None})

    payload = network_status.build_network_info()

    assert payload["usb_modem"]["interface"] == "usb0"
    assert payload["ethernet"] is None
    assert payload["primary_link"]["type"] == "usb_modem"
    assert payload["primary_link"]["label"] == "4G USB"
    assert payload["primary_link"]["internet_reachable"] is True
    assert payload["default_route_interface"] == "usb0"


def test_build_network_info_classifies_enx_usb_ethernet_as_usb_modem(monkeypatch):
    outputs = {
        ("nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,DEVICE", "dev", "wifi"): "",
        ("nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"): "",
        ("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"): (
            "enx0c5b8f279a64:ethernet:connected:Huawei E3372\n"
            "eth0:ethernet:disconnected:--\n"
        ),
        ("ip", "-4", "route", "show", "default"): (
            "default via 192.168.8.1 dev enx0c5b8f279a64 proto dhcp metric 900\n"
        ),
    }

    def fake_check_output(command, universal_newlines=True, timeout=None):
        key = tuple(command)
        if key not in outputs:
            raise AssertionError(command)
        return outputs[key]

    class Completed:
        returncode = 0

    monkeypatch.setattr(network_status.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(network_status.subprocess, "run", lambda *args, **kwargs: Completed())
    monkeypatch.setattr(
        network_status.os.path,
        "realpath",
        lambda path: "/sys/devices/platform/soc/usb1/1-1/1-1.2/net/enx0c5b8f279a64",
    )
    monkeypatch.setattr(network_status, "_INTERNET_CACHE", {"checked_at": 0, "payload": None})

    payload = network_status.build_network_info()

    assert payload["usb_modem"]["interface"] == "enx0c5b8f279a64"
    assert payload["ethernet"] is None
    assert payload["primary_link"]["type"] == "usb_modem"
    assert payload["primary_link"]["label"] == "4G USB"


def test_build_network_info_reports_wifi_and_cached_internet(monkeypatch):
    outputs = {
        ("nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,DEVICE", "dev", "wifi"): "yes:livebox-69C0:79:wlan0\n",
        ("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"): "wlan0:wifi:connected:livebox-69C0\n",
        ("ip", "-4", "route", "show", "default"): "default via 192.168.1.1 dev wlan0 proto dhcp metric 600\n",
    }

    def fake_check_output(command, universal_newlines=True, timeout=None):
        return outputs[tuple(command)]

    calls = {"run": 0}

    class Completed:
        returncode = 0

    def fake_run(*args, **kwargs):
        calls["run"] += 1
        return Completed()

    monkeypatch.setattr(network_status.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(network_status.subprocess, "run", fake_run)
    monkeypatch.setattr(network_status, "_INTERNET_CACHE", {"checked_at": 0, "payload": None})

    first = network_status.build_network_info()
    second = network_status.build_network_info()

    assert first["wifi"]["ssid"] == "livebox-69C0"
    assert first["primary_link"]["type"] == "wifi"
    assert second["internet"]["reachable"] is True
    assert calls["run"] == 1


def test_build_network_info_handles_missing_nmcli(monkeypatch):
    def fake_check_output(command, universal_newlines=True, timeout=None):
        raise FileNotFoundError(command[0])

    def fake_run(*args, **kwargs):
        raise subprocess.SubprocessError("ping unavailable")

    monkeypatch.setattr(network_status.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(network_status.subprocess, "run", fake_run)
    monkeypatch.setattr(network_status, "_INTERNET_CACHE", {"checked_at": 0, "payload": None})

    payload = network_status.build_network_info()

    assert payload["wifi"] is None
    assert payload["ethernet"] is None
    assert payload["primary_link"] is None
    assert payload["internet"]["reachable"] is False
