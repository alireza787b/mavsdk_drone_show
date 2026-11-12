"""One pinned client/server contract and explicit MAVSDK transport semantics.

This module intentionally has no MAVSDK or third-party imports: provisioning
must work before the companion virtual environment exists.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path
import subprocess
import sys


MANIFEST_PATH = Path(__file__).resolve().parents[1] / "config/mavsdk-runtime.json"


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    data = json.loads(path.read_text())
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported MAVSDK compatibility manifest")
    return data


def manifest_digest(path: Path = MANIFEST_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def platform_asset(manifest: dict, machine: str | None = None) -> tuple[str, dict]:
    if platform.system() != "Linux":
        raise ValueError("MDS companion server provisioning supports Linux only")
    machine = machine or platform.machine().lower()
    machine = {"amd64": "x86_64", "arm64": "aarch64", "armhf": "armv7l"}.get(machine, machine)
    try:
        return machine, manifest["server"]["assets"][machine]
    except KeyError as exc:
        raise ValueError(f"Unsupported MAVSDK server architecture: {machine}") from exc


def udp_listen_url(port: int) -> str:
    """v4 explicit UDP listener, preserving the legacy all-interface binding."""
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("UDP port must be in 1..65535")
    return f"udpin://0.0.0.0:{port}"


def matches_udp_listener(args: list[str], port: int) -> bool:
    # Exact legacy spelling is accepted only for an already-owned old process.
    # A remote/other-port endpoint never grants borrowing authority.
    return udp_listen_url(port) in args or f"udp://:{int(port)}" in args


def verify_elf(path: Path, asset: dict) -> None:
    with path.open("rb") as source:
        header = source.read(20)
    if len(header) < 20 or header[:4] != b"\x7fELF" or header[5] != 1:
        raise ValueError("Candidate is not a little-endian Linux ELF executable")
    if header[4] != asset["elf_class"] or int.from_bytes(header[18:20], "little") != asset["elf_machine"]:
        raise ValueError("MAVSDK candidate ELF architecture does not match this host")


def verify_help(path: Path) -> None:
    # --version is not a supported probe and can open/wait on a transport.
    try:
        result = subprocess.run([str(path.resolve()), "--help"], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("MAVSDK --help probe timed out") from exc
    if result.returncode != 0:
        raise ValueError("MAVSDK candidate failed bounded --help probe")


def active_server_pids(runtime_directory: Path | None = None, *, proc_root: Path = Path("/proc")) -> list[int]:
    """Find this deployment's server, not neighboring isolated Docker fleets."""
    directory = (runtime_directory or MANIFEST_PATH.parents[1]).resolve()
    binary = directory / "mavsdk_server"
    found = []
    for process in proc_root.iterdir():
        if not process.name.isdigit():
            continue
        try:
            executable = os.readlink(process / "exe")
            executable_path = Path(executable.removesuffix(" (deleted)"))
            if "mavsdk_server" not in executable_path.name:
                continue
            cwd = Path(os.readlink(process / "cwd").removesuffix(" (deleted)"))
            same_binary = binary.exists() and (process / "exe").samefile(binary)
            if same_binary or executable_path.is_relative_to(directory) or cwd.is_relative_to(directory):
                found.append(int(process.name))
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            raise ValueError("Cannot establish MAVSDK idle state; run the maintenance check with sufficient access") from exc
    return found


def require_idle(runtime_directory: Path | None = None) -> None:
    pids = active_server_pids(runtime_directory)
    if pids:
        raise ValueError(f"MAVSDK server is active (PIDs {pids}); stop the grounded runtime explicitly before upgrading")


def verify_python_platform(manifest: dict | None = None) -> dict:
    manifest = manifest or load_manifest()
    contract = manifest["python"]
    if platform.python_implementation() != "CPython":
        raise ValueError("The reviewed MDS SDK wheel matrix requires CPython")
    if sys.version_info.major != 3 or sys.version_info.minor not in contract["supported_minors"]:
        raise ValueError("This Python version is outside the reviewed MDS SDK platform matrix (3.11–3.13)")
    machine, _asset = platform_asset(manifest)
    if machine not in contract["linux_platforms"]:
        raise ValueError("This Python/CPU platform is not in the reviewed SDK matrix; a server asset alone does not establish compatible Python wheels")
    return {"python": sys.version.split()[0], "platform": machine}


def verify_python(manifest: dict | None = None) -> dict:
    manifest = manifest or load_manifest()
    verify_python_platform(manifest)
    contract = manifest["python"]
    versions = {name: importlib.metadata.version(name) for name in
                (contract["distribution"], "grpcio", "protobuf")}
    expected = {contract["distribution"]: contract["version"], "grpcio": contract["grpcio"], "protobuf": contract["protobuf"]}
    if versions != expected:
        raise ValueError(f"MAVSDK Python dependencies do not match the reviewed manifest: {versions}")
    # Actual import catches generated-code requirements missing in wheel metadata.
    module = importlib.import_module(contract["import"])
    distribution = importlib.metadata.distribution(contract["distribution"])
    expected_module = Path(distribution.locate_file(f"{contract['import']}/__init__.py")).resolve()
    if Path(module.__file__).resolve() != expected_module:
        raise ValueError("MAVSDK module is shadowed; imports must come from the selected installed mavsdk-grpc distribution")
    return {"versions": versions, "module_file": module.__file__, "python": sys.version.split()[0]}
