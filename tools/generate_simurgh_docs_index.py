#!/usr/bin/env python3
"""Generate the Simurgh public documentation search index.

The generator indexes only public resources from docs/agent-context/context-index.yaml.
Generated artifacts are skipped unless the context index marks a specific generated
reference as safe for search, so the index remains auditable and does not
recursively embed large machine-readable inventories.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTEXT_INDEX_PATH = REPO_ROOT / "docs" / "agent-context" / "context-index.yaml"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "docs" / "agent-context" / "generated" / "simurgh-docs-index.json"
GENERATOR_ID = "tools/generate_simurgh_docs_index.py"
MAX_CHUNK_CHARS = 2200
OVERLAP_CHARS = 240
SKIPPED_RESOURCE_IDS = {"simurgh.docs_index", "simurgh.openapi_tool_candidates"}
SKIPPED_TAGS = {"generated", "candidates", "evals"}
SKIPPED_PATH_PREFIXES = ("docs/agent-context/generated/", "docs/plans/")
SECRET_PATTERNS = (
    re.compile(r"sk-proj-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-or-v1-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+(?!\.{3}\b|<)[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(
        r"(?i)\b(?:api[_ -]?key|token|secret|password|netbird[_ -]?(?:setup[_ -]?)?key)"
        r"\s*[:=]\s*['\"]?(?!\.{3}\b|<|REDACTED\b|example\b|your\b|test\b)[A-Za-z0-9._~+/=-]{20,}"
    ),
)


@dataclass(frozen=True)
class SourceResource:
    id: str
    title: str
    path: Path
    mime_type: str
    audience: str
    sensitivity: str
    summary: str
    tags: tuple[str, ...]


def _stable_hash(text: str | bytes) -> str:
    data = text if isinstance(text, bytes) else text.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized[:80] or "section"


def _read_yaml(path: Path) -> Mapping[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, Mapping):
        raise SystemExit(f"{path} root must be an object")
    return payload


def _resource_from_mapping(payload: Mapping[str, Any]) -> SourceResource:
    tags = tuple(str(tag).strip() for tag in payload.get("tags") or () if str(tag).strip())
    return SourceResource(
        id=str(payload.get("id") or "").strip(),
        title=str(payload.get("title") or "").strip(),
        path=Path(str(payload.get("path") or "")),
        mime_type=str(payload.get("mime_type") or "text/markdown").strip(),
        audience=str(payload.get("audience") or "agent").strip(),
        sensitivity=str(payload.get("sensitivity") or "public").strip(),
        summary=str(payload.get("summary") or "").strip(),
        tags=tags,
    )


def _iter_source_resources(context_index_path: Path) -> Iterable[SourceResource]:
    payload = _read_yaml(context_index_path)
    raw_resources = payload.get("resources")
    if not isinstance(raw_resources, list):
        raise SystemExit("context index resources must be a list")
    for raw in raw_resources:
        if not isinstance(raw, Mapping):
            raise SystemExit("each context index resource must be an object")
        resource = _resource_from_mapping(raw)
        if not resource.id or not resource.title:
            raise SystemExit("context resource id/title are required")
        if resource.sensitivity != "public":
            continue
        docs_search_mode = str(raw.get("docs_search") or "").strip().lower()
        searchable = raw.get("searchable") is True or docs_search_mode == "include"
        if not searchable:
            continue
        generated_file = ".generated." in resource.path.name or resource.path.name.endswith(".generated")
        if generated_file and not (docs_search_mode == "include" and raw.get("generated_safe_for_search") is True):
            continue
        if resource.id in SKIPPED_RESOURCE_IDS:
            continue
        if SKIPPED_TAGS.intersection(resource.tags):
            continue
        resource_path_text = resource.path.as_posix()
        if any(resource_path_text.startswith(prefix) for prefix in SKIPPED_PATH_PREFIXES):
            continue
        if resource.path.is_absolute() or ".." in resource.path.parts:
            raise SystemExit(f"invalid context resource path: {resource.path}")
        full_path = (REPO_ROOT / resource.path).resolve()
        try:
            full_path.relative_to(REPO_ROOT)
        except ValueError as exc:
            raise SystemExit(f"resource escapes repository root: {resource.path}") from exc
        if not full_path.is_file():
            raise SystemExit(f"context resource is missing: {resource.path}")
        yield resource


def _contains_raw_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _markdown_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    current_heading = "Overview"
    current_lines: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if match:
            if current_lines:
                sections.append((current_heading, current_lines))
            current_heading = match.group(2).strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_heading, current_lines))
    return [(heading, _normalize_text("\n".join(lines))) for heading, lines in sections if _normalize_text("\n".join(lines))]


def _split_long_text(text: str, *, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    paragraphs = re.split(r"\n{2,}", text)
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        candidate = (current + "\n\n" + paragraph).strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > max_chars:
            head = paragraph[:max_chars]
            split_at = max(head.rfind(". "), head.rfind("\n"), head.rfind(" "))
            if split_at < max_chars // 2:
                split_at = max_chars
            chunks.append(paragraph[:split_at].strip())
            paragraph = paragraph[max(0, split_at - OVERLAP_CHARS):].strip()
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


def _extract_links(text: str) -> list[str]:
    links = set()
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
        target = match.group(1).strip()
        if target.startswith(("/", "docs/", "http://", "https://")):
            links.add(target)
    for match in re.finditer(r"(?<![\w/])(docs/[A-Za-z0-9_./#-]+)", text):
        links.add(match.group(1).rstrip(".,)"))
    return sorted(links)[:20]


def _route_hint(path: Path) -> str | None:
    mapping = {
        "docs/features/drone-show.md": "/manage-drone-show",
        "docs/features/swarm-trajectory.md": "/swarm-trajectory",
        "docs/quickscout.md": "/quickscout",
        "docs/guides/logging-system.md": "/logs",
        "docs/reference/mds-environment-registry.generated.md": "/environments",
        "docs/guides/simurgh-operator.md": "/simurgh",
        "docs/guides/simurgh-mcp-clients.md": "/simurgh",
        "docs/guides/fleet-ops.md": "/fleet-ops",
        "docs/guides/mds-init-setup.md": "/fleet-enrollment",
        "docs/guides/sitl-control.md": "/sitl-control",
    }
    return mapping.get(path.as_posix())


def build_index(context_index_path: Path = DEFAULT_CONTEXT_INDEX_PATH) -> dict[str, Any]:
    resources_payload: list[dict[str, Any]] = []
    chunks_payload: list[dict[str, Any]] = []

    for resource in _iter_source_resources(context_index_path):
        full_path = REPO_ROOT / resource.path
        text = _normalize_text(full_path.read_text(encoding="utf-8"))
        if _contains_raw_secret(text):
            raise SystemExit(f"refusing to index raw secret pattern in {resource.path}")
        source_hash = _stable_hash(text)
        sections = _markdown_sections(text) if resource.mime_type == "text/markdown" else [(resource.title, text)]
        resource_chunk_count = 0
        for section_index, (heading, section_text) in enumerate(sections, start=1):
            for part_index, chunk_text in enumerate(_split_long_text(section_text), start=1):
                chunk_id = f"{resource.id}:{section_index:03d}-{part_index:02d}-{_slug(heading)}"
                chunks_payload.append(
                    {
                        "id": chunk_id,
                        "resource_id": resource.id,
                        "title": resource.title,
                        "heading": heading,
                        "path": resource.path.as_posix(),
                        "route_hint": _route_hint(resource.path),
                        "audience": resource.audience,
                        "mime_type": resource.mime_type,
                        "summary": resource.summary,
                        "tags": list(resource.tags),
                        "text": chunk_text,
                        "links": _extract_links(chunk_text),
                        "canonical_url": f"/api/v1/simurgh/context/{resource.id}/markdown",
                        "content_hash": _stable_hash(chunk_text),
                    }
                )
                resource_chunk_count += 1
        resources_payload.append(
            {
                "id": resource.id,
                "title": resource.title,
                "path": resource.path.as_posix(),
                "route_hint": _route_hint(resource.path),
                "audience": resource.audience,
                "mime_type": resource.mime_type,
                "summary": resource.summary,
                "tags": list(resource.tags),
                "canonical_url": f"/api/v1/simurgh/context/{resource.id}/markdown",
                "content_hash": source_hash,
                "chunk_count": resource_chunk_count,
            }
        )

    return {
        "version": 1,
        "schema": "mds.simurgh.docs_index.v1",
        "generated_by": GENERATOR_ID,
        "source_context_index": context_index_path.relative_to(REPO_ROOT).as_posix(),
        "resource_count": len(resources_payload),
        "chunk_count": len(chunks_payload),
        "resources": resources_payload,
        "chunks": chunks_payload,
    }


def _json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-index", type=Path, default=DEFAULT_CONTEXT_INDEX_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--check", action="store_true", help="fail if the generated artifact is not current")
    args = parser.parse_args(argv)

    context_index = args.context_index if args.context_index.is_absolute() else REPO_ROOT / args.context_index
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    payload = build_index(context_index)
    rendered = _json_text(payload)

    if args.check:
        try:
            existing = output.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"missing generated docs index: {output.relative_to(REPO_ROOT)}", file=sys.stderr)
            return 1
        if existing != rendered:
            print(f"generated docs index is stale: {output.relative_to(REPO_ROOT)}", file=sys.stderr)
            return 1
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(f"wrote {output.relative_to(REPO_ROOT)} ({payload['chunk_count']} chunks)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
