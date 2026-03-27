# SITL Custom Release Workflow

## Overview

This guide is the source of truth for advanced SITL image maintenance.

Use it when you need one of these workflows:
- maintain your own fork
- maintain a customer-owned private repo
- build a custom validated SITL image
- package a release archive for other users
- keep a large fleet on a pinned tested image instead of mutable latest-on-boot sync

This guide is about the **Docker SITL image workflow**. It does not replace the real-hardware setup guides for Raspberry Pi, Jetson, or field deployment.

If you are aligning GCS, drones, and SITL around the same customer repo/branch, read [Custom Repo Workflow](custom-repo-workflow.md) first.

## Choose The Right Workflow

| Goal | Recommended workflow |
|------|----------------------|
| Quick evaluation on a fresh VPS | Use the official public archive and `mavsdk-drone-show-sitl:latest` |
| Active development on your own fork | Use runtime git sync with `MDS_SITL_GIT_SYNC=true` |
| Customer delivery or stable demo image | Rebuild a validated image, package it, and deploy with `MDS_SITL_GIT_SYNC=false` |
| Large fleet, 100+ containers | Use a pinned rebuilt image with `MDS_SITL_GIT_SYNC=false` and usually `MDS_SITL_REQUIREMENTS_SYNC=false` |

## Core Rules

- Do not use `docker commit` as the normal release workflow.
- Treat running containers as disposable runtime instances, not as the source of truth.
- Commit changes to git first, then rebuild a clean image.
- Keep PX4 and the baked `mavsdk_server` pinned inside the image and update them only through a validated image rebuild.
- Use runtime git sync only when you intentionally want mutable latest-on-boot behavior.

## What Container Startup Actually Syncs

When `MDS_SITL_GIT_SYNC=true`:
- the container fetches and hard-resets the `mavsdk_drone_show` repo to the configured branch
- untracked MDS files are cleaned, while runtime artifacts such as `venv/`, `logs/`, `*.hwID`, and the baked `mavsdk_server` are preserved

What it does **not** auto-update:
- PX4 source tree
- PX4 build outputs
- system packages
- baked `mavsdk_server`

That means runtime git sync is useful for development, but it is not a full image refresh and not a reproducible release process.
For private GitHub repos, add `MDS_GIT_AUTH_TOKEN` during mutable runtime sync or image preparation; plain HTTPS alone will not clone a private repo.

## Official Tested Archive Workflow

For the shared official image:

1. Download the public archive described in [SITL Comprehensive Guide](sitl-comprehensive.md).
2. Load it with `docker load`.
3. Start containers with:

```bash
bash multiple_sitl/create_dockers.sh 2
```

For stable validated runs, prefer:

```bash
export MDS_SITL_GIT_SYNC=false
export MDS_SITL_REQUIREMENTS_SYNC=false
bash multiple_sitl/create_dockers.sh 2
```

## Development Workflow On Your Fork

Use this when you want containers to pull the latest committed MDS code from your fork or customer repo on boot.

```bash
export MDS_REPO_URL="https://github.com/YOURORG/YOURREPO.git"
export MDS_BRANCH="your-branch"
export MDS_SITL_GIT_SYNC=true
export MDS_SITL_REQUIREMENTS_SYNC=true

bash multiple_sitl/create_dockers.sh 2
```

Recommended rules:
- commit and push before testing changes that must survive container recreation
- do not rely on editing files inside running containers
- rebuild the image once the fork state is approved and needs to become a stable release
- for private repos, make sure the runtime environment can authenticate before you rely on mutable boot sync

## Build A Clean Custom Image

When your fork or customer-specific branch is approved, build a clean image from git:

```bash
export MDS_REPO_URL="https://github.com/YOURORG/YOURREPO.git"
export MDS_BRANCH="your-release-branch"

bash tools/build_custom_image.sh \
  "$MDS_REPO_URL" \
  "$MDS_BRANCH" \
  "yourcompany-mds-sitl:v5-custom"
```

Notes:
- the builder keeps one prebuilt Python venv
- PX4 stays pinned in the image with real git and submodule metadata intact
- the final image is flattened so old `docker commit` layer history does not accumulate
- export `MDS_MAVSDK_VERSION` or `MDS_MAVSDK_URL` before building if you intentionally want a different baked `mavsdk_server`
- export `MDS_SITL_KEEP_ARM_TOOLCHAIN=true` before building only if your custom image intentionally needs the PX4 ARM toolchain
- for private repos, prefer authenticated HTTPS or another pre-authenticated Git path during image preparation

## Rebuild And Package A Validated Release

If you want a stable distributable release, use the release helper instead of hand-running multiple steps:

```bash
bash tools/release_sitl_image.sh \
  --base-image mavsdk-drone-show-sitl:latest \
  --image-repo yourcompany-mds-sitl \
  --version-tag v5-custom \
  --repo-url "https://github.com/YOURORG/YOURREPO.git" \
  --branch "your-release-branch" \
  --package
```

This does all of the following:
- prepares a clean release filesystem
- preserves PX4 provenance metadata
- tags the image as `latest`, the release tag, and the baked commit tag
- exports a stable archive basename
- verifies the resulting `.7z`
- writes checksum and manifest files

If you only need packaging for an already-built image:

```bash
bash tools/package_sitl_image.sh \
  --image-repo yourcompany-mds-sitl \
  --version-tag v5-custom
```

## Recommended Deployment Mode For Large Fleets

For customer demos, stable testing, or 100+ containers:

```bash
export MDS_DOCKER_IMAGE="yourcompany-mds-sitl:v5-custom"
export MDS_SITL_GIT_SYNC=false
export MDS_SITL_REQUIREMENTS_SYNC=false

bash multiple_sitl/create_dockers.sh 100
```

Why:
- avoids one git fetch per container at boot
- avoids one Python dependency sync per container at boot
- keeps startup faster and more repeatable
- ensures every container is running the same validated image state

## When To Leave Runtime Sync Enabled

Keep `MDS_SITL_GIT_SYNC=true` only when you explicitly want:
- mutable development behavior
- rapid testing of new committed branch changes
- a temporary staging environment that follows the latest MDS branch content on boot

Do not confuse that mode with a pinned release.

## Archive Naming And Versioning

Best practice for shared release archives:
- keep one stable archive filename
- let Docker tags carry the release version

Example:
- archive file: `mavsdk-drone-show-sitl-image.7z`
- image tags inside archive: `mavsdk-drone-show-sitl:latest`, `mavsdk-drone-show-sitl:v5`, `mavsdk-drone-show-sitl:c2f6e88`

This keeps the download instructions stable while still preserving release traceability.

## MEGA Distribution Workflow

For authenticated archive management, prefer the official `MEGAcmd` client.

Do not rely on third-party `megatools` for authenticated account replacement workflows. In practice, modern MEGA account protections can cause `megals`/`megaput` login failures such as `HTTP POST failed: Server returned 402` even when browser login is fine. Use `MEGAcmd` for:

- `mega-login`
- `mega-ls`
- `mega-put`
- `mega-export`
- `mega-rm`

Typical release flow:
1. package the image archive locally or on the release host
2. upload the new `.7z`, checksum, and manifest
3. update or replace the public shared link
4. remove obsolete release artifacts you no longer want to keep
5. update the public docs link only after the new upload is confirmed

If you maintain your own customer distribution, document:
- which tag is the approved release
- which archive file is the public download
- whether older archives are retained or replaced

## Recommended Maintenance Policy

For official shared releases:
- validate on the release image first
- publish `latest` plus the current release tag
- update docs only after the archive is uploaded and tested

For custom fork maintainers:
- develop on your fork with runtime sync if convenient
- cut a clean rebuilt image once approved
- deploy the rebuilt image with runtime sync disabled for stable fleets

For PX4 updates:
- do not patch around PX4 internals casually
- update PX4 through a deliberate rebuild and revalidation pass
- preserve PX4 git and submodule metadata in the image for provenance and maintenance

## Related Guides

- [SITL Comprehensive Guide](sitl-comprehensive.md)
- [Advanced SITL Configuration Guide](advanced-sitl.md)
- [Documentation Index](../README.md)
