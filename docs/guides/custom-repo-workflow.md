# Custom Repo Workflow

## Overview

Use this guide when MDS must run against a customer-owned GitHub repository instead of the official public repo.

Typical reasons:
- private customer infrastructure
- customer-specific config, shows, or UI changes
- a dedicated demo branch
- a validated custom SITL image for redistribution
- keeping a customer repo in sync with official MDS upstream over time

This guide is the source of truth for:
- custom repo and branch selection
- where each component stores that selection
- SSH vs HTTPS recommendations
- writable vs read-only Git workflows
- upstream sync strategy
- GitHub public-fork versus private-customer decisions

It complements these guides:
- [GCS Setup Guide](gcs-setup.md)
- [MDS Init Setup Guide](mds-init-setup.md)
- [Advanced SITL Guide](advanced-sitl.md)
- [SITL Custom Release Workflow](sitl-custom-release-workflow.md)
- [Git Sync System](../features/git-sync.md)

## First Decisions

Before touching a customer deployment, decide these five things:

1. Which repo is the customer source of truth?
2. Which branch should GCS, drones, and SITL follow?
3. Does the GCS need write-back (`MDS_GIT_AUTO_PUSH=true`) or read-only behavior?
4. Will SITL stay mutable on boot (`MDS_SITL_GIT_SYNC=true`) or use a pinned validated image?
5. How will the customer repo receive official MDS updates later?

If these are not decided first, the rest becomes noisy and hard to reason about.

## Single Source Of Truth

Use the same variable names everywhere:

| Target | Source of truth | Keys |
|--------|-----------------|------|
| GCS | `/etc/mds/gcs.env` | `MDS_REPO_URL`, `MDS_BRANCH`, `MDS_GIT_AUTO_PUSH` |
| Real drone hardware | `/etc/mds/local.env` and `/etc/mds/node_identity.json` | `MDS_REPO_URL`, `MDS_BRANCH`, node-local bootstrap identity |
| SITL runtime | exported shell env before launch | `MDS_REPO_URL`, `MDS_BRANCH`, optional `MDS_GIT_AUTH_TOKEN_FILE`, optional `MDS_DOCKER_IMAGE` |
| GCS backend defaults | `src/params.py` | fallback only when env files are absent |

Important rules:
- prefer `MDS_REPO_URL` and `MDS_BRANCH` over editing hardcoded defaults
- treat `src/params.py` as a fallback, not the primary customer customization point
- for hardware and GCS, let the init scripts write `/etc/mds/*.env`
- for SITL, export variables explicitly or bake them into a validated custom image workflow

## Access Model

| Target | Recommended access | Why |
|--------|--------------------|-----|
| GCS with dashboard write-back | SSH deploy key or another non-interactive writable Git credential | config/show saves may need commit + push |
| GCS read-only evaluation | HTTPS + `MDS_GIT_AUTO_PUSH=false` | simplest safe demo path |
| Real drones | SSH deploy key or HTTPS read-only | drones normally pull only |
| SITL development (public repo) | HTTPS | easiest when many containers come and go |
| SITL development (private GitHub repo) | authenticated HTTPS via `MDS_GIT_AUTH_TOKEN_FILE` | easiest non-interactive path for many containers without leaking the token into process args |
| Custom SITL image build for private repo | authenticated HTTPS via `MDS_GIT_AUTH_TOKEN_FILE` or a pre-authenticated build environment | build happens inside a containerized prep flow |

Practical recommendation:
- GCS: SSH if it must push customer changes
- GCS private read-only demo/evaluation: explicit `https://github.com/...git` plus `MDS_GIT_AUTH_TOKEN_FILE`
- drones: SSH if customer wants private repo pull access, HTTPS if repo is public and read-only is fine
- SITL: HTTPS for public repos; for private GitHub repos, use `MDS_GIT_AUTH_TOKEN_FILE` unless you deliberately provision SSH credentials into the build/runtime environment

Important GitHub note:
- use a dedicated long-lived read-only GitHub credential file for documented private HTTPS bootstrap/runtime flows
- GitHub temporary clone tokens are useful for validation, but they expire quickly and are not the recommended operator workflow
- a GitHub CLI auth token is not guaranteed to work for Git-over-HTTPS clone/fetch on every host, so do not document `gh auth token` as the standard bootstrap credential

## GitHub Fork Versus Private Mirror

GitHub behavior matters here:

- GitHub keeps all forks in a fork network on the same visibility, so a fork of the public upstream stays public and cannot simply be flipped private later
- that is fine for open collaboration or public demos
- that is not the right answer when the customer needs confidential configs, UI changes, or mission assets

For confidentiality-sensitive customers, prefer:

1. keep `alireza787b/mavsdk_drone_show` as the public upstream
2. create an org-owned private repo
3. seed it from the official repo
4. keep a documented upstream-sync process

That private repo can still track `main` or `main-candidate`, but it should be treated as a private mirror/customization repo, not assumed to be a private fork.

## `--fork` Versus `--repo-url`

There are now two clean ways to target a customer repo:

### `--fork`

Use this when the customer repo lives on GitHub and you want a short shorthand.

Supported values:
- `--fork youruser`
- `--fork yourorg/customer-mds`

Behavior:
- `OWNER` becomes `OWNER/mavsdk_drone_show`
- `OWNER/REPO` keeps the explicit repo name

### `--repo-url`

Use this when you want full explicit control.

Examples:

```bash
--repo-url https://github.com/yourorg/customer-mds.git
--repo-url git@github.com:yourorg/customer-mds.git
```

Recommendation:
- use `--fork` for quick GitHub bootstrap
- use `--repo-url` in long-lived customer docs and automation because it is fully explicit
- the bootstrap installers now support both forms, so explicit `--repo-url` no longer needs an environment-variable workaround

## GCS Workflow

For a customer-owned GitHub repo with dashboard write-back:

```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_gcs.sh | \
  sudo bash -s -- \
  --fork yourorg/customer-mds \
  --branch customer-demo
```

Or with an explicit URL:

```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_gcs.sh | \
  sudo bash -s -- \
  --repo-url git@github.com:yourorg/customer-mds.git \
  --branch customer-demo
```

For a private read-only demo/evaluation repo with deploy keys disabled:

```bash
install -m 600 /dev/null /root/.mds_git_read_token
printf '%s' 'YOUR_READ_ONLY_GITHUB_TOKEN' > /root/.mds_git_read_token

curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_gcs.sh | \
  sudo bash -s -- \
  --repo-url https://github.com/yourorg/customer-mds.git \
  --branch customer-demo \
  --git-auth-token-file /root/.mds_git_read_token \
  -y
```

Or from an already-cloned repo:

```bash
sudo ./tools/mds_gcs_init.sh \
  --repo-url git@github.com:yourorg/customer-mds.git \
  --branch customer-demo
```

What matters after install:
- `/etc/mds/gcs.env` stores `MDS_REPO_URL`, `MDS_BRANCH`, and `MDS_GIT_AUTO_PUSH`
- `app/linux_dashboard_start.sh` exports those values before backend startup
- dashboard saves/imports use those values for commit/push behavior
- repo-local `core.sshCommand` is pinned when SSH is used, so pre-existing `~/.ssh/config` GitHub identities do not silently hijack the intended MDS deploy key
- rerunning `mds_gcs_init.sh` with a different repo, branch, or access mode now rewrites `/etc/mds/gcs.env` accordingly, even in non-interactive mode, so launcher state does not drift behind the selected repo

First-time SSH note:
- the official bootstrap wrapper now prepares the deploy key before the first private clone
- a non-interactive `-y` run still only succeeds if that deploy key is already authorized on GitHub
- otherwise run the wrapper interactively once, authorize the key, and continue from the same flow

If the GCS repo is intentionally read-only:

```bash
MDS_GIT_AUTO_PUSH=false
```

That is the correct safe setting for evaluation setups.
The same token-file path is now preserved into `/etc/mds/gcs.env` and the runtime git-sync path, so bootstrap and later launcher sync use one source of truth instead of separate ad hoc credentials.

## Real Drone Workflow

For a drone that should follow the customer repo:

```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_mds_node.sh | \
  sudo bash -s -- \
  -d 1 \
  --fork yourorg/customer-mds \
  --branch customer-demo \
  -y
```

Or:

```bash
curl -fsSL https://raw.githubusercontent.com/alireza787b/mavsdk_drone_show/main-candidate/tools/install_mds_node.sh | \
  sudo bash -s -- \
  -d 1 \
  --repo-url git@github.com:yourorg/customer-mds.git \
  --branch customer-demo \
  -y
```

Or from an already-cloned repo:

```bash
sudo ./tools/mds_node_init.sh \
  -d 1 \
  --repo-url git@github.com:yourorg/customer-mds.git \
  --branch customer-demo \
  -y
```

What matters after install:
- `/etc/mds/local.env` stores the chosen `MDS_REPO_URL` and `MDS_BRANCH`
- `/etc/mds/node_identity.json` keeps the machine-readable node identity separate from fleet enrollment state
- boot-time `git_sync_mds.service` sources `/etc/mds/local.env`
- operator-triggered `UPDATE_CODE` now also loads `/etc/mds/local.env`, so boot sync and runtime sync use the same repo/branch
- repo-local `core.sshCommand` is pinned when SSH is used, so pre-existing host SSH config does not silently override the intended deploy key

This removes a major source of drift between startup behavior and dashboard-triggered sync.

First-time SSH note:
- the official bootstrap wrapper now prepares the deploy key before the first private clone
- a non-interactive `-y` run still only succeeds if that deploy key is already authorized on GitHub
- otherwise run the wrapper interactively once, authorize the key, and continue from the same flow

## Enrollment And Node Sync

For real hardware, repo selection and enrollment are separate:

1. bootstrap the node with the intended repo/branch
2. let it announce to GCS as a fleet candidate
3. accept, replace, or recover it in **Fleet Enrollment**
4. sync the affected node after enrollment so its local repo/config state matches the new fleet manifest

Do not treat heartbeat discovery as acceptance, and do not assume enrollment alone rewrites the running node state.

## SITL Workflow

For mutable development SITL:

```bash
export MDS_REPO_URL="https://github.com/yourorg/customer-mds.git"
export MDS_BRANCH="customer-demo"
export MDS_SITL_GIT_SYNC=true
export MDS_SITL_REQUIREMENTS_SYNC=true

bash multiple_sitl/create_dockers.sh 5
```

For a private GitHub repo, add an authenticated token file:

```bash
export MDS_REPO_URL="https://github.com/yourorg/customer-mds.git"
export MDS_BRANCH="customer-demo"
install -m 600 /dev/null ~/.mds_git_read_token
printf '%s' 'YOUR_READ_ONLY_GITHUB_TOKEN' > ~/.mds_git_read_token
export MDS_GIT_AUTH_TOKEN_FILE="$HOME/.mds_git_read_token"
export MDS_GIT_AUTH_USERNAME="x-access-token"
export MDS_SITL_GIT_SYNC=true
export MDS_SITL_REQUIREMENTS_SYNC=true

bash multiple_sitl/create_dockers.sh 5
```

Legacy fallback:
- `MDS_GIT_AUTH_TOKEN` still works if you already have automation built around it
- `MDS_GIT_AUTH_TOKEN_FILE` is now preferred because the launcher/builder can pass only a mounted secret file path into containers instead of placing the raw token in process arguments

For a pinned validated customer image:

```bash
export MDS_DOCKER_IMAGE="yourorg-mds-sitl:v5-customer"
export MDS_SITL_GIT_SYNC=false
export MDS_SITL_REQUIREMENTS_SYNC=false

bash multiple_sitl/create_dockers.sh 5
```

Use mutable boot sync for active development.
Use a pinned image for professional demos, large fleets, and repeatable validation.
For private GitHub SITL, the cleanest large-fleet path is usually a rebuilt custom image plus `MDS_SITL_GIT_SYNC=false`.

## Custom SITL Image Workflow

If the customer repo is approved and must become a stable release image:

```bash
export MDS_REPO_URL="https://github.com/yourorg/customer-mds.git"
export MDS_BRANCH="customer-demo"

bash tools/release_sitl_image.sh \
  --base-image mavsdk-drone-show-sitl:latest \
  --image-repo yourorg-mds-sitl \
  --version-tag v5-customer \
  --repo-url "$MDS_REPO_URL" \
  --branch "$MDS_BRANCH" \
  --package
```

Important:
- this rebuilds the image from git
- PX4 and the baked `mavsdk_server` stay pinned inside the image
- the final image is the correct artifact for redistribution
- do not use `docker commit` as the release workflow

For private repo builds, make sure the build environment has real Git access. Authenticated HTTPS via `MDS_GIT_AUTH_TOKEN_FILE` is usually easier than injecting SSH keys into the containerized image-prep flow.

## Upstream Sync Strategy

Recommended model:
- customer repo = `origin`
- official MDS repo = `upstream`

Inside the customer repo:

```bash
git remote add upstream https://github.com/alireza787b/mavsdk_drone_show.git
git fetch upstream
```

Then choose one policy:

| Policy | When to use it |
|--------|----------------|
| merge upstream into customer branch | easiest operational history |
| rebase customer branch on upstream | cleaner history, requires more Git discipline |
| cherry-pick selected upstream commits | strict change control |

Recommendation for most customers:
- keep the running branch on the customer repo
- pull official changes into a staging branch first
- validate in SITL
- then promote to the customer production/demo branch

Do not point customer drones straight at the official repo if the customer expects their own config, UI, or mission assets to remain authoritative.

## What Changes When You Leave The Official Repo

These areas matter:

| Area | What changes |
|------|--------------|
| GCS bootstrap | choose customer repo/branch and write `/etc/mds/gcs.env` |
| Hardware bootstrap | choose customer repo/branch and write `/etc/mds/local.env` |
| Dashboard save/import flow | may need writable Git credentials |
| SITL launch | export `MDS_REPO_URL` / `MDS_BRANCH` or use a custom image |
| Private GitHub SITL auth | export `MDS_GIT_AUTH_TOKEN_FILE` for mutable runtime sync or image prep |
| Release packaging | customer image/tag/archive naming now belongs to the customer workflow |
| Upstream maintenance | customer repo must deliberately fetch and review official updates |

## Common Pitfalls

### 1. GCS points at customer repo, drones still point at official repo

Result:
- dashboard saves land in one repo
- drones keep pulling another repo

Fix:
- verify `/etc/mds/gcs.env`
- verify `/etc/mds/local.env`
- verify SITL env or image settings

### 2. Private repo build fails inside custom SITL image prep

Result:
- image build cannot clone customer repo

Fix:
- use authenticated HTTPS or a build environment with valid non-interactive credentials

### 3. Dashboard pushes fail on a read-only repo

Result:
- show/config save succeeds locally but push fails

Fix:
- set `MDS_GIT_AUTO_PUSH=false`
- or give the GCS real write credentials

### 4. Running containers are edited manually

Result:
- changes disappear when the container is recreated

Fix:
- commit to git first
- or rebuild and package a clean image

## Recommended Customer Policy

For serious customer work:

1. Keep official MDS on GitHub as the upstream reference.
2. Keep each customer on their own repo and branch.
3. Use GCS SSH write-back only where the customer actually wants dashboard saves committed automatically.
4. Validate custom behavior in SITL before moving it to hardware.
5. Rebuild a pinned custom SITL image once the customer branch is approved.
6. Document the customer repo URL, branch, image tag, and update policy in one place.

## Related Guides

- [GCS Setup Guide](gcs-setup.md)
- [MDS Init Setup Guide](mds-init-setup.md)
- [Advanced SITL Guide](advanced-sitl.md)
- [SITL Custom Release Workflow](sitl-custom-release-workflow.md)
- [Git Sync System](../features/git-sync.md)
