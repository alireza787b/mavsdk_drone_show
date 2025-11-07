# Versioning Guide

**How MAVSDK Drone Show manages versions and releases**

---

## Table of Contents

- [Version Numbering Scheme](#version-numbering-scheme)
- [Single Source of Truth](#single-source-of-truth)
- [Version Synchronization](#version-synchronization)
- [How to Bump Versions](#how-to-bump-versions)
- [Release Workflow](#release-workflow)
- [Where Versions Appear](#where-versions-appear)
- [Manual Override](#manual-override)
- [Best Practices](#best-practices)
- [Examples](#examples)

---

## Version Numbering Scheme

MDS uses **simple two-part versioning**: `X.Y`

### Format: `X.Y`

- **X** (Major): Significant architectural changes, breaking changes, or major new capabilities
  - Example: 3.0 introduced Smart Swarm and unified architecture
- **Y** (Minor): New features, improvements, bug fixes, and non-breaking changes
  - Example: 3.6 added versioning system and documentation restructure

### Why Not Semantic Versioning (X.Y.Z)?

We chose simple `X.Y` versioning because:
- **Clarity**: Easier to communicate and remember
- **Simplicity**: Appropriate for the project's scale
- **Flexibility**: Minor version can include bug fixes and features
- **User-Friendly**: Less confusing for non-developers

---

## Single Source of Truth

The project uses a **VERSION file** as the single source of truth:

```
/root/mavsdk_drone_show/VERSION
```

**Contents:** Just the version number (e.g., `3.6`)

**Why a VERSION file?**
- Easy to read by both humans and scripts
- Version-control friendly (git can track changes)
- Simple to edit manually
- AI-friendly (Claude Code and other tools can easily understand and modify it)

---

## Version Synchronization

The version number must be synchronized across multiple locations:

### Automated Synchronization

Use the `version_sync.py` script to automatically update all locations:

```bash
python tools/version_sync.py
```

**What it updates:**
1. **Python source** (`src/__init__.py`): `__version__ = "3.6"`
2. **Frontend package.json** (`app/dashboard/drone-dashboard/package.json`): `"version": "3.6"`
3. **Frontend version.js** (`app/dashboard/drone-dashboard/src/version.js`): Auto-generated with version + git hash

**What it includes:**
- Current version number
- Git commit hash (for debugging)
- Git branch name
- Display format: `v3.6 (b4afd70)`

---

## How to Bump Versions

### Step-by-Step Process

#### 1. Update the VERSION File

Edit `/root/mavsdk_drone_show/VERSION` and change the version number:

```bash
echo "3.7" > VERSION
```

or edit manually in your text editor.

#### 2. Run Version Sync Script

```bash
python tools/version_sync.py
```

Expected output:
```
============================================================
MAVSDK Drone Show - Version Synchronization
============================================================

📌 Current version: 3.7

📝 Updating src/__init__.py...
   ✅ Updated to version 3.7
📝 Updating app/dashboard/drone-dashboard/package.json...
   ✅ Updated to version 3.7
📝 Generating app/dashboard/drone-dashboard/src/version.js...
   ✅ Generated: v3.7 (a1b2c3d) on main-candidate

============================================================
✅ Version synchronization complete!
============================================================
```

#### 3. Update CHANGELOG.md

Add a new section at the top of `CHANGELOG.md`:

```markdown
## [3.7] - 2025-XX-XX

### Added
- New feature description

### Changed
- What changed

### Fixed
- Bug fixes
```

#### 4. Rebuild Frontend

```bash
cd app/dashboard/drone-dashboard
npm run build
cd ../../..
```

This ensures the new version.js is bundled into the production build.

#### 5. Commit Changes

```bash
git add -A
git commit -m "chore: bump version to 3.7"
```

---

## Release Workflow

MDS uses a **two-branch release workflow**:

### Branch Strategy

```
main-candidate  ←  Development & testing
      ↓
    main  ←  Stable releases only
```

**Branches:**
- **main-candidate**: Active development, new features, testing
- **main**: Stable releases only, production-ready code

### Release Process

#### Phase 1: Development (main-candidate)

1. Develop features on `main-candidate` branch
2. Test thoroughly in SITL environment
3. Version number can be bumped to next minor version early (e.g., `3.7`)
4. Multiple commits during development

#### Phase 2: Prepare Release

1. Ensure all features are complete and tested
2. Update CHANGELOG.md with all changes
3. Update VERSION file if not already done
4. Run `python tools/version_sync.py`
5. Rebuild frontend
6. Commit: `git commit -m "chore: prepare release 3.7"`

#### Phase 3: Merge to Main

```bash
git checkout main
git merge main-candidate
git push origin main
```

#### Phase 4: Create GitHub Release

1. Go to GitHub → Releases → "Draft a new release"
2. Create a new tag: `v3.7`
3. Target: `main` branch
4. Release title: `Version 3.7`
5. Description: Copy from CHANGELOG.md
6. Publish release

### Version Lock

- Version only increments when ready for release
- GitHub release tag (e.g., `v3.7`) locks the version
- No version changes after release except for hotfixes

---

## Where Versions Appear

### User-Visible Locations

| Location | Format | Example | How Updated |
|----------|--------|---------|-------------|
| **Dashboard Sidebar** | `vX.Y (hash)` | `v3.6 (b4afd70)` | Auto (from version.js) |
| **README.md** | `X.Y` | `3.6` | Manual |
| **CHANGELOG.md** | `[X.Y]` | `[3.6]` | Manual |
| **GitHub Releases** | `vX.Y` | `v3.6` | Manual (tag) |

### Developer Locations

| Location | Format | How Updated |
|----------|--------|-------------|
| **VERSION file** | `X.Y` | Manual |
| **src/__init__.py** | `__version__ = "X.Y"` | Auto (version_sync.py) |
| **package.json** | `"version": "X.Y"` | Auto (version_sync.py) |
| **version.js** | Multiple formats | Auto (version_sync.py) |

---

## Manual Override

The versioning system supports manual overrides when needed.

### When to Override?

- Emergency hotfixes
- Custom forks or branches
- Experimental builds
- Special deployments

### How to Override

Simply edit the VERSION file and run the sync script:

```bash
echo "3.6-hotfix1" > VERSION
python tools/version_sync.py
```

**Note:** Non-standard version formats (with suffixes) work but may affect auto-detection in some tools.

---

## Best Practices

### DO

✅ **Always run version_sync.py after changing VERSION**
- Ensures consistency across all files

✅ **Update CHANGELOG.md with every version bump**
- Keeps users informed of changes

✅ **Test after version bump**
- Ensure dashboard displays correct version

✅ **Use meaningful commit messages**
- Example: `chore: bump version to 3.7`

✅ **Rebuild frontend after version changes**
- Ensures version.js is bundled correctly

### DON'T

❌ **Don't edit version.js manually**
- It's auto-generated and will be overwritten

❌ **Don't skip version_sync.py**
- Leads to version inconsistencies

❌ **Don't bump version for every commit**
- Only bump when preparing a release

❌ **Don't merge to main without testing**
- main branch should always be stable

❌ **Don't create GitHub releases from main-candidate**
- Only create releases from main branch

---

## Examples

### Example 1: Minor Feature Release

```bash
# Starting from version 3.6

# 1. Update VERSION file
echo "3.7" > VERSION

# 2. Sync versions
python tools/version_sync.py

# 3. Update CHANGELOG.md (manually edit)
# Add section for [3.7] with changes

# 4. Rebuild frontend
cd app/dashboard/drone-dashboard && npm run build && cd ../../..

# 5. Commit
git add -A
git commit -m "chore: bump version to 3.7 with new trajectory features"

# 6. Merge to main (when ready)
git checkout main
git merge main-candidate
git push origin main

# 7. Create GitHub release v3.7
```

### Example 2: Major Version Bump

```bash
# Starting from version 3.9

# 1. Major architectural change warrants 4.0
echo "4.0" > VERSION

# 2. Sync versions
python tools/version_sync.py

# 3. Update CHANGELOG.md
# Add [4.0] section with breaking changes

# 4. Rebuild frontend
cd app/dashboard/drone-dashboard && npm run build && cd ../../..

# 5. Commit
git add -A
git commit -m "chore: bump version to 4.0 - major architecture overhaul"

# 6. Follow release workflow
```

### Example 3: Hotfix

```bash
# Emergency fix on main branch

# 1. Create hotfix version
echo "3.6" > VERSION  # Keep same version for hotfix

# 2. Make fix in code

# 3. Commit with fix
git add -A
git commit -m "fix: critical safety issue in failsafe module"

# 4. Can optionally create patch release
echo "3.7" > VERSION
python tools/version_sync.py
git add -A
git commit -m "chore: bump to 3.7 for hotfix release"

# 5. Create GitHub release v3.7
```

---

## Validation

### Validate Version Format

Run version_sync.py in validate-only mode:

```bash
python tools/version_sync.py --validate-only
```

Output:
```
✅ Version format valid: 3.6

Would update:
  - src/__init__.py
  - app/dashboard/drone-dashboard/package.json
  - app/dashboard/drone-dashboard/src/version.js

Run without --validate-only to apply changes
```

---

## Troubleshooting

### Version not showing in dashboard?

1. Check version.js exists: `app/dashboard/drone-dashboard/src/version.js`
2. Rebuild frontend: `cd app/dashboard/drone-dashboard && npm run build`
3. Clear browser cache and reload

### Version mismatch across files?

Run version_sync.py again:
```bash
python tools/version_sync.py
```

### Git hash showing "unknown"?

Ensure you're in a git repository:
```bash
git status
```

---

## Summary

**Quick Reference:**

1. **Single Source:** VERSION file
2. **Sync Tool:** `python tools/version_sync.py`
3. **Version Format:** `X.Y` (simple two-part)
4. **Release Branch:** main (stable releases only)
5. **Development Branch:** main-candidate
6. **Manual Override:** Supported (edit VERSION file)

**Version Bump Checklist:**
- [ ] Edit VERSION file
- [ ] Run `python tools/version_sync.py`
- [ ] Update CHANGELOG.md
- [ ] Rebuild frontend (`npm run build`)
- [ ] Commit changes
- [ ] Merge to main (when ready)
- [ ] Create GitHub release

---

## Questions?

If you have questions about versioning or the release process:

- Check [CHANGELOG.md](../CHANGELOG.md) for version history
- Review [README.md](../README.md) for project overview
- Contact: [p30planets@gmail.com](mailto:p30planets@gmail.com)

---

**Document Version:** 1.0 (November 2025)

© 2025 Alireza Ghaderi | Licensed under CC BY-NC-SA 4.0
