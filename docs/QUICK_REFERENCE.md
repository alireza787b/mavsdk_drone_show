# Quick Reference - Automated Releases

**🚀 For Developers & AI: How to work with automated versioning**

---

## **TL;DR - 3 Steps**

```bash
# 1. Commit with conventional format
git commit -m "feat: add new feature"

# 2. Create PR and merge to main

# 3. Done! Release happens automatically
```

---

## **Commit Message Format**

```
<type>: <description>
```

### **Quick Table**

| Type | Version | Example |
|------|---------|---------|
| `feat:` | 3.7 → **3.8** | `feat: add trajectory editor` |
| `fix:` | 3.7 → **3.8** | `fix: resolve GPS timeout` |
| `feat!:` | 3.7 → **4.0** | `feat!: breaking API change` |
| `docs:` | 3.7 → 3.7 | `docs: update README` |
| `chore:` | 3.7 → 3.7 | `chore: cleanup files` |
| `refactor:` | 3.7 → 3.7 | `refactor: restructure code` |
| `test:` | 3.7 → 3.7 | `test: add unit tests` |
| `style:` | 3.7 → 3.7 | `style: fix formatting` |
| `perf:` | 3.7 → 3.7 | `perf: optimize algorithm` |

---

## **Good Examples ✅**

```bash
feat: add swarm trajectory smoother
fix: resolve modal centering issue
feat(dashboard): add dark mode toggle
fix(gcs): resolve WebSocket timeout
docs: update installation guide
chore: cleanup deprecated files
refactor(api): restructure endpoints
test: add trajectory validation tests
```

---

## **Bad Examples ❌**

```bash
Updated files               # No type
Fixed bug                   # Too vague
feat added feature          # Missing colon
FIX: Bug in code           # Uppercase
feature: new thing         # Wrong type name
```

---

## **With Scope (Better)**

```bash
feat(scope): description

# Examples:
feat(dashboard): add real-time telemetry
fix(api): resolve timeout issue
docs(install): update Docker guide
chore(deps): update dependencies
```

**Scopes:** `dashboard`, `gcs`, `api`, `docs`, `drone`, `core`, `config`

---

## **Breaking Changes**

```bash
# Method 1: Use ! suffix
feat!: remove deprecated API

# Method 2: Use footer
feat: update authentication

BREAKING CHANGE: OAuth 2.0 now required.
Old API keys no longer work.
```

---

## **What Happens Automatically**

```
Merge to main
     ↓
[Automated Release Workflow]
     ↓
✅ Analyzes commits
✅ Bumps version (3.7 → 3.8)
✅ Updates CHANGELOG.md
✅ Syncs all files (Python, JS, package.json)
✅ Creates git tag (v3.8)
✅ Creates GitHub Release
✅ Generates release notes
     ↓
✅ Version 3.8 Released!
```

---

## **Manual Override**

**GitHub UI:**
1. Go to: **Actions** → **Automated Release**
2. Click: **Run workflow**
3. Enter: Custom version or select bump type
4. Click: **Run**

**Command Line:**
```bash
# Test what would happen (dry-run)
python3 tools/bump_version.py --dry-run --type auto

# Manually bump to 3.8
python3 tools/bump_version.py --manual 3.8

# Auto-detect and bump
python3 tools/bump_version.py --type auto
```

---

## **For AI Assistants (Claude, etc.)**

### **When creating commits:**
```python
# Template:
f"{type}: {description}"

# Rules:
# - type: feat|fix|docs|chore|refactor|test|style|perf
# - description: lowercase, imperative mood, no period
# - Use feat! or fix! for breaking changes
```

### **When bumping versions manually:**
```bash
# Read current version
cat VERSION  # Returns: 3.7

# Bump version
python3 tools/bump_version.py --manual 3.8

# Verify
cat VERSION  # Returns: 3.8
```

### **File locations:**
- **VERSION file:** `/root/mavsdk_drone_show/VERSION`
- **Automation scripts:** `/root/mavsdk_drone_show/tools/`
- **Workflows:** `/root/mavsdk_drone_show/.github/workflows/`
- **Docs:** `/root/mavsdk_drone_show/docs/VERSIONING.md`

---

## **Validation**

### **Before PR:**
```bash
# Validate your commits locally
python3 tools/validate_commits.py
```

### **During PR:**
- Bot automatically validates
- Bot comments with predicted version
- Fix any validation errors

---

## **Troubleshooting**

| Issue | Solution |
|-------|----------|
| "Invalid commit format" | Use `type: description` format |
| "No version change" | Ensure you used `feat:` or `fix:` |
| "Workflow didn't run" | Check if merged to `main` (not main-candidate) |
| "Wrong version bumped" | Check commit messages for breaking change markers |

---

## **Quick Commands**

```bash
# Check current version
cat VERSION

# Test version bump (no changes)
python3 tools/bump_version.py --dry-run --type auto

# Generate release notes preview
python3 tools/generate_release_notes.py

# Validate commits
python3 tools/validate_commits.py

# Manual version bump
python3 tools/bump_version.py --manual 3.8

# Run version sync
python3 tools/version_sync.py
```

---

## **Summary**

| What | How |
|------|-----|
| **Format** | `type: description` |
| **Version bump** | `feat:` or `fix:` → minor, `feat!:` → major |
| **Automation** | Merge to `main` triggers release |
| **Manual** | Actions → Run workflow, or use `bump_version.py` |
| **Validation** | Automatic on PR, or run `validate_commits.py` |

---

## **Learning Resources**

- **Full Guide:** [docs/VERSIONING.md](VERSIONING.md)
- **Contributing:** [../CONTRIBUTING.md](../CONTRIBUTING.md)
- **Conventional Commits:** https://www.conventionalcommits.org/
- **Examples:** See git log for real examples

---

## **Version History**

- **v3.7** - Automated release system implemented
- **v3.6** - Documentation restructure and versioning system
- **v3.5** - Production UI/UX improvements

See [CHANGELOG.md](../CHANGELOG.md) for full history.

---

**Last Updated:** 2025-11-07
**Automation Version:** 1.0
**Project:** MAVSDK Drone Show
