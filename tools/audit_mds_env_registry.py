#!/usr/bin/env python3
"""Audit active MDS_* environment references against the registry.

Every active MDS_* reference must be either:

- present in resources/config/mds_env_registry.json, or
- explicitly classified in resources/config/mds_env_internal_allowlist.json.

This keeps operator-facing configuration discoverable without forcing
process-only launcher/build/test variables into the dashboard env editor.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOWLIST_PATH = REPO_ROOT / "resources" / "config" / "mds_env_internal_allowlist.json"

ENV_KEY_RE = re.compile(r"\bMDS_[A-Z0-9](?:[A-Z0-9_]*[A-Z0-9])?\b")

DEFAULT_SCAN_ROOTS = (
    "app",
    "deployment",
    "gcs-server",
    "mds_logging",
    "multiple_sitl",
    "src",
    "tools",
)

ROOT_FILE_SUFFIXES = {".py", ".sh"}
IGNORED_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "coverage_html",
    "node_modules",
    "runtime_data",
    "temp",
}
IGNORED_FILE_NAMES = {
    "package-lock.json",
}
IGNORED_NAME_PARTS = (
    ".test.",
    ".spec.",
)


@dataclass(frozen=True)
class EnvReference:
    """Single active file/line reference to an MDS_* key."""

    path: Path
    line: int

    def display(self) -> str:
        return f"{self.path.as_posix()}:{self.line}"


@dataclass(frozen=True)
class InternalAllowlist:
    """Exact and wildcard allowlist for process-only MDS_* keys."""

    exact: frozenset[str] = frozenset()
    patterns: tuple[str, ...] = ()

    def matches(self, key: str) -> bool:
        return key in self.exact or any(fnmatch.fnmatchcase(key, pattern) for pattern in self.patterns)


@dataclass
class EnvAuditResult:
    """Classification result for active MDS_* references."""

    registered: dict[str, list[EnvReference]] = field(default_factory=dict)
    internal: dict[str, list[EnvReference]] = field(default_factory=dict)
    unclassified: dict[str, list[EnvReference]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.unclassified

    @property
    def reference_count(self) -> int:
        return (
            sum(len(refs) for refs in self.registered.values())
            + sum(len(refs) for refs in self.internal.values())
            + sum(len(refs) for refs in self.unclassified.values())
        )


def _load_registry_keys(registry_path: Path | None = None) -> set[str]:
    if registry_path is None:
        sys.path.insert(0, str(REPO_ROOT))
        from src.settings.env_registry import load_env_registry

        return set(load_env_registry().entries)

    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"{registry_path}: entries must be a list")
    return {str(entry["name"]) for entry in entries if isinstance(entry, dict) and "name" in entry}


def load_internal_allowlist(path: Path = DEFAULT_ALLOWLIST_PATH) -> InternalAllowlist:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if int(raw.get("version", 0)) < 1:
        raise ValueError(f"{path}: version must be >= 1")

    exact: set[str] = set()
    patterns: list[str] = []

    for item in raw.get("keys") or []:
        name = str(item.get("name", "")).strip()
        if not ENV_KEY_RE.fullmatch(name):
            raise ValueError(f"{path}: invalid allowlist key {name!r}")
        exact.add(name)

    for item in raw.get("rules") or []:
        pattern = str(item.get("pattern", "")).strip()
        if not pattern.startswith("MDS_") or "*" not in pattern:
            raise ValueError(f"{path}: invalid allowlist pattern {pattern!r}")
        patterns.append(pattern)

    return InternalAllowlist(exact=frozenset(exact), patterns=tuple(patterns))


def _is_ignored_path(path: str | Path) -> bool:
    path = Path(path)
    parts = set(path.parts)
    if parts & IGNORED_DIRS:
        return True
    if path.name in IGNORED_FILE_NAMES:
        return True
    if any(part in path.name for part in IGNORED_NAME_PARTS):
        return True
    return False


def _iter_scan_files(scan_roots: Iterable[str | Path]) -> Iterable[Path]:
    for raw_root in scan_roots:
        root = Path(raw_root)
        if not root.is_absolute():
            root = REPO_ROOT / root
        if not root.exists():
            continue
        if root.is_file():
            candidates = [root]
        else:
            candidates = root.rglob("*")

        for path in candidates:
            if not path.is_file() or _is_ignored_path(path.relative_to(REPO_ROOT)):
                continue
            yield path

    for path in REPO_ROOT.iterdir():
        if path.is_file() and path.suffix in ROOT_FILE_SUFFIXES and not _is_ignored_path(path.name):
            yield path


def collect_mds_env_references(scan_roots: Iterable[str | Path] = DEFAULT_SCAN_ROOTS) -> dict[str, list[EnvReference]]:
    references: dict[str, list[EnvReference]] = {}
    seen_files: set[Path] = set()

    for path in _iter_scan_files(scan_roots):
        path = path.resolve()
        if path in seen_files:
            continue
        seen_files.add(path)
        relative_path = path.relative_to(REPO_ROOT)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            for key in sorted(set(ENV_KEY_RE.findall(line))):
                references.setdefault(key, []).append(EnvReference(path=relative_path, line=line_number))

    return references


def audit_mds_env_references(
    *,
    registry_path: Path | None = None,
    allowlist_path: Path = DEFAULT_ALLOWLIST_PATH,
    scan_roots: Iterable[str | Path] = DEFAULT_SCAN_ROOTS,
) -> EnvAuditResult:
    registry_keys = _load_registry_keys(registry_path)
    allowlist = load_internal_allowlist(allowlist_path)
    references = collect_mds_env_references(scan_roots)
    result = EnvAuditResult()

    for key, refs in sorted(references.items()):
        if key in registry_keys:
            result.registered[key] = refs
        elif allowlist.matches(key):
            result.internal[key] = refs
        else:
            result.unclassified[key] = refs

    return result


def _format_result(result: EnvAuditResult) -> str:
    lines = [
        "MDS env registry audit",
        f"  registered keys : {len(result.registered)}",
        f"  internal keys   : {len(result.internal)}",
        f"  unclassified   : {len(result.unclassified)}",
        f"  active refs     : {result.reference_count}",
    ]
    if result.unclassified:
        lines.append("")
        lines.append("Unclassified active MDS_* keys:")
        for key, refs in sorted(result.unclassified.items()):
            examples = ", ".join(ref.display() for ref in refs[:5])
            suffix = "" if len(refs) <= 5 else f", +{len(refs) - 5} more"
            lines.append(f"  - {key}: {examples}{suffix}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable summary")
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST_PATH,
        help="internal allowlist JSON path",
    )
    args = parser.parse_args(argv)

    result = audit_mds_env_references(allowlist_path=args.allowlist)
    if args.json:
        payload = {
            "passed": result.passed,
            "registered_keys": sorted(result.registered),
            "internal_keys": sorted(result.internal),
            "unclassified_keys": sorted(result.unclassified),
            "reference_count": result.reference_count,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_format_result(result))

    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
