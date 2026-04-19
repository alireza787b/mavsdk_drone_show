#!/usr/bin/env python3
"""Package a generic MDS runtime evidence report.

This tool intentionally avoids project/customer-specific language. Private
deployments can pass their own title/subtitle and keep generated packages out of
the public repo when evidence contains customer details.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any


IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
DEFAULT_LARGE_EVIDENCE_LIMIT_MB = 25


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def safe_slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    return "-".join(part for part in slug.split("-") if part) or "runtime-evidence"


def repo_commit(repo_root: Path | None) -> str:
    if not repo_root:
        return "not-recorded"
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "not-recorded"


def command_status(value: Any) -> str:
    if not isinstance(value, dict):
        return "n/a"
    return str(value.get("status") or value.get("outcome") or value.get("phase") or "recorded")


def find_command_rows(summary: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    skip_keys = {
        "baseline_telemetry",
        "final_telemetry",
        "timeline_trace",
        "event_log",
        "health",
        "roles",
        "drone_ids",
    }
    for key, value in summary.items():
        if key in skip_keys or not isinstance(value, dict):
            continue
        if not any(field in value for field in ("status", "outcome", "phase", "acks", "executions")):
            continue
        acks = value.get("acks") if isinstance(value.get("acks"), dict) else {}
        executions = value.get("executions") if isinstance(value.get("executions"), dict) else {}
        accepted = acks.get("accepted", "n/a")
        succeeded = executions.get("succeeded", "n/a")
        rows.append((key, command_status(value), str(accepted), str(succeeded)))
    return rows


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        rows = [["n/a" for _ in headers]]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def timing_rows(metrics: dict[str, Any]) -> list[list[str]]:
    rows = []
    for key, value in metrics.items():
        if not key.endswith("_sec") and key != "total_run_sec":
            continue
        try:
            rendered = f"{float(value):.2f} s"
        except (TypeError, ValueError):
            rendered = str(value)
        rows.append([key.replace("_", " "), rendered])
    return rows


def tracking_rows(metrics: dict[str, Any]) -> list[list[str]]:
    stats = metrics.get("tracking_error_stats")
    if not isinstance(stats, dict):
        return []
    rows = []
    for segment, roles in stats.items():
        if not isinstance(roles, dict):
            continue
        for role, values in roles.items():
            if not isinstance(values, dict):
                continue
            rows.append(
                [
                    str(segment),
                    str(role),
                    str(values.get("horizontal_mean_m", "n/a")),
                    str(values.get("horizontal_p95_m", "n/a")),
                    str(values.get("horizontal_max_m", "n/a")),
                    str(values.get("vertical_p95_m", "n/a")),
                ]
            )
    return rows


def event_rows(summary: dict[str, Any]) -> list[list[str]]:
    events = summary.get("event_log")
    if not isinstance(events, list):
        return []
    first_ts = None
    rows = []
    for event in events:
        if not isinstance(event, dict):
            continue
        timestamp = event.get("timestamp")
        if isinstance(timestamp, (int, float)):
            first_ts = timestamp if first_ts is None else first_ts
            elapsed = f"+{timestamp - first_ts:.1f}s"
        else:
            elapsed = "n/a"
        rows.append([elapsed, str(event.get("label", "event")), ", ".join(map(str, event.get("target_ids", [])))])
    return rows


def copy_visuals(visuals_dir: Path | None, output_visuals_dir: Path, prefix: str | None) -> list[str]:
    if not visuals_dir or not visuals_dir.exists():
        return []
    output_visuals_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in sorted(visuals_dir.iterdir()):
        if not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if prefix and not source.name.startswith(prefix):
            continue
        shutil.copy2(source, output_visuals_dir / source.name)
        copied.append(source.name)
    return copied


def copy_evidence(
    sources: list[Path],
    output_evidence_dir: Path,
    *,
    large_limit_mb: float,
    include_large: bool,
) -> tuple[list[str], list[str]]:
    output_evidence_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    skipped: list[str] = []
    limit_bytes = int(large_limit_mb * 1024 * 1024)
    for source in sources:
        if not source.exists() or not source.is_file():
            continue
        size = source.stat().st_size
        if size > limit_bytes and not include_large:
            skipped.append(f"{source.name} ({size / (1024 * 1024):.1f} MB)")
            continue
        shutil.copy2(source, output_evidence_dir / source.name)
        copied.append(source.name)
    return copied, skipped


def render_assets(visual_files: list[str]) -> str:
    if not visual_files:
        return "_No visual assets were supplied._"
    lines = []
    for name in visual_files:
        if Path(name).suffix.lower() in IMAGE_SUFFIXES:
            lines.append(f"![{name}](../visuals/{name})")
    return "\n\n".join(lines)


def build_report(
    *,
    title: str,
    subtitle: str,
    scenario: str,
    date: str,
    commit: str,
    summary: dict[str, Any],
    metrics: dict[str, Any],
    visual_files: list[str],
    evidence_files: list[str],
    skipped_evidence: list[str],
) -> str:
    command_rows = [[key, status, accepted, succeeded] for key, status, accepted, succeeded in find_command_rows(summary)]
    evidence_lines = [f"- [`{name}`](../evidence/{name})" for name in evidence_files] or ["- No small evidence files were copied."]
    if skipped_evidence:
        evidence_lines.append("- Large evidence retained outside git/package copy:")
        evidence_lines.extend(f"- `{item}`" for item in skipped_evidence)

    return dedent(
        f"""\
        ---
        title: "{title}"
        subtitle: "{subtitle}"
        date: "{date}"
        ---

        # Executive Summary

        This package records an accepted MDS runtime scenario using a generic, customer-neutral evidence format.

        - Scenario: `{scenario}`
        - Result: `{summary.get('result', 'UNKNOWN')}`
        - Repo commit: `{commit}`
        - Drones: `{summary.get('drone_ids', 'not-recorded')}`

        # Scope And Claim Discipline

        This report should only claim behavior proven by the attached run summary, metrics, visuals, and logs.
        Private customer names, contract terms, site details, and mission-sensitive context should be added only in private forks or external packages.

        # Command Results

        {markdown_table(["Phase", "Status", "Accepted", "Succeeded"], command_rows)}

        # Timing Summary

        {markdown_table(["Metric", "Value"], timing_rows(metrics))}

        # Event Timeline

        {markdown_table(["Elapsed", "Event", "Targets"], event_rows(summary))}

        # Tracking Metrics

        {markdown_table(["Segment", "Role", "Mean horiz. m", "P95 horiz. m", "Max horiz. m", "P95 vertical m"], tracking_rows(metrics))}

        # Visual Evidence

        {render_assets(visual_files)}

        # Evidence Files

        {chr(10).join(evidence_lines)}

        # Reproduction Notes

        1. Re-run the runtime validator or scenario-specific script that generated the accepted summary JSON.
        2. Fetch raw logs/ULogs for the same run when available.
        3. Rebuild metrics and visuals from the accepted summary.
        4. Package the report with `tools/package_runtime_evidence_report.py`.
        5. Keep customer-specific evidence in a private repo or external package unless it is explicitly safe for public release.
        """
    ).strip() + "\n"


def css_text() -> str:
    return dedent(
        """\
        @page {
          size: A4;
          margin: 18mm 16mm;
          @bottom-center {
            content: "MDS Runtime Evidence";
            font-size: 9pt;
            color: #64748b;
          }
          @bottom-right {
            content: counter(page) " / " counter(pages);
            font-size: 9pt;
            color: #64748b;
          }
        }
        body {
          color: #0f172a;
          font-family: "DejaVu Sans", "Liberation Sans", sans-serif;
          font-size: 10.5pt;
          line-height: 1.45;
        }
        h1, h2, h3 { color: #0f172a; margin-top: 1.15em; }
        table { border-collapse: collapse; width: 100%; margin: 0.8em 0; }
        th, td { border: 1px solid #cbd5e1; padding: 6px 8px; vertical-align: top; }
        th { background: #e2e8f0; }
        img { max-width: 100%; margin: 0.5em 0 1em; border: 1px solid #e2e8f0; }
        code { background: #f1f5f9; padding: 1px 4px; border-radius: 4px; }
        """
    )


def render_pdf(markdown_path: Path, html_path: Path, pdf_path: Path, css_path: Path) -> bool:
    if not shutil.which("pandoc") or not shutil.which("weasyprint"):
        return False
    subprocess.run(
        [
            "pandoc",
            markdown_path.name,
            "-f",
            "gfm",
            "-t",
            "html5",
            "--standalone",
            "--css",
            css_path.name,
            "-o",
            html_path.name,
        ],
        cwd=markdown_path.parent,
        check=True,
    )
    subprocess.run(["weasyprint", html_path.name, pdf_path.name], cwd=markdown_path.parent, check=True)
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package a generic MDS runtime evidence report.")
    parser.add_argument("--summary-json", type=Path, required=True, help="Accepted runtime summary JSON")
    parser.add_argument("--metrics-json", type=Path, help="Optional metrics JSON")
    parser.add_argument("--visuals-dir", type=Path, help="Directory containing generated plots/animations")
    parser.add_argument("--evidence-file", type=Path, action="append", default=[], help="Evidence file to copy; repeat as needed")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output package directory")
    parser.add_argument("--repo-root", type=Path, help="Repo root used to record current git commit")
    parser.add_argument("--title", default="MDS Runtime Evidence Report")
    parser.add_argument("--subtitle", default="Accepted Runtime Scenario Evidence")
    parser.add_argument("--scenario", default="runtime-scenario")
    parser.add_argument("--asset-prefix", default=None, help="Only copy visual assets with this filename prefix")
    parser.add_argument("--large-evidence-limit-mb", type=float, default=DEFAULT_LARGE_EVIDENCE_LIMIT_MB)
    parser.add_argument("--include-large-evidence", action="store_true", help="Copy evidence files larger than the size limit")
    parser.add_argument("--no-pdf", action="store_true", help="Skip optional HTML/PDF rendering")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = read_json(args.summary_json)
    metrics = read_json(args.metrics_json) if args.metrics_json else {}
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    report_dir = output_dir / "report"
    visuals_dir = output_dir / "visuals"
    evidence_dir = output_dir / "evidence"
    report_dir.mkdir(parents=True, exist_ok=True)

    visual_files = copy_visuals(args.visuals_dir, visuals_dir, args.asset_prefix)
    evidence_sources = [args.summary_json]
    if args.metrics_json:
        evidence_sources.append(args.metrics_json)
    evidence_sources.extend(args.evidence_file)
    evidence_files, skipped_evidence = copy_evidence(
        evidence_sources,
        evidence_dir,
        large_limit_mb=float(args.large_evidence_limit_mb),
        include_large=bool(args.include_large_evidence),
    )

    stem = safe_slug(args.scenario)
    report_md = report_dir / f"{stem}-evidence-report.md"
    report_html = report_dir / f"{stem}-evidence-report.html"
    report_pdf = report_dir / f"{stem}-evidence-report.pdf"
    css_path = report_dir / "report.css"

    date = datetime.now(timezone.utc).date().isoformat()
    write_text(css_path, css_text())
    write_text(
        report_md,
        build_report(
            title=args.title,
            subtitle=args.subtitle,
            scenario=args.scenario,
            date=date,
            commit=repo_commit(args.repo_root),
            summary=summary,
            metrics=metrics,
            visual_files=visual_files,
            evidence_files=evidence_files,
            skipped_evidence=skipped_evidence,
        ),
    )
    pdf_rendered = False if args.no_pdf else render_pdf(report_md, report_html, report_pdf, css_path)
    write_text(
        output_dir / "README.md",
        dedent(
            f"""\
            # MDS Runtime Evidence Package

            - Markdown report: `report/{report_md.name}`
            - HTML report: `report/{report_html.name}` {'(generated)' if report_html.exists() else '(not generated)'}
            - PDF report: `report/{report_pdf.name}` {'(generated)' if pdf_rendered else '(not generated; install pandoc and weasyprint)'}
            - Visual assets: `visuals/`
            - Evidence files: `evidence/`
            """
        ),
    )
    print(report_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
