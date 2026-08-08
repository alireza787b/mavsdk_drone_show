#!/usr/bin/env python3
"""Package and verify a dashboard build with exact, non-secret provenance."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path


MANIFEST_NAME = "mds-dashboard-build-manifest.json"
ARTIFACT_TYPE = "mds-dashboard-build"
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
BUILD_ENV_DEFAULTS = {
    "DASHBOARD_BUILD_GCS_PORT": "5030",
    "DASHBOARD_BUILD_DRONE_PORT": "7070",
    "DASHBOARD_BUILD_SERVER_URL": "",
    "DASHBOARD_BUILD_MAPBOX_ACCESS_TOKEN": "",
    "DASHBOARD_BUILD_MAPBOX_TOKEN": "",
    "DASHBOARD_BUILD_MAP_TOKEN": "",
    "DASHBOARD_BUILD_SOURCE_MAPS": "false",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_tree_digest(build_root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    file_count = 0
    for path in sorted(build_root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"dashboard build must not contain symbolic links: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(build_root).as_posix()
        if relative == MANIFEST_NAME:
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
        file_count += 1
    return digest.hexdigest(), file_count


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise ValueError(f"{label} is missing: {path}")
    return path


def normalized_text(path: Path, label: str) -> str:
    value = require_file(path, label).read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"{label} is empty: {path}")
    return value


def build_environment_value(name: str) -> str:
    return os.environ.get(name, BUILD_ENV_DEFAULTS[name])


def build_environment_flag(name: str) -> bool:
    value = build_environment_value(name).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value, got {value!r}")


def build_environment_port(name: str) -> str:
    value = build_environment_value(name).strip()
    if not value.isdigit() or not 1 <= int(value) <= 65535:
        raise ValueError(f"{name} must be a TCP port in 1..65535, got {value!r}")
    return value


def compile_inputs_from_environment() -> dict[str, object]:
    server_url = build_environment_value("DASHBOARD_BUILD_SERVER_URL").strip()
    mapbox_values = (
        build_environment_value("DASHBOARD_BUILD_MAPBOX_ACCESS_TOKEN"),
        build_environment_value("DASHBOARD_BUILD_MAPBOX_TOKEN"),
        build_environment_value("DASHBOARD_BUILD_MAP_TOKEN"),
    )
    return {
        "gcs_port": build_environment_port("DASHBOARD_BUILD_GCS_PORT"),
        "drone_port": build_environment_port("DASHBOARD_BUILD_DRONE_PORT"),
        "server_url_mode": "explicit" if server_url else "browser_auto_detect",
        "mapbox_access_token_embedded": any(value.strip() for value in mapbox_values),
        "source_maps": build_environment_flag("DASHBOARD_BUILD_SOURCE_MAPS"),
    }


def write_manifest(args: argparse.Namespace) -> Path:
    if args.build_dir.is_symlink():
        raise ValueError(
            f"dashboard build directory must not be a symbolic link: {args.build_dir}"
        )
    build_dir = args.build_dir.resolve()
    if not build_dir.is_dir():
        raise ValueError(f"dashboard build directory is missing: {build_dir}")
    if not COMMIT_RE.fullmatch(args.commit):
        raise ValueError("commit must be one full 40-character hexadecimal Git SHA")

    required = {
        "package_lock_sha256": require_file(args.package_lock.resolve(), "package lock"),
        "asset_manifest_sha256": require_file(
            build_dir / "asset-manifest.json", "dashboard asset manifest"
        ),
        "index_sha256": require_file(build_dir / "index.html", "dashboard index"),
    }
    tree_sha256, file_count = build_tree_digest(build_dir)
    manifest = {
        "schema_version": 1,
        "artifact_type": ARTIFACT_TYPE,
        "source": {
            "repository": args.repository,
            "commit": args.commit.lower(),
            "ref": args.ref,
            "ref_name": args.ref_name,
            "display_ref": args.display_ref,
        },
        "product_version": normalized_text(args.version_file.resolve(), "VERSION"),
        "build": {
            **{name: sha256_file(path) for name, path in required.items()},
            "tree_sha256": tree_sha256,
            "file_count": file_count,
            "compile_inputs": compile_inputs_from_environment(),
        },
        "ci": {
            "provider": "github-actions",
            "run_id": args.run_id,
            "run_attempt": args.run_attempt,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    manifest_path = build_dir / MANIFEST_NAME
    if manifest_path.is_symlink():
        raise ValueError(
            f"dashboard build manifest must not be a symbolic link: {manifest_path}"
        )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def normalized_tar_info(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


def write_archive(build_dir: Path, output_dir: Path, commit: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"dashboard-build-{commit.lower()}.tar.gz"
    with archive.open("wb") as raw_archive:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_archive, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as bundle:
                bundle.add(build_dir, arcname="build", filter=normalized_tar_info)

    checksum_file = output_dir / "SHA256SUMS"
    checksum_file.write_text(
        f"{sha256_file(archive)}  {archive.name}\n", encoding="utf-8"
    )
    return archive, checksum_file


def require_nonempty(args: argparse.Namespace, names: tuple[str, ...]) -> None:
    for name in names:
        if not str(getattr(args, name)).strip():
            raise ValueError(f"{name.replace('_', '-')} must not be empty")


def expected_compile_inputs(gcs_port: str, drone_port: str) -> dict[str, object]:
    for label, value in (("gcs-port", gcs_port), ("drone-port", drone_port)):
        if not value.isdigit() or not 1 <= int(value) <= 65535:
            raise ValueError(f"{label} must be a TCP port in 1..65535, got {value!r}")
    return {
        "gcs_port": gcs_port,
        "drone_port": drone_port,
        "server_url_mode": "browser_auto_detect",
        "mapbox_access_token_embedded": False,
        "source_maps": False,
    }


def verify_manifest(args: argparse.Namespace) -> dict[str, object]:
    if args.build_dir.is_symlink():
        raise ValueError(
            f"dashboard build directory must not be a symbolic link: {args.build_dir}"
        )
    build_dir = args.build_dir.resolve()
    if not build_dir.is_dir():
        raise ValueError(f"dashboard build directory is missing: {build_dir}")
    if not COMMIT_RE.fullmatch(args.commit):
        raise ValueError("commit must be one full 40-character hexadecimal Git SHA")

    manifest_path = build_dir / MANIFEST_NAME
    if manifest_path.is_symlink():
        raise ValueError(
            f"dashboard build manifest must not be a symbolic link: {manifest_path}"
        )
    try:
        manifest = json.loads(
            require_file(manifest_path, "dashboard build manifest").read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"dashboard build manifest is invalid JSON: {exc}") from exc

    if not isinstance(manifest, dict):
        raise ValueError("dashboard build manifest root must be an object")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("artifact_type") != ARTIFACT_TYPE
    ):
        raise ValueError("unsupported dashboard artifact manifest schema or type")

    source = manifest.get("source")
    build = manifest.get("build")
    ci = manifest.get("ci")
    if (
        not isinstance(source, dict)
        or not isinstance(build, dict)
        or not isinstance(ci, dict)
    ):
        raise ValueError("dashboard artifact manifest is missing source/build/ci records")
    if not str(source.get("display_ref", "")).strip():
        raise ValueError("dashboard artifact manifest has no display ref")
    if ci.get("provider") != "github-actions" or any(
        not str(ci.get(name, "")).strip()
        for name in ("run_id", "run_attempt", "created_at")
    ):
        raise ValueError("dashboard artifact manifest has incomplete CI metadata")

    expected_source = {
        "repository": args.repository,
        "commit": args.commit.lower(),
        "ref": args.ref,
        "ref_name": args.ref_name,
    }
    for key, expected in expected_source.items():
        observed = source.get(key)
        matches = observed == expected
        if key == "repository" and isinstance(observed, str):
            matches = observed.casefold() == expected.casefold()
        if not matches:
            raise ValueError(
                f"source {key} mismatch: expected {expected!r}, observed {observed!r}"
            )

    expected_version = normalized_text(args.version_file.resolve(), "VERSION")
    if manifest.get("product_version") != expected_version:
        raise ValueError(
            "product version mismatch: "
            f"expected {expected_version!r}, observed {manifest.get('product_version')!r}"
        )

    required_hashes = {
        "package_lock_sha256": require_file(
            args.package_lock.resolve(), "package lock"
        ),
        "asset_manifest_sha256": require_file(
            build_dir / "asset-manifest.json", "dashboard asset manifest"
        ),
        "index_sha256": require_file(build_dir / "index.html", "dashboard index"),
    }
    for key, path in required_hashes.items():
        observed = sha256_file(path)
        if build.get(key) != observed:
            raise ValueError(f"{key} mismatch for {path.name}")

    tree_sha256, file_count = build_tree_digest(build_dir)
    if build.get("tree_sha256") != tree_sha256:
        raise ValueError("tree_sha256 mismatch for dashboard build contents")
    if build.get("file_count") != file_count:
        raise ValueError(
            "dashboard build file-count mismatch: "
            f"expected {build.get('file_count')!r}, observed {file_count!r}"
        )

    compile_inputs = expected_compile_inputs(args.gcs_port, args.drone_port)
    if build.get("compile_inputs") != compile_inputs:
        raise ValueError(
            "dashboard compile-input profile mismatch: "
            f"expected {compile_inputs!r}, observed {build.get('compile_inputs')!r}"
        )

    return {
        "manifest": str(manifest_path),
        "repository": source["repository"],
        "commit": source["commit"],
        "ref_name": source["ref_name"],
        "tree_sha256": tree_sha256,
        "file_count": file_count,
    }


def add_provenance_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--package-lock", type=Path, required=True)
    parser.add_argument("--version-file", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--ref-name", required=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    package_parser = subparsers.add_parser(
        "package", help="write a manifest and normalized deployment archive"
    )
    add_provenance_arguments(package_parser)
    package_parser.add_argument("--display-ref", required=True)
    package_parser.add_argument("--run-id", required=True)
    package_parser.add_argument("--run-attempt", required=True)
    package_parser.add_argument("--output-dir", type=Path, required=True)

    verify_parser = subparsers.add_parser(
        "verify", help="verify an extracted build against expected checkout provenance"
    )
    add_provenance_arguments(verify_parser)
    verify_parser.add_argument("--gcs-port", required=True)
    verify_parser.add_argument("--drone-port", required=True)
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, object]:
    require_nonempty(args, ("repository", "ref", "ref_name"))
    if args.command == "verify":
        return verify_manifest(args)

    require_nonempty(args, ("display_ref", "run_id", "run_attempt"))
    build_dir = args.build_dir.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir == build_dir or build_dir in output_dir.parents:
        raise ValueError("output directory must be outside the dashboard build tree")
    manifest_path = write_manifest(args)
    archive, checksum_file = write_archive(
        build_dir, output_dir, args.commit
    )
    return {
        "manifest": str(manifest_path),
        "archive": str(archive),
        "checksums": str(checksum_file),
        "archive_sha256": sha256_file(archive),
    }


def main() -> int:
    args = parse_args()
    try:
        report = run(args)
    except (OSError, ValueError) as exc:
        print(f"dashboard artifact error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
