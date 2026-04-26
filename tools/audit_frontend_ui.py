#!/usr/bin/env python3
"""Audit frontend UI consistency guardrails for the MDS dashboard.

The script is intentionally lightweight: it reports debt without failing by
default. Use --strict when a CI-style gate should fail on structural problems
such as missing route docs or broken doc paths.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = REPO_ROOT / "app" / "dashboard" / "drone-dashboard"
SRC_ROOT = FRONTEND_ROOT / "src"
DOCS_ROOT = REPO_ROOT / "docs"
ROUTE_DOCS_FILE = SRC_ROOT / "config" / "routeDocs.js"
APP_FILE = SRC_ROOT / "App.js"

SOURCE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".css"}
TOKEN_FILES = {
    (SRC_ROOT / "styles" / "DesignTokens.css").resolve(),
}
ALLOWED_DOMAIN_COLOR_FILES = {
    # These values are data passed to map/plot renderers or HTML color inputs,
    # not CSS styling. CSS variables would be invalid or unreliable there.
    "app/dashboard/drone-dashboard/src/utilities/SpeedCalculator.js": {
        "#00d4ff",
        "#f5a623",
        "#dc3545",
        "#8ea4bf",
    },
    "app/dashboard/drone-dashboard/src/utilities/missionConfigFields.js": {
        "#00d4ff",
    },
}

COLOR_LITERAL_RE = re.compile(r"(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\))")
Z_INDEX_LITERAL_RE = re.compile(r"z-index\s*:\s*(?!var\()[0-9]+", re.IGNORECASE)
NATIVE_TITLE_ATTR_RE = re.compile(r"<[a-z][^>\n]*\btitle\s*=")
ROUTE_RE = re.compile(r"<Route\s+path=\"([^\"]+)\"")
DOC_ENTRY_RE = re.compile(
    r"path:\s*'(?P<path>[^']+)'.*?label:\s*'(?P<label>[^']+)'.*?docPath:\s*'(?P<docPath>[^']+)'",
    re.DOTALL,
)
IMPORT_RE = re.compile(r"import\s+.+?\s+from\s+['\"](?P<module>[^'\"]+)['\"]")


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    file: str
    line: int
    detail: str


def iter_source_files() -> Iterable[Path]:
    for path in sorted(SRC_ROOT.rglob("*")):
        if path.is_file() and path.suffix in SOURCE_EXTENSIONS:
            yield path


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def is_test_file(path: Path) -> bool:
    return any(path.name.endswith(suffix) for suffix in (".test.js", ".test.jsx", ".test.ts", ".test.tsx"))


def is_allowed_hardcoded_color(path: Path, literal: str) -> bool:
    if is_test_file(path):
        return True
    return literal in ALLOWED_DOMAIN_COLOR_FILES.get(rel(path), set())


def audit_hardcoded_colors() -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_source_files():
        if path.resolve() in TOKEN_FILES:
            continue
        if "node_modules" in path.parts:
            continue
        text = read_text(path)
        for match in COLOR_LITERAL_RE.finditer(text):
            literal = match.group(1)
            source_window = text[match.start():match.start() + 32]
            if "currentColor" in literal or "var(" in literal or source_window.startswith(("rgba(var(", "rgb(var(")):
                continue
            if is_allowed_hardcoded_color(path, literal):
                continue
            findings.append(
                Finding(
                    code="hardcoded-color",
                    severity="debt",
                    file=rel(path),
                    line=line_number(text, match.start()),
                    detail=literal,
                )
            )
    return findings


def audit_hardcoded_z_index() -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_source_files():
        if path.resolve() in TOKEN_FILES:
            continue
        text = read_text(path)
        for match in Z_INDEX_LITERAL_RE.finditer(text):
            findings.append(
                Finding(
                    code="hardcoded-z-index",
                    severity="debt",
                    file=rel(path),
                    line=line_number(text, match.start()),
                    detail=match.group(0),
                )
            )
    return findings


def audit_title_attributes() -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_source_files():
        if path.suffix not in {".js", ".jsx", ".tsx", ".ts"}:
            continue
        if path.name.endswith(".test.js") or path.name.endswith(".test.jsx"):
            continue
        text = read_text(path)
        for match in NATIVE_TITLE_ATTR_RE.finditer(text):
            findings.append(
                Finding(
                    code="native-title",
                    severity="debt",
                    file=rel(path),
                    line=line_number(text, match.start()),
                    detail="Prefer InfoHint/tooltip primitive for persistent operator help; native title is acceptable only for simple labels.",
                )
            )
    return findings


def parse_app_routes() -> set[str]:
    text = read_text(APP_FILE)
    return set(ROUTE_RE.findall(text))


def parse_route_docs() -> dict[str, dict[str, str]]:
    text = read_text(ROUTE_DOCS_FILE)
    docs: dict[str, dict[str, str]] = {}
    for match in DOC_ENTRY_RE.finditer(text):
        docs[match.group("path")] = {
            "label": match.group("label"),
            "docPath": match.group("docPath"),
        }
    return docs


def audit_route_docs() -> list[Finding]:
    findings: list[Finding] = []
    app_routes = parse_app_routes()
    route_docs = parse_route_docs()

    for route in sorted(app_routes):
        if route not in route_docs:
            findings.append(
                Finding(
                    code="missing-route-doc",
                    severity="critical",
                    file=rel(ROUTE_DOCS_FILE),
                    line=1,
                    detail=f"No docs metadata for route {route}",
                )
            )

    for route, metadata in sorted(route_docs.items()):
        doc_path = metadata.get("docPath", "")
        if doc_path.startswith("http://") or doc_path.startswith("https://"):
            continue
        absolute_doc_path = REPO_ROOT / doc_path
        if not absolute_doc_path.exists():
            findings.append(
                Finding(
                    code="broken-doc-path",
                    severity="critical",
                    file=rel(ROUTE_DOCS_FILE),
                    line=1,
                    detail=f"{route} references missing {doc_path}",
                )
            )
    return findings


def audit_duplicate_primitives() -> list[Finding]:
    findings: list[Finding] = []
    duplicate_primitive_files = [
        SRC_ROOT / "components" / "ConfirmModal.js",
        SRC_ROOT / "components" / "ConfirmationDialog.js",
        SRC_ROOT / "components" / "ConfirmationModal.js",
        SRC_ROOT / "components" / "Modal.js",
        SRC_ROOT / "components" / "Notification.js",
        SRC_ROOT / "components" / "MissionNotification.js",
    ]
    for path in duplicate_primitive_files:
        if path.exists():
            findings.append(
                Finding(
                    code="duplicate-primitive",
                    severity="debt",
                    file=rel(path),
                    line=1,
                    detail="Candidate for migration into shared operator primitive layer.",
                )
            )
    return findings


def audit_icon_stack() -> list[Finding]:
    module_counts: dict[str, set[str]] = {}
    watched_prefixes = ("react-icons", "@fortawesome", "@mui/icons-material")
    for path in iter_source_files():
        if path.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        text = read_text(path)
        for match in IMPORT_RE.finditer(text):
            module = match.group("module")
            if module.startswith(watched_prefixes):
                root = module.split("/")[0] if not module.startswith("@") else "/".join(module.split("/")[:2])
                module_counts.setdefault(root, set()).add(rel(path))

    findings: list[Finding] = []
    if len(module_counts) > 1:
        detail = ", ".join(f"{module}:{len(files)} files" for module, files in sorted(module_counts.items()))
        findings.append(
            Finding(
                code="mixed-icon-stack",
                severity="debt",
                file=rel(FRONTEND_ROOT / "package.json"),
                line=1,
                detail=detail,
            )
        )
    return findings


def audit_dependency_mismatch() -> list[Finding]:
    package_json_path = FRONTEND_ROOT / "package.json"
    package_json = json.loads(read_text(package_json_path))
    declared = set(package_json.get("dependencies", {})) | set(package_json.get("devDependencies", {}))
    imported_modules: set[str] = set()

    for path in iter_source_files():
        if path.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        text = read_text(path)
        for match in IMPORT_RE.finditer(text):
            module = match.group("module")
            if module.startswith("."):
                continue
            root = module.split("/")[0] if not module.startswith("@") else "/".join(module.split("/")[:2])
            imported_modules.add(root)

    findings: list[Finding] = []
    for module in sorted(imported_modules - declared):
        if module in {"react", "react-dom"}:
            continue
        findings.append(
            Finding(
                code="undeclared-import",
                severity="critical",
                file=rel(package_json_path),
                line=1,
                detail=f"{module} is imported but not declared in package.json",
            )
        )
    return findings


def run_audit() -> dict[str, object]:
    groups = {
        "route_docs": audit_route_docs(),
        "dependency_mismatch": audit_dependency_mismatch(),
        "duplicate_primitives": audit_duplicate_primitives(),
        "icon_stack": audit_icon_stack(),
        "hardcoded_colors": audit_hardcoded_colors(),
        "hardcoded_z_index": audit_hardcoded_z_index(),
        "native_title_attributes": audit_title_attributes(),
    }
    all_findings = [finding for group in groups.values() for finding in group]
    summary: dict[str, int] = {}
    for finding in all_findings:
        summary[finding.code] = summary.get(finding.code, 0) + 1

    return {
        "summary": summary,
        "critical_count": sum(1 for finding in all_findings if finding.severity == "critical"),
        "debt_count": sum(1 for finding in all_findings if finding.severity == "debt"),
        "groups": {
            key: [asdict(finding) for finding in findings]
            for key, findings in groups.items()
        },
    }


def format_text_report(report: dict[str, object], max_items: int) -> str:
    lines = [
        "MDS frontend UI audit",
        "======================",
        f"Critical findings: {report['critical_count']}",
        f"Debt findings: {report['debt_count']}",
        "",
        "Summary:",
    ]
    summary = report["summary"]
    if isinstance(summary, dict) and summary:
        for code, count in sorted(summary.items()):
            lines.append(f"- {code}: {count}")
    else:
        lines.append("- no findings")

    groups = report["groups"]
    if isinstance(groups, dict):
        for group_name, findings in groups.items():
            if not findings:
                continue
            lines.extend(["", f"{group_name}:"])
            for finding in findings[:max_items]:
                lines.append(
                    f"- [{finding['severity']}] {finding['file']}:{finding['line']} "
                    f"{finding['code']} - {finding['detail']}"
                )
            if len(findings) > max_items:
                lines.append(f"- ... {len(findings) - max_items} more")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print the full audit report as JSON.")
    parser.add_argument("--write-json", type=Path, help="Write the full audit report to a JSON file.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when critical findings exist.")
    parser.add_argument("--max-items", type=int, default=12, help="Maximum findings per group in text output.")
    args = parser.parse_args()

    report = run_audit()
    if args.write_json:
        output_path = args.write_json if args.write_json.is_absolute() else REPO_ROOT / args.write_json
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_text_report(report, args.max_items))

    if args.strict and report["critical_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
