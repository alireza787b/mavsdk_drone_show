"""Provider-neutral retrieval abstraction for Simurgh public docs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .docs_index import DEFAULT_SEARCH_LIMIT, MAX_SEARCH_LIMIT, DocsChunk, GeneratedDocsIndex, load_default_docs_index


@dataclass(frozen=True)
class RetrievalQuery:
    """Bounded query for public Simurgh documentation retrieval."""

    text: str
    limit: int = DEFAULT_SEARCH_LIMIT
    tags: tuple[str, ...] = ()
    audience: str = ""

    def normalized(self) -> "RetrievalQuery":
        limit = max(1, min(int(self.limit or DEFAULT_SEARCH_LIMIT), MAX_SEARCH_LIMIT))
        return RetrievalQuery(
            text=str(self.text or "").strip(),
            limit=limit,
            tags=tuple(str(tag).strip().lower() for tag in self.tags if str(tag).strip()),
            audience=str(self.audience or "").strip().lower(),
        )


@dataclass(frozen=True)
class RetrievalHit:
    """One ranked retrieval result."""

    chunk: DocsChunk
    score: float
    snippet: str
    query: str


class Retriever(Protocol):
    """Search adapter contract for docs retrieval backends."""

    def search(self, query: RetrievalQuery) -> tuple[RetrievalHit, ...]:
        """Return ranked retrieval hits for one query."""


@dataclass(frozen=True)
class LexicalDocsRetriever:
    """Current lexical/tag-filtered docs retriever.

    Future vector, hybrid, rerank, managed-search, or GraphRAG adapters should
    preserve the RetrievalQuery/RetrievalHit contract so MCP docs tools and the
    dashboard/provider path keep the same retrieval semantics.
    """

    index: GeneratedDocsIndex

    def search(self, query: RetrievalQuery) -> tuple[RetrievalHit, ...]:
        normalized = query.normalized()
        matches = self.index.search(
            normalized.text,
            limit=normalized.limit,
            tags=normalized.tags,
            audience=normalized.audience,
        )
        return tuple(
            RetrievalHit(chunk=chunk, score=score, snippet=snippet, query=normalized.text)
            for chunk, score, snippet in matches
        )


def load_default_retriever() -> Retriever:
    return LexicalDocsRetriever(index=load_default_docs_index())


def search_retriever_queries(
    retriever: Retriever,
    queries: tuple[str, ...],
    *,
    limit: int = DEFAULT_SEARCH_LIMIT,
    tags: tuple[str, ...] = (),
    audience: str = "",
    include_untagged_fallback: bool = True,
) -> tuple[RetrievalHit, ...]:
    """Search rewritten queries and dedupe by docs chunk id."""

    ranked: dict[str, RetrievalHit] = {}
    normalized_tags = tuple(str(tag).strip().lower() for tag in tags if str(tag).strip())
    tag_sets: list[tuple[str, ...]] = []
    if normalized_tags:
        tag_sets.append(normalized_tags)
    if include_untagged_fallback or not tag_sets:
        tag_sets.append(())

    for query_index, query_text in enumerate(queries):
        query_text = str(query_text or "").strip()
        if not query_text:
            continue
        query_weight = 1.0 / float(query_index + 1)
        for tag_set in tag_sets:
            hits = retriever.search(RetrievalQuery(text=query_text, limit=limit, tags=tag_set, audience=audience))
            for hit in hits:
                weighted_hit = RetrievalHit(
                    chunk=hit.chunk,
                    score=hit.score * query_weight,
                    snippet=hit.snippet,
                    query=hit.query,
                )
                current = ranked.get(hit.chunk.id)
                if current is None or weighted_hit.score > current.score:
                    ranked[hit.chunk.id] = weighted_hit
    return tuple(sorted(ranked.values(), key=lambda hit: (-hit.score, hit.chunk.path, hit.chunk.id)))
