#!/usr/bin/env python3
"""Validate that an MDS runtime virtual environment is internally consistent."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _read_cfg_version(pyvenv_cfg: Path) -> str | None:
    if not pyvenv_cfg.is_file():
        return None

    for raw_line in pyvenv_cfg.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("version ="):
            continue
        return line.split("=", 1)[1].strip()
    return None


def _runtime_metadata(venv_python: Path, modules: list[str]) -> dict:
    probe = """
import importlib
import json
import sys
import sysconfig

modules = sys.argv[1:]
failures = {}
for name in modules:
    try:
        importlib.import_module(name)
    except Exception as exc:  # pragma: no cover - surfaced via caller output
        failures[name] = f"{type(exc).__name__}: {exc}"

print(json.dumps({
    "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    "version_mm": f"{sys.version_info.major}.{sys.version_info.minor}",
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "executable": sys.executable,
    "purelib": sysconfig.get_paths().get("purelib", ""),
    "module_failures": failures,
}))
"""
    completed = subprocess.run(
        [str(venv_python), "-c", probe, *modules],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(stderr or "venv python probe failed")

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"invalid venv probe output: {exc}") from exc


def validate_venv(venv_dir: Path, modules: list[str]) -> tuple[bool, str]:
    pyvenv_cfg = venv_dir / "pyvenv.cfg"
    venv_python = venv_dir / "bin" / "python"

    if not venv_dir.is_dir():
        return False, f"venv directory missing: {venv_dir}"
    if not pyvenv_cfg.is_file():
        return False, f"pyvenv.cfg missing: {pyvenv_cfg}"
    if not venv_python.exists():
        return False, f"venv python missing: {venv_python}"

    cfg_version = _read_cfg_version(pyvenv_cfg)

    try:
        runtime = _runtime_metadata(venv_python, modules)
    except RuntimeError as exc:
        return False, str(exc)

    runtime_version = runtime["version"]
    runtime_version_mm = runtime["version_mm"]
    purelib = runtime["purelib"]

    if cfg_version is not None:
        cfg_version_mm = ".".join(cfg_version.split(".")[:2])
        if cfg_version_mm != runtime_version_mm:
            return (
                False,
                "venv interpreter version mismatch: "
                f"pyvenv.cfg={cfg_version_mm} runtime={runtime_version_mm}",
            )

    expected_prefix = str(venv_dir)
    if runtime["prefix"] != expected_prefix:
        return False, f"venv sys.prefix mismatch: expected {expected_prefix}, got {runtime['prefix']}"

    expected_purelib = venv_dir / "lib" / f"python{runtime_version_mm}" / "site-packages"
    if Path(purelib) != expected_purelib:
        return (
            False,
            "venv purelib mismatch: "
            f"expected {expected_purelib}, got {purelib}",
        )

    if not expected_purelib.is_dir():
        return False, f"venv site-packages missing: {expected_purelib}"

    if runtime["module_failures"]:
        failures = ", ".join(
            f"{name}={error}" for name, error in sorted(runtime["module_failures"].items())
        )
        return False, f"venv module import failure: {failures}"

    return True, (
        "ok "
        f"python={runtime_version} "
        f"prefix={runtime['prefix']} "
        f"purelib={purelib}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", required=True, help="Path to the virtual environment")
    parser.add_argument(
        "--module",
        action="append",
        default=[],
        help="Module that must import successfully inside the venv",
    )
    args = parser.parse_args()

    ok, message = validate_venv(Path(args.venv), args.module)
    stream = sys.stdout if ok else sys.stderr
    print(message, file=stream)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
