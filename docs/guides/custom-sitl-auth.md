# Custom SITL Auth Guide

## Purpose

Use this guide whenever MDS runs against a fork, customer repo, private repo, or custom SITL image.

The rule is simple:

- GCS may need write access.
- Disposable SITL containers need read access only.
- Image preparation needs temporary read access only.
- No token or SSH private key should be baked into a final SITL image.

This guide is the source of truth for custom SITL and private-repo authentication. Related guides should link here instead of repeating conflicting credential rules.

## Supported Modes

| Mode | Repo visibility | GCS access | SITL container access | Recommended use |
|------|-----------------|------------|-----------------------|-----------------|
| Official public demo | public official repo | maintainer/team write on trusted GCS only | no auth, public HTTPS read | public demos and normal evaluation |
| Public fork/custom repo | public fork | write access on GCS if dashboard saves should push | no auth, public HTTPS read | open custom demos and public forks |
| Private customer repo | private repo | host-only write credential on GCS | read-only token/key mounted into containers | customer deployments |
| Pinned private image | private repo baked into image | host-only write credential on GCS | no runtime auth if `MDS_SITL_GIT_SYNC=false` | repeatable demos, large fleets |

## Credential Split

### GCS Write Access

Use this only on the trusted GCS host when dashboard save/import workflows must commit and push.

Recommended:

```text
SSH deploy key with write access, scoped to one repo
```

Store it on the GCS host only, for example:

```text
/root/.mds/keys/customer_gcs_write_key
```

Do not mount this write key into SITL containers.
Do not bake it into Docker images.

If the GCS is intentionally read-only, set:

```env
MDS_GIT_AUTO_PUSH=false
```

In read-only mode, dashboard edits may still be useful for demo/local inspection, but they are not a durable repo write-back workflow.

### SITL Container Read Access

SITL containers are disposable. They should only read the configured repo/branch.

Recommended default for private GitHub HTTPS:

```bash
sudo install -d -m 700 /root/.mds/keys
sudo install -m 600 /dev/null /root/.mds/keys/customer_git_read_token
sudo sh -c 'printf %s "YOUR_FINE_GRAINED_READ_TOKEN" > /root/.mds/keys/customer_git_read_token'

export MDS_REPO_URL="https://github.com/YOURORG/YOURPRIVATE-REPO.git"
export MDS_BRANCH="customer-demo"
export MDS_GIT_AUTH_TOKEN_FILE="/root/.mds/keys/customer_git_read_token"
export MDS_SITL_GIT_SYNC=true
```

The token should be limited to:

- selected customer repository
- read-only contents access
- expiration enabled when practical

The launcher mounts the token file into each container as a read-only secret path and sets the container-side `MDS_GIT_AUTH_TOKEN_FILE`.

SSH fallback for private GitHub:

```bash
sudo install -d -m 700 /root/.mds/keys
sudo install -m 600 customer_read_key /root/.mds/keys/customer_git_read_key

export MDS_REPO_URL="git@github.com:YOURORG/YOURPRIVATE-REPO.git"
export MDS_BRANCH="customer-demo"
export MDS_GIT_SSH_KEY_FILE="/root/.mds/keys/customer_git_read_key"
export MDS_SITL_GIT_SYNC=true
```

Use SSH read keys when organization policy prefers SSH or when HTTPS tokens are not allowed.

### Image Prep Read Access

Private image prep uses the same read-only credential model.

```bash
export MDS_REPO_URL="https://github.com/YOURORG/YOURPRIVATE-REPO.git"
export MDS_BRANCH="customer-demo"
export MDS_GIT_AUTH_TOKEN_FILE="/root/.mds/keys/customer_git_read_token"

bash tools/release_sitl_image.sh \
  --base-image mavsdk-drone-show-sitl:latest \
  --image-repo customer-mds-sitl \
  --version-tag v5-customer \
  --repo-url "$MDS_REPO_URL" \
  --branch "$MDS_BRANCH"
```

The release helper validates git access first, stages the credential only during preparation, removes it, then flattens the final image.

For large fleets or stable customer demos:

```bash
export MDS_DOCKER_IMAGE="customer-mds-sitl:v5-customer"
export MDS_SITL_GIT_SYNC=false
export MDS_SITL_REQUIREMENTS_SYNC=false
bash multiple_sitl/create_dockers.sh 100
```

This avoids one remote git fetch per container and gives every container the same validated code state.

## Required Environment Variables

| Variable | Scope | Purpose |
|----------|-------|---------|
| `MDS_REPO_URL` | GCS, drones, SITL, image prep | Repo URL to clone/fetch |
| `MDS_BRANCH` | GCS, drones, SITL, image prep | Branch to follow |
| `MDS_GIT_AUTO_PUSH` | GCS | Whether dashboard git save/import can push |
| `MDS_GIT_AUTH_TOKEN_FILE` | SITL/image prep/GCS HTTPS read setups | Required read-only token file for HTTPS token auth |
| `MDS_GIT_AUTH_USERNAME` | HTTPS token auth | Usually `x-access-token` |
| `MDS_GIT_SSH_KEY_FILE` | SITL/image prep SSH read setups | Read-only SSH key file |
| `MDS_SITL_GIT_SYNC` | SITL containers | Runtime fetch/reset on container boot |
| `MDS_SITL_GIT_SYNC_PREFLIGHT` | SITL launcher | Validate repo/branch/auth before container creation |

Default:

```env
MDS_SITL_GIT_SYNC_PREFLIGHT=true
```

Do not disable preflight unless you are testing an offline image with `MDS_SITL_GIT_SYNC=false` or deliberately debugging network/auth behavior.

## Preflight Check

Before creating containers or preparing a custom image, validate access:

```bash
bash tools/mds_git_access_check.sh \
  --repo-url "$MDS_REPO_URL" \
  --branch "$MDS_BRANCH" \
  --mode sitl-read
```

Modes:

```text
sitl-read   read access for disposable SITL containers
image-prep  read access before a flattened image build
gcs-write   GCS repo reachability context; write validation remains setup-specific
```

`multiple_sitl/create_dockers.sh`, `tools/build_custom_image.sh`, and `tools/release_sitl_image.sh` run this check automatically unless `MDS_SKIP_GIT_ACCESS_PREFLIGHT=true`.

If the check fails, fix the repo URL, branch, or credential before creating containers. Otherwise every container would fail the same git sync step independently.

## Public Official And Public Forks

For public repos, use HTTPS and no credential:

```bash
export MDS_REPO_URL="https://github.com/alireza787b/mavsdk_drone_show.git"
export MDS_BRANCH="main"
unset MDS_GIT_AUTH_TOKEN_FILE
unset MDS_GIT_SSH_KEY_FILE
```

Public fork example:

```bash
export MDS_REPO_URL="https://github.com/YOURORG/mavsdk_drone_show.git"
export MDS_BRANCH="customer-demo"
```

If the GCS must push to the public fork, configure GCS write access separately. SITL containers still do not need write access.

## Private Repo Operator Flow

1. Decide customer repo and branch.
2. Give the GCS host write access only if dashboard save/import must push.
3. Create a separate read-only credential for SITL and image prep.
4. Export `MDS_REPO_URL`, `MDS_BRANCH`, and the read credential file path.
5. Run `tools/mds_git_access_check.sh`.
6. Start containers through the dashboard or `multiple_sitl/create_dockers.sh`.
7. After approval, build a flattened custom image and prefer `MDS_SITL_GIT_SYNC=false` for repeatable demos.

## AI Agent Checklist

Before changing a custom/private setup:

- Confirm whether the repo is public or private.
- Confirm whether GCS should be write-capable or read-only.
- Never put credentials in `MDS_REPO_URL`.
- Never copy a GCS write key into SITL containers.
- Use `MDS_GIT_AUTH_TOKEN_FILE`; raw token environment variables are intentionally unsupported.
- Run `tools/mds_git_access_check.sh` before launching containers or image prep.
- Check `MDS_SITL_GIT_SYNC=false` for pinned release images and large fleets.
- Do not commit credential files, `.ssh` keys, or token paths that contain customer identity.

## Marker Asset Roadmap

Current supported visual override:

```json
{
  "marker_color": "#00d4ff"
}
```

Future custom 2D/3D markers should be implemented as a managed asset library:

- SVG/PNG for 2D markers
- GLB for 3D runtime markers
- optional OBJ import only if converted to GLB
- file size limits and validation
- preview, reuse, remove, and reset-to-default actions
- config references by asset ID, not arbitrary filesystem paths

This keeps future map/globe rendering reusable and avoids unsafe ad hoc file paths in mission config.

## Troubleshooting

### `Invalid username or token`

The token file is missing, expired, or lacks repo read permission.

Fix:

```bash
bash tools/mds_git_access_check.sh --repo-url "$MDS_REPO_URL" --branch "$MDS_BRANCH" --mode sitl-read
```

Then replace the token file with a valid read-only token.

### `branch was not found`

The repo is reachable, but `MDS_BRANCH` is wrong or not pushed.

Fix:

```bash
git ls-remote --heads "$MDS_REPO_URL"
```

Then export the correct branch.

### Containers fail immediately during startup git sync

Check the operation log or container `startup_sitl.log`. Most failures are one of:

- missing read token/key
- wrong branch
- private repo URL with public/no-auth mode
- SSH key not authorized on the repo

Run the preflight check on the host before recreating the fleet.

### Dashboard can save locally but cannot push

The GCS is read-only or lacks write access.

Fix one of:

```env
MDS_GIT_AUTO_PUSH=false
```

or configure a dedicated GCS write key on the GCS host.

## Related Guides

- [Custom Repo Workflow](custom-repo-workflow.md)
- [Advanced SITL Configuration](advanced-sitl.md)
- [SITL Custom Release Workflow](sitl-custom-release-workflow.md)
- [GCS Setup Guide](gcs-setup.md)
- [Git Sync System](../features/git-sync.md)
