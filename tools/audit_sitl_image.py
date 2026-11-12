#!/usr/bin/env python3
"""Fail a SITL release on credential residue, without printing secret content.

This is a bounded filesystem/configuration gate, not an OS/package CVE scanner.
Virtual filesystems and binary contents are excluded; text is streamed in full.
Public test keys have exact path-suffix AND digest exceptions, never a directory
exemption. Any inaccessible file or exceeded time budget fails the gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

TOKEN = re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")
PRIVATE_KEY = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")
USERINFO = re.compile(rb"https?://[^\s/]+@", re.IGNORECASE)
VIRTUAL_ROOTS = {"proc", "sys", "dev"}
# Public fixtures shipped in future==1.0.0 and the unchanged base PX4 tree.
# The digest check prevents a real key placed at one of these paths passing.
PUBLIC_TEST_KEYS = {
    "future/backports/test/ssl_key.passwd.pem": "23f587e2c070f55b3d67e06f9ae5d8d1ac3cb71f1abefeab9b950be12fe93f4d",
    "future/backports/test/keycert.passwd.pem": "6417e754ba5b06d00e7ffda009d890fb2ac11e646c37349ff150b75294192238",
    "future/backports/test/badkey.pem": "81a04af69c7f806ec39ab2cac5f0fa7fa8beb6802601105355fb3e606151405d",
    "future/backports/test/keycert2.pem": "0c1e3a144018bfc056c1027ee51cc2ebde85c4f37b08e37e42c8be478a682607",
    "future/backports/test/badcert.pem": "262a107916641c7f211ac5898c0177535cd0bdc5aa872cc6e883842694d8f521",
    "future/backports/test/ssl_key.pem": "54a194f91dd461a6695535e5edc856978bc46040dea1bebd49fbd14d0f1aabfe",
    "future/backports/test/keycert.pem": "c4f5e2e6274f71055bae183106a1764cd1a6eac499d9a2d5544b7a0d6ce994bf",
    "PX4-Autopilot/Tools/test_keys/rsa2048.pem": "c18e97211d65b3caa6fa43c74937e213c8b6c700b3e8507cad862d48b0f585b4",
}


def public_test_key(path: Path) -> bool:
    for suffix, expected in PUBLIC_TEST_KEYS.items():
        if path.as_posix().endswith("/" + suffix):
            return hashlib.sha256(path.read_bytes()).hexdigest() == expected
    return False


def git_findings(repo: Path) -> list[dict]:
    result = subprocess.run(["git", "-C", str(repo), "config", "--local", "--list"],
                            capture_output=True, timeout=15, check=False)
    if result.returncode:
        raise ValueError("Cannot read the prepared repository's Git configuration")
    findings = []
    for line in result.stdout.splitlines():
        key, _, value = line.partition(b"=")
        if USERINFO.search(value) or TOKEN.search(value):
            findings.append({"kind": "git-embedded-credential", "path": ".git/config"})
        if (key.startswith(b"credential.") or key.endswith(b".extraheader")) and value:
            findings.append({"kind": "git-credential-directive", "path": ".git/config"})
        if key.startswith(b"include.") or key.startswith(b"includeif."):
            findings.append({"kind": "git-config-include", "path": ".git/config"})
    return findings


def config_findings(config: dict) -> list[dict]:
    findings = []
    for entry in config.get("Env") or []:
        key, _, value = entry.partition("=")
        sensitive = re.search(r"(?:TOKEN|PASSWORD|SECRET|API_KEY)$", key, re.IGNORECASE)
        if value and (sensitive or TOKEN.search(value.encode()) or USERINFO.search(value.encode())):
            findings.append({"kind": "image-environment-credential", "path": "Config.Env"})
    for key in ("Labels", "Cmd", "Entrypoint", "Healthcheck", "OnBuild"):
        content = json.dumps(config.get(key)).encode()
        if TOKEN.search(content) or USERINFO.search(content) or PRIVATE_KEY.search(content):
            findings.append({"kind": "image-metadata-credential", "path": f"Config.{key}"})
    return findings


def filesystem_findings(root: Path, *, seconds: float = 180) -> tuple[list[dict], dict]:
    root = root.resolve(strict=True)
    deadline = time.monotonic() + seconds
    findings, coverage = [], {"text_files": 0, "text_bytes": 0, "binary_files_excluded": 0,
                              "public_fixture_keys": 0, "virtual_roots_excluded": sorted(VIRTUAL_ROOTS)}

    def finding(kind: str, path: Path):
        # Even a secret used as a filename must not leak into the report.
        name = path.relative_to(root).as_posix()
        name = TOKEN.sub(b"[REDACTED]", name.encode()).decode(errors="replace")
        findings.append({"kind": kind, "path": name})

    def walk_error(error: OSError):
        raise ValueError("Filesystem scan could not inspect every in-scope path") from error

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        current = Path(directory)
        if current == root:
            dirs[:] = [name for name in dirs if name not in VIRTUAL_ROOTS]
        for name in files:
            if time.monotonic() > deadline:
                raise ValueError("Filesystem scan exceeded its time budget; no clean result")
            path = current / name
            details = path.lstat()
            relative = path.relative_to(root)
            if relative.parts[:2] == ("run", "secrets"):
                finding("staged-secret-path", path)
            if name in {".git-credentials", ".netrc", ".bash_history", ".zsh_history"}:
                finding("credential-or-history-file", path)
            if stat.S_ISLNK(details.st_mode):
                if ".ssh" in relative.parts and not name.endswith(".pub"):
                    finding("ssh-credential-symlink", path)
                continue
            if not stat.S_ISREG(details.st_mode):
                continue
            with path.open("rb") as handle:
                first = handle.read(4096)
                if b"\0" in first:
                    coverage["binary_files_excluded"] += 1
                    continue
                coverage["text_files"] += 1
                is_git_config = (name == ".gitconfig" or name == "config" and ".git" in relative.parts)
                tail = b""
                token_found = private_found = url_found = False
                chunk = first
                while chunk:
                    if time.monotonic() > deadline:
                        raise ValueError("Filesystem scan exceeded its time budget; no clean result")
                    coverage["text_bytes"] += len(chunk)
                    sample = tail + chunk
                    token_found |= bool(TOKEN.search(sample))
                    private_found |= bool(PRIVATE_KEY.search(sample))
                    url_found |= is_git_config and bool(USERINFO.search(sample))
                    tail = sample[-256:]
                    chunk = handle.read(64 * 1024)
            if token_found:
                finding("github-token", path)
            if url_found:
                finding("git-embedded-credential", path)
            if private_found:
                if public_test_key(path):
                    coverage["public_fixture_keys"] += 1
                else:
                    finding("private-key", path)
    return findings, coverage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["git", "filesystem", "config"])
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args()
    try:
        if args.command == "config":
            metadata = json.load(sys.stdin)
            findings, coverage = config_findings(metadata[0].get("Config") or {}), {}
        else:
            if args.repo is None:
                raise ValueError("A prepared repository is required")
            findings, coverage = git_findings(args.repo), {}
        if args.command == "filesystem":
            file_findings, coverage = filesystem_findings(args.root)
            findings.extend(file_findings)
        print(json.dumps({"ok": not findings, "findings": findings, "coverage": coverage}, sort_keys=True))
        return 1 if findings else 0
    except (OSError, ValueError, subprocess.SubprocessError):
        # OS/Git exceptions can contain URL content. Never echo their text.
        print("Image credential audit incomplete; inspect paths/configuration privately", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
