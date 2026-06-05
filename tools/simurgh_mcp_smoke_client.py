#!/usr/bin/env python3
"""Smoke-test the Simurgh Streamable HTTP MCP endpoint from outside the dashboard.

The client intentionally uses only the Python standard library so it can run on
operator laptops, validation hosts, or CI workers without installing an MCP SDK.
It never prints bearer tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


MCP_PROTOCOL_VERSION = "2025-11-25"
DEFAULT_QUESTION = "What MCP tools are available and what can Simurgh inspect read-only?"
DEFAULT_EXPECTED_TOOLS = (
    "mds.operator.question.answer",
    "mds.docs.search",
    "mds.docs.chunk.read",
    "mds.system.health.read",
)
DEFAULT_EXPECTED_PROMPTS = ("mds.compare_mission_modes",)
DEFAULT_EXPECTED_RESOURCES = (
    "mds://simurgh/status",
    "mds://simurgh/tool-registry",
    "mds://simurgh/context-index",
)
FORBIDDEN_TOOL_HINTS = (
    "raw_submit",
    "drone_local",
)
FORBIDDEN_TOOL_SEGMENTS = (
    "launch",
    "upload",
    "delete",
    "apply",
    "sync",
    "execute",
    "write",
    "mutate",
)


class SimurghMcpSmokeError(RuntimeError):
    """Raised when the MCP smoke cannot prove the expected read-only posture."""


def normalize_mcp_endpoint(base_url: str) -> str:
    value = str(base_url or "").strip().rstrip("/")
    if not value:
        raise SimurghMcpSmokeError("MCP base URL is required")
    if value.endswith("/api/v1/simurgh/mcp"):
        return value
    return f"{value}/api/v1/simurgh/mcp"


def load_bearer_token(*, token: str = "", token_env: str = "MDS_MCP_BEARER_TOKEN", token_file: str = "") -> str:
    if token:
        return token.strip()
    if token_env and os.environ.get(token_env):
        return os.environ[token_env].strip()
    if token_file:
        path = Path(token_file).expanduser()
        if not path.is_file():
            raise SimurghMcpSmokeError(f"token file not found: {path}")
        return path.read_text(encoding="utf-8").strip()
    return ""


def json_rpc_payload(request_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


@dataclass
class McpHttpClient:
    endpoint: str
    bearer_token: str = ""
    timeout: float = 20.0
    opener: Callable[..., Any] | None = None

    def call(self, request_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = json.dumps(json_rpc_payload(request_id, method, params)).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            "User-Agent": "mds-simurgh-mcp-smoke/1.0",
        }
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        request = urllib.request.Request(self.endpoint, data=payload, headers=headers, method="POST")
        try:
            opener = self.opener or urllib.request.urlopen
            with opener(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise SimurghMcpSmokeError(f"{method} failed with HTTP {exc.code}: {raw[:500]}") from exc
        except urllib.error.URLError as exc:
            raise SimurghMcpSmokeError(f"{method} connection failed: {exc.reason}") from exc

        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SimurghMcpSmokeError(f"{method} returned non-JSON content: {raw[:500]}") from exc
        if "error" in message:
            raise SimurghMcpSmokeError(f"{method} returned JSON-RPC error: {message['error']}")
        return message.get("result") or {}


def _tool_names(tools_result: dict[str, Any]) -> list[str]:
    return sorted(str(tool.get("name") or "") for tool in tools_result.get("tools", []) if tool.get("name"))


def _prompt_names(prompts_result: dict[str, Any]) -> list[str]:
    return sorted(str(prompt.get("name") or "") for prompt in prompts_result.get("prompts", []) if prompt.get("name"))


def _resource_uris(resources_result: dict[str, Any]) -> list[str]:
    return sorted(str(resource.get("uri") or "") for resource in resources_result.get("resources", []) if resource.get("uri"))


def _resource_count(resources_result: dict[str, Any]) -> int:
    return len(resources_result.get("resources") or [])


def _forbidden_tool_names(tool_names: list[str]) -> list[str]:
    forbidden: list[str] = []
    for name in tool_names:
        normalized = name.lower()
        if any(hint in normalized for hint in FORBIDDEN_TOOL_HINTS):
            forbidden.append(name)
            continue
        segments = normalized.split(".")
        if any(segment in FORBIDDEN_TOOL_SEGMENTS for segment in segments):
            forbidden.append(name)
    return forbidden


def _content_preview(tool_result: dict[str, Any], max_chars: int = 220) -> str:
    chunks = []
    for item in tool_result.get("content") or []:
        text = item.get("text") if isinstance(item, dict) else ""
        if text:
            chunks.append(str(text))
    return " ".join(chunks).strip().replace("\n", " ")[:max_chars]


def _first_docs_chunk_id(tool_result: dict[str, Any]) -> str:
    structured = tool_result.get("structuredContent") or {}
    results = structured.get("results") if isinstance(structured, dict) else None
    if not isinstance(results, list) or not results:
        raise SimurghMcpSmokeError("mds.docs.search returned no structured results")
    first = results[0] if isinstance(results[0], dict) else {}
    chunk_id = str(first.get("id") or "").strip()
    if not chunk_id:
        raise SimurghMcpSmokeError("mds.docs.search first result did not include a chunk id")
    return chunk_id


def _assert_tool_result_ok(tool_result: dict[str, Any], *, tool_name: str) -> None:
    if tool_result.get("isError") is True:
        raise SimurghMcpSmokeError(f"{tool_name} returned an error: {_content_preview(tool_result, 500)}")


def _assert_tool_result_blocked(tool_result: dict[str, Any], *, tool_name: str) -> None:
    if tool_result.get("isError") is not True:
        raise SimurghMcpSmokeError(f"{tool_name} did not block the action request")
    if "blocked" not in _content_preview(tool_result, 500).lower():
        raise SimurghMcpSmokeError(f"{tool_name} blocked without a clear blocked explanation")


def run_smoke(
    client: Any,
    *,
    question: str = DEFAULT_QUESTION,
    expected_tools: tuple[str, ...] = DEFAULT_EXPECTED_TOOLS,
    expected_prompts: tuple[str, ...] = DEFAULT_EXPECTED_PROMPTS,
    expected_resources: tuple[str, ...] = DEFAULT_EXPECTED_RESOURCES,
    min_tools: int = 10,
) -> dict[str, Any]:
    started = time.monotonic()
    initialize = client.call(
        1,
        "initialize",
        {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mds-simurgh-smoke", "version": "1.0"},
        },
    )
    prompts_result = client.call(2, "prompts/list")
    prompt_names = _prompt_names(prompts_result)
    tools_result = client.call(3, "tools/list")
    tool_names = _tool_names(tools_result)
    resources_result = client.call(4, "resources/list")
    resource_uris = _resource_uris(resources_result)

    missing = [tool for tool in expected_tools if tool not in tool_names]
    if missing:
        raise SimurghMcpSmokeError(f"expected MCP tools are missing: {', '.join(missing)}")
    missing_prompts = [prompt for prompt in expected_prompts if prompt not in prompt_names]
    if missing_prompts:
        raise SimurghMcpSmokeError(f"expected MCP prompts are missing: {', '.join(missing_prompts)}")
    missing_resources = [uri for uri in expected_resources if uri not in resource_uris]
    if missing_resources:
        raise SimurghMcpSmokeError(f"expected MCP resources are missing: {', '.join(missing_resources)}")
    if len(tool_names) < min_tools:
        raise SimurghMcpSmokeError(f"too few MCP tools exposed: {len(tool_names)} < {min_tools}")

    forbidden = _forbidden_tool_names(tool_names)
    if forbidden:
        raise SimurghMcpSmokeError(f"forbidden-looking tools exposed: {', '.join(forbidden[:8])}")

    status_resource = client.call(5, "resources/read", {"uri": "mds://simurgh/status"})
    if not status_resource.get("contents"):
        raise SimurghMcpSmokeError("resources/read for mds://simurgh/status returned no content")

    compare_prompt = client.call(
        6,
        "prompts/get",
        {
            "name": "mds.compare_mission_modes",
            "arguments": {"question": "Compare QuickScout and Swarm Trajectory for a field operator."},
        },
    )
    if not compare_prompt.get("messages"):
        raise SimurghMcpSmokeError("prompts/get for mds.compare_mission_modes returned no messages")

    answer_result = client.call(
        7,
        "tools/call",
        {"name": "mds.operator.question.answer", "arguments": {"question": question}},
    )
    _assert_tool_result_ok(answer_result, tool_name="mds.operator.question.answer")
    docs_result = client.call(
        8,
        "tools/call",
        {"name": "mds.docs.search", "arguments": {"query": "Simurgh MCP clients", "limit": 3}},
    )
    _assert_tool_result_ok(docs_result, tool_name="mds.docs.search")
    chunk_id = _first_docs_chunk_id(docs_result)
    docs_chunk_result = client.call(
        9,
        "tools/call",
        {"name": "mds.docs.chunk.read", "arguments": {"chunk_id": chunk_id, "max_chars": 1200}},
    )
    _assert_tool_result_ok(docs_chunk_result, tool_name="mds.docs.chunk.read")

    blocked_action_result = client.call(
        10,
        "tools/call",
        {"name": "mds.operator.question.answer", "arguments": {"question": "Can you launch the drone show now?"}},
    )
    _assert_tool_result_blocked(blocked_action_result, tool_name="mds.operator.question.answer")

    return {
        "server": initialize.get("serverInfo", {}),
        "protocol_version": initialize.get("protocolVersion"),
        "tool_count": len(tool_names),
        "tools_preview": tool_names[:20],
        "prompt_count": len(prompt_names),
        "resource_count": _resource_count(resources_result),
        "expected_tools_present": list(expected_tools),
        "expected_prompts_present": list(expected_prompts),
        "expected_resources_present": list(expected_resources),
        "answer_preview": _content_preview(answer_result),
        "docs_preview": _content_preview(docs_result),
        "docs_chunk_preview": _content_preview(docs_chunk_result),
        "blocked_action_verified": True,
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test the MDS Simurgh HTTP MCP endpoint.")
    parser.add_argument("--base-url", required=True, help="GCS base URL or full /api/v1/simurgh/mcp endpoint")
    parser.add_argument("--token-env", default="MDS_MCP_BEARER_TOKEN", help="Environment variable containing bearer token")
    parser.add_argument("--token-file", default="", help="File containing bearer token; raw token is not printed")
    parser.add_argument("--token", default="", help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds")
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="Read-only question for mds.operator.question.answer")
    parser.add_argument("--min-tools", type=int, default=10, help="Minimum expected read-only MCP tools")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        endpoint = normalize_mcp_endpoint(args.base_url)
        token = load_bearer_token(token=args.token, token_env=args.token_env, token_file=args.token_file)
        client = McpHttpClient(endpoint=endpoint, bearer_token=token, timeout=args.timeout)
        summary = run_smoke(client, question=args.question, min_tools=args.min_tools)
    except SimurghMcpSmokeError as exc:
        print(f"Simurgh MCP smoke failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        server = summary.get("server") or {}
        print("Simurgh MCP smoke passed")
        print(f"Endpoint: {endpoint}")
        print(f"Server: {server.get('name', 'unknown')} {server.get('version', '')}".rstrip())
        print(f"Protocol: {summary.get('protocol_version')}")
        print(f"Tools: {summary.get('tool_count')} read-only callable tools")
        print(f"Prompts: {summary.get('prompt_count')}")
        print(f"Resources: {summary.get('resource_count')}")
        print(f"Action block verified: {summary.get('blocked_action_verified')}")
        print(f"Answer preview: {summary.get('answer_preview') or 'n/a'}")
        print(f"Docs preview: {summary.get('docs_preview') or 'n/a'}")
        print(f"Docs chunk preview: {summary.get('docs_chunk_preview') or 'n/a'}")
        print(f"Duration: {summary.get('duration_ms')} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
