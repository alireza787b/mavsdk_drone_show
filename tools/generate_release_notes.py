#!/usr/bin/env python3
"""
Release notes generator for MAVSDK Drone Show

Generates formatted release notes from conventional commits.
"""

import subprocess
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


def categorize_commits(commits):
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
        entry += f" ([`{commit['hash']}`](https://github.com/alireza787b/mavsdk_drone_show/commit/{commit['hash']}))"

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
    # Read current version
    version_file = PROJECT_ROOT / "VERSION"
    version = version_file.read_text().strip() if version_file.exists() else "Unknown"

    commits = get_git_commits_since_last_tag()

    if not commits:
        print(f"""# Release v{version}

## Changes

No conventional commits found. See [commit history](https://github.com/alireza787b/mavsdk_drone_show/commits/main) for details.

---

🤖 *Auto-generated release notes*
""")
        return

    categories = categorize_commits(commits)

    # Build release notes
    notes = [f"# MAVSDK Drone Show v{version}", ""]

    # Breaking changes (if any)
    if categories['breaking']:
        notes.append("## ⚠️ BREAKING CHANGES")
        notes.append("")
        notes.extend(categories['breaking'])
        notes.append("")

    # Features
    if categories['features']:
        notes.append("## ✨ New Features")
        notes.append("")
        notes.extend(categories['features'])
        notes.append("")

    # Fixes
    if categories['fixes']:
        notes.append("## 🐛 Bug Fixes")
        notes.append("")
        notes.extend(categories['fixes'])
        notes.append("")

    # Performance
    if categories['performance']:
        notes.append("## ⚡ Performance Improvements")
        notes.append("")
        notes.extend(categories['performance'])
        notes.append("")

    # Refactoring
    if categories['refactor']:
        notes.append("## ♻️ Code Refactoring")
        notes.append("")
        notes.extend(categories['refactor'])
        notes.append("")

    # Documentation
    if categories['documentation']:
        notes.append("## 📚 Documentation")
        notes.append("")
        notes.extend(categories['documentation'])
        notes.append("")

    # Tests
    if categories['tests']:
        notes.append("## 🧪 Tests")
        notes.append("")
        notes.extend(categories['tests'])
        notes.append("")

    # Chore
    if categories['chore']:
        notes.append("## 🔧 Maintenance")
        notes.append("")
        notes.extend(categories['chore'])
        notes.append("")

    # Other
    if categories['other']:
        notes.append("## 📦 Other Changes")
        notes.append("")
        notes.extend(categories['other'])
        notes.append("")

    # Footer
    notes.append("---")
    notes.append("")
    notes.append("## 📥 Installation")
    notes.append("")
    notes.append("```bash")
    notes.append("git clone https://github.com/alireza787b/mavsdk_drone_show.git")
    notes.append("cd mavsdk_drone_show")
    notes.append("# Follow docs/sitl_demo_docker.md for Docker setup")
    notes.append("```")
    notes.append("")
    notes.append("## 📚 Documentation")
    notes.append("")
    notes.append("- [Documentation](https://github.com/alireza787b/mavsdk_drone_show/tree/main/docs)")
    notes.append("- [CHANGELOG](https://github.com/alireza787b/mavsdk_drone_show/blob/main/CHANGELOG.md)")
    notes.append("- [Contributing Guide](https://github.com/alireza787b/mavsdk_drone_show/blob/main/CONTRIBUTING.md)")
    notes.append("")
    notes.append("---")
    notes.append("")
    notes.append(f"**Full Changelog**: [View all changes](https://github.com/alireza787b/mavsdk_drone_show/compare/v{version}...v{version})")
    notes.append("")
    notes.append("🤖 *Auto-generated release notes*")

    print('\n'.join(notes))


if __name__ == "__main__":
    generate_release_notes()
