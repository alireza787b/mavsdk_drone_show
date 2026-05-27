from __future__ import annotations

from agent_runtime import AnswerComposer, markdown_table


def test_answer_composer_renders_valid_markdown_table_and_escapes_cells():
    content = markdown_table(("Tool", "Purpose"), (("MCP", "tools/list | tools/call"),))

    assert "| Tool | Purpose |" in content
    assert "| --- | --- |" in content
    assert "tools/list \\| tools/call" in content


def test_answer_composer_compacts_blank_lines_and_keeps_bullets():
    content = (
        AnswerComposer()
        .line("Heading")
        .blank()
        .blank()
        .bullets(("One", "- Two"))
        .blank()
        .render()
    )

    assert content == "Heading\n\n- One\n- Two"
