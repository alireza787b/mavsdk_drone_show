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

### Documentation
- [ ] CHANGELOG.md updated with all changes
- [ ] README.md updated if needed
- [ ] All new features documented
- [ ] API changes documented

### Version Management
- [ ] VERSION file updated to X.Y
- [ ] `python tools/version_sync.py` executed successfully
- [ ] Frontend rebuilt with `npm run build`
- [ ] Version displayed correctly in dashboard sidebar

### Quality Checks
- [ ] Python syntax validation passed
- [ ] Frontend builds without errors
- [ ] No ESLint warnings (or documented)
- [ ] All links in documentation verified

### Repository
- [ ] All changes committed to main-candidate
- [ ] main-candidate merged to main
- [ ] No uncommitted changes

---

## Release Process

### 1. Create Git Tag

```bash
git checkout main
git tag -a v3.6 -m "Release version 3.6"
git push origin v3.6
```

### 2. Create GitHub Release

1. Go to: https://github.com/alireza787b/mavsdk_drone_show/releases/new
2. Tag version: `v3.6`
3. Target: `main`
4. Release title: `Version 3.6`
5. Description: Copy from CHANGELOG.md (see template below)

---

## Release Notes Template

Copy this template and fill in details from CHANGELOG.md:

```markdown
# MAVSDK Drone Show v3.6

**Release Date:** November 6, 2025

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
git checkout v3.6

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

**Full Changelog**: https://github.com/alireza787b/mavsdk_drone_show/blob/main/CHANGELOG.md
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
- Use semantic version tags: `v3.6`, `v4.0`, etc.
- Include release notes copied from CHANGELOG.md
- Link to documentation and installation guides
- Tag releases for discoverability

---

**Last Updated:** November 2025 (v3.6)
