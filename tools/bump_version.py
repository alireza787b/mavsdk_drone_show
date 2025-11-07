#!/usr/bin/env python3
"""
Intelligent version bumper for MAVSDK Drone Show

Automatically bumps version based on conventional commits or manual input.
Integrates with existing version_sync.py for consistency.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = PROJECT_ROOT / "VERSION"
CHANGELOG_FILE = PROJECT_ROOT / "CHANGELOG.md"


def get_git_commits_since_last_tag():
    """Get all commit messages since last version tag"""
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
                ["git", "log", f"{last_tag}..HEAD", "--pretty=format:%s"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=True
            )
        else:
            # Get all commits
            result = subprocess.run(
                ["git", "log", "--pretty=format:%s"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=True
            )

        return result.stdout.strip().split('\n') if result.stdout else []

    except subprocess.CalledProcessError:
        print("⚠️  Warning: Could not read git commits, assuming minor bump")
        return []


def analyze_commits(commits):
    """
    Analyze commits to determine version bump type

    Returns: 'major', 'minor', or 'none'
    """
    has_breaking = False
    has_feature_or_fix = False

    breaking_patterns = [
        r'^BREAKING CHANGE:',
        r'^feat.*!:',
        r'^fix.*!:',
    ]

    feature_fix_patterns = [
        r'^feat(\(.+\))?:',
        r'^fix(\(.+\))?:',
    ]

    for commit in commits:
        # Check for breaking changes
        if any(re.match(pattern, commit, re.IGNORECASE) for pattern in breaking_patterns):
            has_breaking = True
            break

        # Check for BREAKING CHANGE in commit body/message
        if 'BREAKING CHANGE' in commit.upper():
            has_breaking = True
            break

        # Check for features or fixes
        if any(re.match(pattern, commit, re.IGNORECASE) for pattern in feature_fix_patterns):
            has_feature_or_fix = True

    if has_breaking:
        return 'major'
    elif has_feature_or_fix:
        return 'minor'
    else:
        return 'none'


def read_current_version():
    """Read current version from VERSION file"""
    if not VERSION_FILE.exists():
        print(f"❌ ERROR: VERSION file not found at {VERSION_FILE}")
        sys.exit(1)

    version = VERSION_FILE.read_text().strip()

    if not re.match(r'^\d+\.\d+$', version):
        print(f"❌ ERROR: Invalid version format '{version}'")
        sys.exit(1)

    return version


def bump_version(current_version, bump_type):
    """
    Bump version based on type

    Args:
        current_version: String like "3.7"
        bump_type: 'major', 'minor', or 'none'

    Returns:
        New version string
    """
    major, minor = map(int, current_version.split('.'))

    if bump_type == 'major':
        major += 1
        minor = 0
    elif bump_type == 'minor':
        minor += 1
    else:
        # No bump
        return current_version

    return f"{major}.{minor}"


def write_version(new_version):
    """Write new version to VERSION file"""
    VERSION_FILE.write_text(f"{new_version}\n")
    print(f"✅ Updated VERSION file to {new_version}")


def update_changelog(new_version, bump_type):
    """Add new version entry to CHANGELOG.md"""
    if not CHANGELOG_FILE.exists():
        print("⚠️  CHANGELOG.md not found, skipping update")
        return

    changelog_content = CHANGELOG_FILE.read_text()

    # Check if version already exists
    if f"## [{new_version}]" in changelog_content:
        print(f"⏭️  Version {new_version} already in CHANGELOG.md")
        return

    today = datetime.now().strftime("%Y-%m-%d")

    # Create new version entry
    new_entry = f"""## [{new_version}] - {today}

### Added
- Automated version bump ({bump_type})

### Changed
- See commit history for detailed changes

---

"""

    # Insert after the header (after the "---" line)
    lines = changelog_content.split('\n')
    insert_index = None

    for i, line in enumerate(lines):
        if line.strip() == '---' and i < 20:  # Find first separator
            insert_index = i + 2  # Insert after separator and blank line
            break

    if insert_index:
        lines.insert(insert_index, new_entry)
        CHANGELOG_FILE.write_text('\n'.join(lines))
        print(f"✅ Updated CHANGELOG.md with version {new_version}")
    else:
        print("⚠️  Could not find insertion point in CHANGELOG.md")


def run_version_sync():
    """Run the version_sync.py script"""
    version_sync_script = PROJECT_ROOT / "tools" / "version_sync.py"

    if not version_sync_script.exists():
        print("⚠️  version_sync.py not found, skipping sync")
        return

    try:
        result = subprocess.run(
            ["python3", str(version_sync_script)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True
        )
        print("✅ Synchronized version across all files")
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running version_sync.py: {e}")
        print(e.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Intelligent version bumper for MAVSDK Drone Show'
    )
    parser.add_argument(
        '--type',
        choices=['auto', 'major', 'minor'],
        default='auto',
        help='Version bump type (auto=detect from commits)'
    )
    parser.add_argument(
        '--manual',
        type=str,
        help='Manually specify version (e.g., 3.8)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would happen without making changes'
    )

    args = parser.parse_args()

    current_version = read_current_version()
    print(f"📌 Current version: {current_version}")

    if args.manual:
        # Manual version override
        new_version = args.manual.strip()

        if not re.match(r'^\d+\.\d+$', new_version):
            print(f"❌ ERROR: Invalid version format '{new_version}'")
            print("   Expected format: X.Y (e.g., 3.8)")
            sys.exit(1)

        bump_type = 'manual'
        print(f"🎯 Manual version specified: {new_version}")

    else:
        # Auto-detect from commits
        if args.type == 'auto':
            commits = get_git_commits_since_last_tag()

            if not commits or commits == ['']:
                print("⏭️  No commits found since last tag, no version bump needed")
                print(current_version)
                sys.exit(0)

            bump_type = analyze_commits(commits)
            print(f"🤖 Analyzed {len(commits)} commit(s)")
            print(f"🔍 Detected bump type: {bump_type}")
        else:
            bump_type = args.type
            print(f"🎯 Manual bump type specified: {bump_type}")

        new_version = bump_version(current_version, bump_type)

    # Check if version changed
    if new_version == current_version:
        print(f"✅ No version change needed (staying at {current_version})")
        print(current_version)
        sys.exit(0)

    print(f"🎉 Version bump: {current_version} → {new_version}")

    if args.dry_run:
        print("🔍 DRY RUN - No changes made")
        print(new_version)
        sys.exit(0)

    # Make changes
    write_version(new_version)
    update_changelog(new_version, bump_type)
    run_version_sync()

    print(f"\n{'='*60}")
    print(f"✅ Version bumped successfully!")
    print(f"{'='*60}")
    print(f"   {current_version} → {new_version}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
