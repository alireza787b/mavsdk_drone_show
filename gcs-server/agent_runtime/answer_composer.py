"""Small Markdown composition helpers for Simurgh local answers.

The local read-only tools should return evidence-first Markdown that renders
cleanly in the dashboard and MCP clients. This module keeps formatting rules
centralized without giving the composer any authority to route, retrieve, or
execute tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence


@dataclass
class AnswerComposer:
    """Build compact, predictable Markdown for operator-facing answers."""

    lines: list[str] = field(default_factory=list)

    def line(self, value: object = "") -> "AnswerComposer":
        self.lines.append(str(value).rstrip())
        return self

    def blank(self) -> "AnswerComposer":
        if self.lines and self.lines[-1] != "":
            self.lines.append("")
        return self

    def bullets(self, values: Iterable[object]) -> "AnswerComposer":
        for value in values:
            text = str(value).strip()
            if not text:
                continue
            self.lines.append(text if text.startswith("-") else f"- {text}")
        return self

    def numbered(self, values: Iterable[object]) -> "AnswerComposer":
        for index, value in enumerate(values, start=1):
            text = str(value).strip()
            if text:
                self.lines.append(f"{index}. {text}")
        return self

    def table(self, headers: Sequence[object], rows: Iterable[Sequence[object]]) -> "AnswerComposer":
        table_text = markdown_table(headers, rows)
        if table_text:
            self.lines.extend(table_text.splitlines())
        return self

    def render(self) -> str:
        return compact_markdown_lines(self.lines)


def markdown_table(headers: Sequence[object], rows: Iterable[Sequence[object]]) -> str:
    """Return a GitHub-style Markdown table with a valid divider row."""

    normalized_headers = [str(header).strip() for header in headers]
    if len(normalized_headers) < 2 or any(not header for header in normalized_headers):
        return ""

    rendered_rows: list[list[str]] = []
    for row in rows:
        values = [str(value).strip() for value in row]
        if len(values) < len(normalized_headers):
            values.extend([""] * (len(normalized_headers) - len(values)))
        rendered_rows.append(values[: len(normalized_headers)])

    lines = [
        "| " + " | ".join(_escape_table_cell(header) for header in normalized_headers) + " |",
        "| " + " | ".join("---" for _ in normalized_headers) + " |",
    ]
    for row in rendered_rows:
        lines.append("| " + " | ".join(_escape_table_cell(value) for value in row) + " |")
    return "\n".join(lines)


def compact_markdown_lines(lines: Iterable[object]) -> str:
    """Normalize blank lines while preserving list/table/code content."""

    output: list[str] = []
    previous_blank = False
    for raw_line in lines:
        line = str(raw_line).rstrip()
        blank = not line.strip()
        if blank and (not output or previous_blank):
            previous_blank = True
            continue
        output.append(line)
        previous_blank = blank
    while output and not output[-1].strip():
        output.pop()
    return "\n".join(output)


def _escape_table_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()
