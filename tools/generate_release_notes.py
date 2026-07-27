#!/usr/bin/env python3
"""
Release notes generator for MDS - Mission-Directed Swarm

Uses the curated CHANGELOG entry for the target tag when available and falls
back to conventional commits. All release links resolve through the immutable
target tag.
"""

import os
import re
import subprocess
from pathlib import Path
from collections import defaultdict
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OFFICIAL_REPOSITORY = "alireza787b/mavsdk_drone_show"
PROJECT_NAME = "MDS - Mission-Directed Swarm"


def get_release_repository():
    """Return the repository used for release links."""
    configured = os.environ.get("GITHUB_REPOSITORY", OFFICIAL_REPOSITORY).strip()
    return configured or OFFICIAL_REPOSITORY


def get_curated_changelog_entry(release_tag):
    """Return (release_date, markdown) for an exact release tag, if present."""
    changelog_path = PROJECT_ROOT / "CHANGELOG.md"
    if not changelog_path.exists():
        return None

    release_name = release_tag.removeprefix("v")
    changelog = changelog_path.read_text(encoding="utf-8")
    heading = re.compile(
        rf"^## \[{re.escape(release_name)}\](?:\s+-\s+([^\n]+))?\s*$",
        re.MULTILINE,
    )
    match = heading.search(changelog)
    if match is None:
        return None

    following_heading = re.search(
        r"^## \[[^\]]+\].*$",
        changelog[match.end():],
        re.MULTILINE,
    )
    end = (
        match.end() + following_heading.start()
        if following_heading is not None
        else len(changelog)
    )
    section = changelog[match.end():end].strip()
    section = re.sub(r"\n---\s*$", "", section).strip()
    if not section:
        return None
    return (match.group(1), section)


def get_git_commits_since_last_tag():
    """Get all commit messages and hashes since last version tag"""
    try:
        # Get last tag
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False
        )

        last_tag = result.stdout.strip() if result.returncode == 0 else None

        if last_tag:
            # Get commits since last tag
            result = subprocess.run(
                ["git", "log", f"{last_tag}..HEAD", "--pretty=format:%H|||%s|||%b"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=True
            )
        else:
            # Get recent commits (last 50)
            result = subprocess.run(
                ["git", "log", "-50", "--pretty=format:%H|||%s|||%b"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=True
            )

        commits = []
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split('|||')
                if len(parts) >= 2:
                    commits.append({
                        'hash': parts[0][:8],
                        'subject': parts[1],
                        'body': parts[2] if len(parts) > 2 else ''
                    })

        return commits

    except subprocess.CalledProcessError:
        return []


def parse_conventional_commit(commit):
    """
    Parse conventional commit message

    Returns: (type, scope, description, breaking)
    """
    subject = commit['subject']
    body = commit['body']

    # Match conventional commit format: type(scope)!: description
    match = re.match(r'^(\w+)(?:\(([^)]+)\))?(!)?:\s*(.+)$', subject)

    if match:
        commit_type = match.group(1).lower()
        scope = match.group(2) or ''
        is_breaking = match.group(3) == '!' or 'BREAKING CHANGE' in body.upper()
        description = match.group(4)
    else:
        # Non-conventional commit
        commit_type = 'other'
        scope = ''
        is_breaking = 'BREAKING CHANGE' in body.upper() or 'BREAKING CHANGE' in subject.upper()
        description = subject

    return commit_type, scope, description, is_breaking


def categorize_commits(commits, repository):
    """
    Categorize commits by type

    Returns: dict with categories
    """
    categories = defaultdict(list)

    for commit in commits:
        commit_type, scope, description, is_breaking = parse_conventional_commit(commit)

        # Build formatted entry
        entry = f"- {description}"
        if scope:
            entry = f"- **{scope}**: {description}"

        # Add commit hash reference
        entry += (
            f" ([`{commit['hash']}`]"
            f"(https://github.com/{repository}/commit/{commit['hash']}))"
        )

        if is_breaking:
            categories['breaking'].append(entry)
        elif commit_type in ['feat', 'feature']:
            categories['features'].append(entry)
        elif commit_type == 'fix':
            categories['fixes'].append(entry)
        elif commit_type in ['perf', 'performance']:
            categories['performance'].append(entry)
        elif commit_type in ['docs', 'doc']:
            categories['documentation'].append(entry)
        elif commit_type in ['style', 'refactor']:
            categories['refactor'].append(entry)
        elif commit_type in ['test', 'tests']:
            categories['tests'].append(entry)
        elif commit_type in ['chore', 'build', 'ci']:
            categories['chore'].append(entry)
        else:
            categories['other'].append(entry)

    return categories


def generate_release_notes():
    """Generate formatted release notes"""
    version_file = PROJECT_ROOT / "VERSION"
    version = version_file.read_text().strip() if version_file.exists() else "Unknown"
    release_tag = os.environ.get("RELEASE_TAG_OVERRIDE", f"v{version}").strip() or f"v{version}"
    repository = get_release_repository()
    tag_ref = quote(release_tag, safe="._-")
    curated_entry = get_curated_changelog_entry(release_tag)
    notes = [f"# {PROJECT_NAME} {release_tag}", ""]

    if curated_entry is not None:
        release_date, changelog_markdown = curated_entry
        if release_date:
            notes.extend([f"**Release date:** {release_date}", ""])
        notes.extend([changelog_markdown, ""])
        source_note = "Generated from the curated CHANGELOG.md release entry."
    else:
        commits = get_git_commits_since_last_tag()
        categories = categorize_commits(commits, repository)
        sections = (
            ("breaking", "## ⚠️ BREAKING CHANGES"),
            ("features", "## ✨ New Features"),
            ("fixes", "## 🐛 Bug Fixes"),
            ("performance", "## ⚡ Performance Improvements"),
            ("refactor", "## ♻️ Code Refactoring"),
            ("documentation", "## 📚 Documentation"),
            ("tests", "## 🧪 Tests"),
            ("chore", "## 🔧 Maintenance"),
            ("other", "## 📦 Other Changes"),
        )
        for category, title in sections:
            if categories[category]:
                notes.extend([title, "", *categories[category], ""])
        if not commits:
            notes.extend(
                [
                    "## Changes",
                    "",
                    (
                        "No conventional commits were found. "
                        f"See the [tag history](https://github.com/{repository}/commits/{tag_ref})."
                    ),
                    "",
                ]
            )
        source_note = (
            "Generated from conventional commits because no exact "
            "CHANGELOG entry was found."
        )

    notes.append("---")
    notes.append("")
    notes.append("## 📥 Installation")
    notes.append("")
    notes.append("```bash")
    notes.append(
        f"git clone --branch {release_tag} --depth 1 "
        f"https://github.com/{repository}.git"
    )
    notes.append("cd mavsdk_drone_show")
    notes.append("# Follow docs/guides/sitl-comprehensive.md for Docker/SITL setup")
    notes.append("```")
    notes.append("")
    notes.append("## 📚 Documentation")
    notes.append("")
    notes.append(f"- [Documentation](https://github.com/{repository}/tree/{tag_ref}/docs)")
    notes.append(f"- [CHANGELOG](https://github.com/{repository}/blob/{tag_ref}/CHANGELOG.md)")
    notes.append(
        f"- [Contributing Guide]"
        f"(https://github.com/{repository}/blob/{tag_ref}/CONTRIBUTING.md)"
    )
    notes.append("")
    notes.append("---")
    notes.append("")
    notes.append(f"**Release tag**: `{release_tag}`")
    notes.append("")
    notes.append(f"*{source_note}*")

    print('\n'.join(notes))


if __name__ == "__main__":
    generate_release_notes()
