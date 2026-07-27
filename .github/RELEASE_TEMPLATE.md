# Release Checklist & Template

**Version:** X.Y

**Release Date:** YYYY-MM-DD

---

## Pre-Release Checklist

Before creating the release, ensure all items are completed:

### Code & Testing
- [ ] All features tested in SITL environment
- [ ] All known bugs fixed or documented
- [ ] Code reviewed and approved
- [ ] No critical security vulnerabilities
- [ ] Release CI includes all changed security, runtime, API, and ULog tests

### Documentation
- [ ] CHANGELOG.md updated with all changes
- [ ] CHANGELOG.md contains an exact section for the intended tag without the `v` prefix
- [ ] README.md updated if needed
- [ ] All new features documented
- [ ] API changes documented

### Version Management
- [ ] VERSION checked: updated for stable release, intentionally unchanged for beta
- [ ] Stable metadata synchronized by `tools/version_sync.py`
- [ ] Frontend rebuilt with `npm run build:release`
- [ ] Frontend build provenance resolves to the immutable release commit and tag
- [ ] Version displayed correctly in dashboard sidebar

### Quality Checks
- [ ] Python syntax validation passed
- [ ] Frontend builds without errors
- [ ] No ESLint warnings (or documented)
- [ ] All links in documentation verified
- [ ] Python and frontend package metadata refer to the canonical root `LICENSE`

### Repository
- [ ] All changes committed to main
- [ ] `main` contains the validated release commit
- [ ] No uncommitted changes
- [ ] Release is dispatched from `alireza787b/mavsdk_drone_show`, not a client fork

---

## Release Process

Publish beta and stable releases only through the **Automated Release**
workflow in the official repository, dispatched from `main`.

1. Confirm the intended release section exists in `CHANGELOG.md`.
2. Open **Actions → Automated Release → Run workflow** in
   `alireza787b/mavsdk_drone_show`.
3. For a beta, keep `VERSION` at the current stable `X.Y`, leave the stable
   version input empty, and provide an immutable tag such as
   `vX.Y.N-simurgh-operator-beta`.
4. For a stable release, leave the prerelease tag empty and select an explicit
   version or reviewed bump type.
5. Review the completed quality gates and generated release before announcing
   it.

For stable releases, the workflow synchronizes package metadata and the npm
lockfile, creates the version commit locally, retests that exact commit, and
only then pushes, tags, and publishes it. For beta releases, it tags the already
validated `main` commit without changing the stable `X.Y` product version.
Stable branch and tag refs are pushed atomically. Release publication is
blocked in downstream/client forks.

Do not manually create or move a release tag. If the workflow fails before
release refs are pushed, fix the cause and rerun it from a clean official
`main`. If the immutable tag exists but GitHub Release publication fails, verify
the tag and complete publication from that same tag; never replace or move it.

---

## Release Notes Template

The workflow uses the exact target section from `CHANGELOG.md` and generates
tag-pinned installation and documentation links. Use this only as a review
guide for the curated changelog entry:

```markdown
# MDS - Mission-Directed Swarm vX.Y

**Release Date:** YYYY-MM-DD

## Highlights

[Brief 2-3 sentence summary of major changes]

## What's New

### Added
- Feature 1 description
- Feature 2 description

### Changed
- Change 1 description
- Change 2 description

### Fixed
- Bug fix 1
- Bug fix 2

## Documentation

📖 [Full Changelog](CHANGELOG.md)
📖 [Documentation Index](docs/README.md)
📖 [Versioning Guide](docs/VERSIONING.md)

## Installation

### SITL Demo (Recommended for Testing)

```bash
# Clone repository
git clone https://github.com/alireza787b/mavsdk_drone_show.git
cd mavsdk_drone_show

# Checkout this version
git checkout vX.Y

# Follow SITL guide
```

📖 [Complete SITL Setup Guide](docs/guides/sitl-comprehensive.md)

### Python Requirements

**Requires Python 3.11, 3.12, or 3.13**

See [Python Compatibility Guide](docs/guides/python-compatibility.md)

## Upgrade Notes

[Any breaking changes or migration steps users need to know]

## Known Issues

[List any known issues or limitations in this release]

## Contributors

Thanks to all contributors who helped make this release possible!

---

## 🏢 Commercial Support

For production deployments, custom features, or hardware implementation assistance:
- Email: p30planets@gmail.com
- LinkedIn: [Alireza Ghaderi](https://www.linkedin.com/in/alireza787b/)

---

**Full Changelog**: https://github.com/alireza787b/mavsdk_drone_show/blob/vX.Y/CHANGELOG.md
```

---

## Post-Release

After creating the release:

- [ ] Verify release appears on GitHub
- [ ] Test download link works
- [ ] Announce on social media (LinkedIn, etc.)
- [ ] Update any external documentation
- [ ] Create announcement (if major release)

---

## Notes

- Releases should only be created from the `main` branch
- Release publication is allowed only in `alireza787b/mavsdk_drone_show`
- Use stable version tags such as `v3.6` or `v4.0`
- Use `vX.Y.N-descriptive-beta` tags for prereleases; never move an existing tag
- Keep the exact release entry in CHANGELOG.md before dispatching the workflow
- Keep release documentation and installation links pinned to the target tag
- Tag releases for discoverability

---

**Last Updated:** July 2026
