"""Generated public documentation index search for Simurgh tools."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .models import AgentRuntimeError


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOCS_INDEX_PATH = REPO_ROOT / "docs" / "agent-context" / "generated" / "simurgh-docs-index.json"
DOCS_INDEX_ENV = "MDS_AGENT_DOCS_INDEX_FILE"
DEFAULT_SEARCH_LIMIT = 5
MAX_SEARCH_LIMIT = 8
DEFAULT_READ_MAX_CHARS = 4000
MAX_READ_MAX_CHARS = 8000
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "can", "do", "for", "from", "give", "have", "how", "i", "in",
    "is", "it", "link", "me", "of", "on", "or", "read", "setup", "the", "there", "to", "we", "what", "where",
    "with", "you", "your",
}


@dataclass(frozen=True)
class DocsChunk:
    id: str
    resource_id: str
    title: str
    heading: str
    path: str
    route_hint: str | None
    audience: str
    mime_type: str
    summary: str
    tags: tuple[str, ...]
    text: str
    links: tuple[str, ...]
    canonical_url: str
    content_hash: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DocsChunk":
        chunk = cls(
            id=str(payload.get("id") or "").strip(),
            resource_id=str(payload.get("resource_id") or "").strip(),
            title=str(payload.get("title") or "").strip(),
            heading=str(payload.get("heading") or "").strip(),
            path=str(payload.get("path") or "").strip(),
            route_hint=str(payload.get("route_hint") or "").strip() or None,
            audience=str(payload.get("audience") or "agent").strip(),
            mime_type=str(payload.get("mime_type") or "text/markdown").strip(),
            summary=str(payload.get("summary") or "").strip(),
            tags=tuple(str(tag).strip() for tag in payload.get("tags") or () if str(tag).strip()),
            text=str(payload.get("text") or "").strip(),
            links=tuple(str(link).strip() for link in payload.get("links") or () if str(link).strip()),
            canonical_url=str(payload.get("canonical_url") or "").strip(),
            content_hash=str(payload.get("content_hash") or "").strip(),
        )
        chunk.validate()
        return chunk

    def validate(self) -> None:
        if not self.id or not re.fullmatch(r"[A-Za-z0-9_.:-]+", self.id):
            raise AgentRuntimeError("docs index chunk id is invalid")
        if not self.resource_id or not self.title or not self.path or not self.text:
            raise AgentRuntimeError(f"docs index chunk {self.id} is missing required fields")
        path = Path(self.path)
        if path.is_absolute() or ".." in path.parts:
            raise AgentRuntimeError(f"docs index chunk {self.id} has invalid path")

    def public_payload(self, *, include_text: bool = False, snippet: str | None = None, score: float | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "resource_id": self.resource_id,
            "title": self.title,
            "heading": self.heading,
            "path": self.path,
            "route_hint": self.route_hint,
            "audience": self.audience,
            "summary": self.summary,
            "tags": list(self.tags),
            "links": list(self.links),
            "canonical_url": self.canonical_url,
            "content_hash": self.content_hash,
        }
        if snippet is not None:
            payload["snippet"] = snippet
        if score is not None:
            payload["score"] = round(float(score), 3)
        if include_text:
            payload["text"] = self.text
        return payload


@dataclass(frozen=True)
class GeneratedDocsIndex:
    version: int
    path: Path
    source_context_index: str
    resources: tuple[dict[str, Any], ...]
    chunks: tuple[DocsChunk, ...]

    @classmethod
    def from_file(cls, path: str | Path = DEFAULT_DOCS_INDEX_PATH) -> "GeneratedDocsIndex":
        index_path = Path(path)
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AgentRuntimeError(f"generated docs index not found: {index_path}") from exc
        except json.JSONDecodeError as exc:
            raise AgentRuntimeError(f"generated docs index is invalid JSON: {index_path}") from exc
        if not isinstance(payload, Mapping):
            raise AgentRuntimeError("generated docs index root must be an object")
        return cls.from_mapping(payload, path=index_path)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, path: Path | None = None) -> "GeneratedDocsIndex":
        version = int(payload.get("version") or 0)
        if version != 1:
            raise AgentRuntimeError("generated docs index version must be 1")
        chunks_raw = payload.get("chunks")
        resources_raw = payload.get("resources")
        if not isinstance(chunks_raw, list) or not isinstance(resources_raw, list):
            raise AgentRuntimeError("generated docs index must contain resources and chunks lists")
        chunks = tuple(DocsChunk.from_mapping(item) for item in chunks_raw if isinstance(item, Mapping))
        if len(chunks) != len(chunks_raw):
            raise AgentRuntimeError("each generated docs chunk must be an object")
        return cls(
            version=version,
            path=path or DEFAULT_DOCS_INDEX_PATH,
            source_context_index=str(payload.get("source_context_index") or ""),
            resources=tuple(dict(item) for item in resources_raw if isinstance(item, Mapping)),
            chunks=chunks,
        )

    def chunk_by_id(self, chunk_id: str) -> DocsChunk:
        for chunk in self.chunks:
            if chunk.id == chunk_id:
                return chunk
        raise KeyError(f"unknown generated docs chunk: {chunk_id}")

    def search(self, query: str, *, limit: int = DEFAULT_SEARCH_LIMIT, tags: tuple[str, ...] = (), audience: str = "") -> list[tuple[DocsChunk, float, str]]:
        query = str(query or "").strip()
        terms = _query_terms(query)
        if not terms:
            raise AgentRuntimeError("docs search query must include at least one searchable term")
        limit = max(1, min(int(limit or DEFAULT_SEARCH_LIMIT), MAX_SEARCH_LIMIT))
        required_tags = {tag.lower() for tag in tags if tag}
        audience_filter = str(audience or "").strip().lower()
        scored: list[tuple[DocsChunk, float, str]] = []
        for chunk in self.chunks:
            if audience_filter and chunk.audience.lower() != audience_filter:
                continue
            if required_tags and not required_tags.issubset({tag.lower() for tag in chunk.tags}):
                continue
            score = _score_chunk(chunk, query=query, terms=terms)
            if score <= 0:
                continue
            scored.append((chunk, score, _snippet(chunk.text, terms)))
        scored.sort(key=lambda item: (-item[1], item[0].path, item[0].id))
        return scored[:limit]


def _default_index_path() -> Path:
    raw = os.environ.get(DOCS_INDEX_ENV)
    if not raw:
        return DEFAULT_DOCS_INDEX_PATH
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def load_default_docs_index() -> GeneratedDocsIndex:
    return GeneratedDocsIndex.from_file(_default_index_path())


def build_docs_search_payload(
    query: str,
    *,
    limit: int = DEFAULT_SEARCH_LIMIT,
    tags: str | tuple[str, ...] = (),
    audience: str = "",
) -> dict[str, Any]:
    parsed_tags = _parse_tags(tags)
    audience = str(audience or "").strip().lower()
    if audience and audience not in {"agent", "operator", "developer"}:
        raise AgentRuntimeError("docs search audience must be agent, operator, or developer")
    index = load_default_docs_index()
    from .retrieval import LexicalDocsRetriever, RetrievalQuery

    results = LexicalDocsRetriever(index=index).search(
        RetrievalQuery(text=query, limit=limit, tags=parsed_tags, audience=audience)
    )
    return {
        "query": str(query or "").strip(),
        "limit": max(1, min(int(limit or DEFAULT_SEARCH_LIMIT), MAX_SEARCH_LIMIT)),
        "tags": list(parsed_tags),
        "audience": audience or None,
        "source_context_index": index.source_context_index,
        "index_path": _display_path(index.path),
        "resource_count": len(index.resources),
        "chunk_count": len(index.chunks),
        "results": [hit.chunk.public_payload(snippet=hit.snippet, score=hit.score) for hit in results],
    }


def format_docs_search_payload(payload: Mapping[str, Any]) -> str:
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    lines = [f"MDS docs search results for: {payload.get('query')}"]
    if payload.get("tags"):
        lines.append("Tag filter: " + ", ".join(str(tag) for tag in payload.get("tags") or ()))
    if not results:
        lines.append("No public indexed docs matched that query. Try fewer words or ask a narrower MDS topic.")
    for index, item in enumerate(results, start=1):
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "")
        route = str(item.get("route_hint") or "")
        canonical = str(item.get("canonical_url") or "")
        heading = str(item.get("heading") or "")
        title = str(item.get("title") or "")
        lines.append(f"{index}. {title} - {heading}")
        lines.append(f"   Path: {path}" + (f" | Dashboard: {route}" if route else "") + (f" | Source: {canonical}" if canonical else ""))
        lines.append(f"   Chunk: `{item.get('id')}`")
        snippet = str(item.get("snippet") or "").strip()
        if snippet:
            lines.append(f"   {snippet}")
    lines.append("This is public documentation retrieval only; no GCS mutation or drone command was sent.")
    return "\n".join(lines)


def build_docs_chunk_payload(chunk_id: str, *, max_chars: int = DEFAULT_READ_MAX_CHARS) -> dict[str, Any]:
    chunk_id = str(chunk_id or "").strip()
    if not chunk_id:
        raise AgentRuntimeError("docs chunk id is required")
    max_chars = max(1, min(int(max_chars or DEFAULT_READ_MAX_CHARS), MAX_READ_MAX_CHARS))
    index = load_default_docs_index()
    chunk = index.chunk_by_id(chunk_id)
    text = chunk.text
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + "\n...[truncated by Simurgh docs read limit]"
    return {
        "chunk": chunk.public_payload(include_text=False),
        "text": text,
        "truncated": truncated,
        "max_chars": max_chars,
        "index_path": _display_path(index.path),
    }


def format_docs_chunk_payload(payload: Mapping[str, Any]) -> str:
    chunk = payload.get("chunk") if isinstance(payload.get("chunk"), Mapping) else {}
    lines = [
        f"{chunk.get('title')} - {chunk.get('heading')}",
        f"Path: {chunk.get('path')}" + (f" | Dashboard: {chunk.get('route_hint')}" if chunk.get("route_hint") else "") + (f" | Source: {chunk.get('canonical_url')}" if chunk.get("canonical_url") else ""),
        f"Chunk: `{chunk.get('id')}`",
        "",
        str(payload.get("text") or "").strip(),
        "",
        "This is public documentation retrieval only; no GCS mutation or drone command was sent.",
    ]
    return "\n".join(line for line in lines if line is not None)


def _query_terms(query: str) -> tuple[str, ...]:
    terms = []
    for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}", query.lower()):
        normalized = term.replace("_", "-")
        if normalized not in STOPWORDS:
            terms.append(normalized)
    return tuple(dict.fromkeys(terms))


def _score_chunk(chunk: DocsChunk, *, query: str, terms: tuple[str, ...]) -> float:
    title = chunk.title.lower()
    heading = chunk.heading.lower()
    summary = chunk.summary.lower()
    tags = " ".join(chunk.tags).lower()
    text = chunk.text.lower()
    phrase = query.strip().lower()
    score = 0.0
    if phrase and phrase in text:
        score += 20.0
    if phrase and phrase in (title + " " + heading + " " + summary):
        score += 30.0
    for term in terms:
        score += 12.0 if term in title else 0.0
        score += 9.0 if term in heading else 0.0
        score += 7.0 if term in tags else 0.0
        score += 4.0 if term in summary else 0.0
        score += min(text.count(term), 6) * 1.2
    return score


def _snippet(text: str, terms: tuple[str, ...], *, max_chars: int = 360) -> str:
    lower = text.lower()
    first = -1
    for term in terms:
        pos = lower.find(term)
        if pos >= 0 and (first < 0 or pos < first):
            first = pos
    if first < 0:
        return _collapse(text[:max_chars])
    start = max(0, first - max_chars // 3)
    end = min(len(text), start + max_chars)
    if end - start < max_chars:
        start = max(0, end - max_chars)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return prefix + _collapse(text[start:end]) + suffix


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_tags(tags: str | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(tags, tuple):
        return tags
    return tuple(part.strip().lower() for part in str(tags or "").split(",") if part.strip())


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()
