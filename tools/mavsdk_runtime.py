#!/usr/bin/env python3
"""Inspect/provision the manifest-pinned MAVSDK server, without vehicle access."""
from __future__ import annotations

import argparse
import fcntl
from importlib.metadata import PackageNotFoundError
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.mavsdk_runtime import (load_manifest, manifest_digest, platform_asset, require_idle,
                               sha256_file, verify_elf, verify_help, verify_python, verify_python_platform)

MAX_DOWNLOAD_BYTES = 96 * 1024 * 1024
MAX_BACKUPS_BYTES = 192 * 1024 * 1024


def write_json(path: Path, value: dict) -> None:
    descriptor, filename = tempfile.mkstemp(prefix=".provenance-", dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def download(url: str, path: Path) -> None:
    if not url.startswith("https://"):
        raise ValueError("MAVSDK download URL must use HTTPS")
    deadline = time.monotonic() + 120
    request = urllib.request.Request(url, headers={"User-Agent": "MDS-pinned-MAVSDK"})
    with urllib.request.urlopen(request, timeout=20) as response, path.open("wb") as target:
        total = 0
        # read1 returns after one socket read. A full-size read can otherwise
        # keep waiting indefinitely while a peer trickles bytes below the
        # socket idle timeout, defeating an overall transfer budget.
        while True:
            if time.monotonic() > deadline:
                raise ValueError("MAVSDK download exceeded the bounded size/time budget")
            chunk = response.read1(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES or time.monotonic() > deadline:
                raise ValueError("MAVSDK download exceeded the bounded size/time budget")
            target.write(chunk)
        target.flush()
        os.fsync(target.fileno())


def provision(destination: Path, *, version: str | None = None, url: str | None = None) -> dict:
    manifest = load_manifest()
    machine, asset = platform_asset(manifest)
    version = version or manifest["server"]["version"]
    version = version if version.startswith("v") else f"v{version}"
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9.-]+)?", version):
        raise ValueError("MAVSDK version must be an explicit release tag; automatic latest is not supported")
    custom = bool(url) or version != manifest["server"]["version"]
    source = url or f"https://github.com/mavlink/MAVSDK/releases/download/{version}/{asset['name']}"
    if destination.is_symlink():
        raise ValueError("MAVSDK destination is a symlink; preserve/resolve its ownership explicitly before provisioning")
    destination = destination.parent.resolve() / destination.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    state = destination.parent / "runtime_data/mavsdk"
    state.mkdir(parents=True, exist_ok=True)
    with (state / "install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _provision_locked(destination, state, manifest, machine, asset, version, source, custom)


def _provision_locked(destination, state, manifest, machine, asset, version, source, custom):
    provenance_path = state / "provenance.json"
    existing_hash = sha256_file(destination) if destination.is_file() else None
    if not custom and existing_hash == asset["sha256"]:
        verify_elf(destination, asset)
        destination.chmod(0o755)
        verify_help(destination)
        result = receipt(manifest, machine, asset, existing_hash, version, custom)
        write_json(provenance_path, result)
        return result

    # Check before even downloading; check again just before activation.
    require_idle(destination.parent)
    descriptor, filename = tempfile.mkstemp(prefix=".mavsdk-candidate-", dir=destination.parent)
    os.close(descriptor)
    candidate = Path(filename)
    try:
        download(source, candidate)
        digest = sha256_file(candidate)
        if not custom and digest != asset["sha256"]:
            raise ValueError("MAVSDK download SHA256 does not match the published pinned release")
        verify_elf(candidate, asset)
        candidate.chmod(0o755)
        verify_help(candidate)
        result = receipt(manifest, machine, asset, digest, version, custom)
        require_idle(destination.parent)
        backups = state / "rollback"
        backups.mkdir(exist_ok=True)
        old_provenance = provenance_path.read_bytes() if provenance_path.exists() else None
        previous = None
        if existing_hash:
            previous = backups / f"mavsdk_server-{existing_hash}"
            if not previous.exists():
                retained = sum(item.stat().st_size for item in backups.iterdir() if item.is_file())
                if retained + destination.stat().st_size > MAX_BACKUPS_BYTES:
                    raise ValueError("MAVSDK rollback storage is full; archive reviewed old artifacts before retrying")
                # Same-filesystem hardlink preserves the working inode, without
                # copying tens of MB or changing an existing process's mapping.
                os.link(destination, previous)
            if old_provenance is not None:
                previous.with_suffix(".json").write_bytes(old_provenance)
        # A single rename is the activation point. Never unlink the old binary first.
        os.replace(candidate, destination)
        try:
            write_json(provenance_path, result)
        except Exception:
            if previous:
                os.link(previous, candidate)
                os.replace(candidate, destination)
            else:
                destination.unlink(missing_ok=True)
            raise
        return result
    finally:
        candidate.unlink(missing_ok=True)


def receipt(manifest, machine, asset, digest, requested, custom):
    matches = digest == asset["sha256"]
    return {"schema_version": 1, "timestamp": time.time(), "platform": machine,
            "manifest_sha256": manifest_digest(), "sha256": digest,
            "requested_version": requested, "custom_override": custom,
            "verified_server_version": manifest["server"]["version"] if matches else None,
            "compatibility": "pinned" if matches and not custom else "custom_pinned_bytes" if matches else "custom_unverified",
            "python": manifest["python"], "elf_verified": True, "help_verified": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["install", "check", "python-check", "python-platform", "idle", "manifest"])
    parser.add_argument("--install-dir", type=Path, default=Path(os.environ.get("MDS_INSTALL_DIR", Path(__file__).resolve().parents[1])))
    parser.add_argument("--version", default=os.environ.get("MDS_MAVSDK_VERSION"))
    parser.add_argument("--url", default=os.environ.get("MDS_MAVSDK_URL"))
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest()
        if args.command == "install":
            result = provision(args.install_dir / "mavsdk_server", version=args.version, url=args.url)
            if result["custom_override"]:
                print(f"WARNING: Explicit MAVSDK override: {result['compatibility']}; this is not the default reviewed installation", file=sys.stderr)
        elif args.command == "python-check":
            result = verify_python(manifest)
        elif args.command == "python-platform":
            result = verify_python_platform(manifest)
        elif args.command == "idle":
            require_idle(args.install_dir)
            result = {"idle": True}
        elif args.command == "manifest":
            result = manifest
        else:
            machine, asset = platform_asset(manifest)
            binary = args.install_dir / "mavsdk_server"
            verify_elf(binary, asset)
            digest = sha256_file(binary)
            if digest != asset["sha256"]:
                raise ValueError("Installed MAVSDK server does not match the pinned release; custom/unverified or upgrade required")
            verify_help(binary)
            result = receipt(manifest, machine, asset, digest, manifest["server"]["version"], False)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        # Never echo an override URL (it may contain deployment credentials).
        message = str(exc) if isinstance(exc, (ValueError, PackageNotFoundError)) else type(exc).__name__
        print(f"MAVSDK runtime check failed: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
