from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.docs_index import DocsChunk
from agent_runtime.query_understanding import build_assistant_query_plan
from agent_runtime.retrieval import RetrievalHit, load_default_retriever, search_retriever_queries


REPO_ROOT = Path(__file__).resolve().parents[1]
RETRIEVAL_EVAL_PATH = REPO_ROOT / "docs" / "agent-context" / "evals" / "simurgh-retrieval-quality.yaml"


def _load_cases() -> list[dict[str, object]]:
    payload = yaml.safe_load(RETRIEVAL_EVAL_PATH.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    cases = payload.get("cases")
    assert isinstance(cases, list) and cases
    return cases


def _ranked_retrieval_hits(prompt: str) -> tuple[RetrievalHit, ...]:
    plan = build_assistant_query_plan(prompt)
    return search_retriever_queries(
        load_default_retriever(),
        plan.search_queries,
        limit=8,
        tags=plan.tags,
    )


def test_retrieval_quality_eval_file_is_schema_clean():
    ids: set[str] = set()
    for case in _load_cases():
        assert isinstance(case.get("id"), str) and case["id"]
        assert case["id"] not in ids
        ids.add(str(case["id"]))
        assert isinstance(case.get("prompt"), str) and case["prompt"]
        expected = case.get("expected")
        assert isinstance(expected, dict)
        assert isinstance(expected.get("domain"), str) and expected["domain"]
        assert isinstance(expected.get("response_mode"), str) and expected["response_mode"]
        if expected.get("require_results", True):
            assert expected.get("top_resource_any") or expected.get("resources_any") or expected.get("resources_all")


def test_retrieval_quality_cases_route_and_retrieve_expected_docs():
    for case in _load_cases():
        prompt = str(case["prompt"])
        expected = case["expected"]
        assert isinstance(expected, dict)
        plan = build_assistant_query_plan(prompt)

        assert plan.domain == expected["domain"], case["id"]
        assert plan.response_mode == expected["response_mode"], case["id"]
        if "unclear" in expected:
            assert plan.unclear is bool(expected["unclear"]), case["id"]
        tags_any = tuple(str(tag) for tag in expected.get("tags_any") or ())
        if tags_any:
            assert any(tag in plan.tags for tag in tags_any), case["id"]

        if expected.get("require_results", True) is False:
            continue

        hits = _ranked_retrieval_hits(prompt)
        assert hits, case["id"]
        within_rank = int(expected.get("within_rank") or 5)
        top_score = hits[0].score
        assert top_score >= float(expected.get("min_top_score") or 1), case["id"]

        top_resource_any = {str(item) for item in expected.get("top_resource_any") or ()}
        if top_resource_any:
            assert hits[0].chunk.resource_id in top_resource_any, case["id"]

        ranked_resources = [hit.chunk.resource_id for hit in hits[:within_rank]]
        resources_any = {str(item) for item in expected.get("resources_any") or ()}
        if resources_any:
            assert any(resource in ranked_resources for resource in resources_any), case["id"]

        for resource in expected.get("resources_all") or ():
            assert resource in ranked_resources, case["id"]


def test_retrieval_interface_dedupes_multi_query_hits():
    hits = _ranked_retrieval_hits("connect n8n or claude desktop to simurgh mcp")

    assert hits
    assert all(isinstance(hit.chunk, DocsChunk) for hit in hits)
    assert len({hit.chunk.id for hit in hits}) == len(hits)
    assert hits == tuple(sorted(hits, key=lambda hit: (-hit.score, hit.chunk.path, hit.chunk.id)))
    assert any(hit.chunk.resource_id == "simurgh.mcp_client_recipes" for hit in hits[:5])


def test_retrieval_eval_prompts_are_safe_public_queries():
    forbidden_fragments = (
        "sk-proj-",
        "sk-or-v1-",
        "authorization: bearer",
        "password",
        "192.168.",
        "cm4-",
        "ticket",
        "screenshot",
    )
    for case in _load_cases():
        prompt = str(case["prompt"]).lower()
        assert not any(fragment in prompt for fragment in forbidden_fragments), case["id"]
