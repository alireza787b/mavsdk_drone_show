#!/usr/bin/env python3
"""Select an eligible MDS interpreter; provision the pinned fallback in images only.

This bootstrap intentionally uses only the standard library and runs on the old
image's Python 3.10. It never changes /usr/bin/python3 or a host Python environment.
The SDK manifest owns the supported minor versions; the source manifest owns the
managed fallback, its prefix and the upstream source digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/python-runtime.json"
CORE_MODULES = ["ssl", "sqlite3", "bz2", "lzma", "ctypes", "zlib", "venv"]


def load_manifest(path: Path = MANIFEST) -> dict:
    data = json.loads(path.read_text())
    version = data["version"]
    if not re.fullmatch(r"3\.\d+\.\d+", version):
        raise ValueError("Managed Python version must be an explicit release")
    if data["source_url"] != f"https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz":
        raise ValueError("Managed Python must use the pinned official source URL")
    if not re.fullmatch(r"[a-f0-9]{64}", data["source_sha256"]):
        raise ValueError("Managed Python source SHA256 is invalid")
    if data["prefix"] != f"/opt/mds-python/{version}":
        raise ValueError("Managed Python prefix must be versioned under /opt/mds-python")
    return data


def supported_minors() -> list[int]:
    return json.loads((ROOT / "config/mavsdk-runtime.json").read_text())["python"]["supported_minors"]


def probe(executable: str | Path, modules: list[str] | None = None) -> dict:
    code = """import importlib,json,sys
for module in sys.argv[1:]: importlib.import_module(module)
print(json.dumps({'version':list(sys.version_info[:3]),
                 'base_executable':getattr(sys,'_base_executable',sys.executable)}))
"""
    completed = subprocess.run([str(executable), "-c", code, *(modules or [])],
                               capture_output=True, text=True, timeout=25, check=True)
    data = json.loads(completed.stdout)
    if data["version"][0] != 3 or data["version"][1] not in supported_minors():
        raise ValueError("Interpreter is outside the SDK-supported Python minors")
    return data


def select_python(venv: Path | None = None) -> str:
    manifest = load_manifest()
    minor = ".".join(manifest["version"].split(".")[:2])
    candidates = ([str(venv / "bin/python")] if venv else []) + [
        f"{manifest['prefix']}/bin/python{minor}", sys.executable,
        *(shutil.which(f"python3.{number}") for number in reversed(supported_minors())),
    ]
    for candidate in dict.fromkeys(candidates):
        if not candidate:
            continue
        try:
            data = probe(candidate, CORE_MODULES)
            # Do not return the venv executable: a broken venv may be replaced.
            base = data["base_executable"]
            probe(base, CORE_MODULES)
            return base
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    raise ValueError("No SDK-supported Python interpreter; rebuild the image with the managed Python runtime")


def check_venv(venv: Path, modules: list[str]) -> tuple[bool, str]:
    from check_runtime_venv import validate_venv
    try:
        probe(venv / "bin/python", CORE_MODULES)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False, "venv interpreter is unavailable, incomplete or outside the SDK-supported minors"
    return validate_venv(venv, modules)


def requirements_state(venv: Path, requirements: Path) -> str:
    runtime = probe(venv / "bin/python")
    version = ".".join(map(str, runtime["version"]))
    return f"{hashlib.sha256(requirements.read_bytes()).hexdigest()}|python={version}"


def run_bounded(command: list[str], *, cwd: Path | None = None, timeout: int = 120) -> None:
    process = subprocess.Popen(command, cwd=cwd, start_new_session=True, stdout=sys.stderr, stderr=sys.stderr)
    try:
        status = process.wait(timeout=timeout)
    except BaseException:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise
    if status:
        raise RuntimeError(f"Python provisioning step failed ({Path(command[0]).name}, status={status})")


def download_source(url: str, target: Path, expected: str) -> None:
    deadline = time.monotonic() + 180
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(url, timeout=20) as response, target.open("wb") as output:
        if response.geturl() != url:
            raise ValueError("Python source URL unexpectedly redirected")
        while True:
            chunk = response.read1(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > 40 * 1024 * 1024 or time.monotonic() > deadline:
                raise ValueError("Python source exceeded the bounded download budget")
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("Python source SHA256 does not match the pinned official release")


def extract_source(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:xz") as source:
        members = source.getmembers()
        if sum(max(0, item.size) for item in members) > 256 * 1024 * 1024:
            raise ValueError("Python source archive expands beyond its budget")
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or not (member.isfile() or member.isdir()):
                raise ValueError("Unexpected path/link in Python source archive")
        source.extractall(destination, members=members)


def provision_image() -> str:
    if not Path("/.dockerenv").is_file() or os.geteuid() != 0:
        raise ValueError("Managed Python provisioning is restricted to an owned root image-build container")
    data = load_manifest()
    prefix = Path(data["prefix"])
    minor = ".".join(data["version"].split(".")[:2])
    executable = prefix / f"bin/python{minor}"
    if executable.exists():
        if ".".join(map(str, probe(executable, CORE_MODULES)["version"])) != data["version"]:
            raise ValueError("Existing managed Python differs from the source manifest; preserve it for investigation")
        return str(executable)
    try:
        return select_python()
    except ValueError:
        pass
    if prefix.exists() or prefix.is_symlink():
        raise ValueError("Incomplete managed Python prefix exists; do not overwrite it implicitly")
    deps = ["build-essential", "libssl-dev", "zlib1g-dev", "libbz2-dev", "libreadline-dev",
            "libsqlite3-dev", "libffi-dev", "liblzma-dev", "libgdbm-dev", "libncurses-dev",
            "uuid-dev", "ca-certificates"]
    run_bounded(["apt-get", "update", "-qq"], timeout=180)
    run_bounded(["apt-get", "install", "-y", "--no-install-recommends", *deps], timeout=300)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mds-python-build-") as work_name, \
            tempfile.TemporaryDirectory(prefix=".install-", dir=prefix.parent) as stage_name:
        work, stage = Path(work_name), Path(stage_name)
        archive = work / "source.tar.xz"
        download_source(data["source_url"], archive, data["source_sha256"])
        extract_source(archive, work)
        source = work / f"Python-{data['version']}"
        # No PGO/LTO; bounded two-worker build leaves room for host services.
        run_bounded([str(source / "configure"), f"--prefix={prefix}", "--with-ensurepip=install",
                     "--disable-test-modules"], cwd=source, timeout=180)
        run_bounded(["make", "-j2"], cwd=source, timeout=1200)
        run_bounded(["make", "altinstall", f"DESTDIR={stage}"], cwd=source, timeout=180)
        staged = stage / prefix.relative_to("/")
        receipt = {**data, "source_verified": True, "configure_pgo": False, "build_workers": 2}
        (staged / "mds-python-provenance.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
        os.rename(staged, prefix)
    probe(executable, CORE_MODULES)
    return str(executable)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser("select")
    select.add_argument("--venv", type=Path)
    check = commands.add_parser("check-venv")
    check.add_argument("--venv", type=Path, required=True)
    check.add_argument("--module", action="append", default=[])
    state = commands.add_parser("state")
    state.add_argument("--venv", type=Path, required=True)
    state.add_argument("--requirements", type=Path, required=True)
    commands.add_parser("provision-image")
    args = parser.parse_args()
    try:
        if args.command == "select":
            print(select_python(args.venv))
        elif args.command == "check-venv":
            ok, message = check_venv(args.venv, args.module)
            print(message, file=sys.stdout if ok else sys.stderr)
            return 0 if ok else 1
        elif args.command == "state":
            print(requirements_state(args.venv, args.requirements))
        else:
            print(provision_image())
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Python runtime: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
