# Private Customer Bootstrap And Runtime Validation

Date: 2026-04-12

## Scope

Validate the official MDS bootstrap/runtime path against a private customer repo
and a live Hetzner deployment target before starting customer-specific
customization work.

## What Was Validated

1. Official wrapper bootstrap can now target a private GitHub repo over HTTPS
   with `--git-auth-token-file`.
2. The repo-local init scripts persist the same token-file source of truth into
   `/etc/mds/gcs.env` and `/etc/mds/local.env`.
3. The GCS runtime launcher now exports that token-file path into the runtime
   git-sync environment.
4. The runtime git-sync path now performs authenticated HTTPS fetch/pull instead
   of assuming SSH or unauthenticated HTTPS.
5. The GCS real-mode marker and health guidance are now aligned with the rest
   of MDS (`real.mode` at repo root and `/api/v1/system/health` guidance).

## Real-World Deviations Found And Fixed

### 1. Deploy keys disabled on the customer repo

The customer GitHub org/repo policy rejected deploy-key automation. That meant
the official MDS bootstrap flow needed a first-class private HTTPS token-file
path instead of assuming deploy keys were always available.

Implemented:
- wrapper support for `--git-auth-token-file`
- repo-local init support for `--git-auth-token-file`
- repo helper support for authenticated HTTPS git operations

### 2. Customer repo lagged behind official bootstrap contract

The first Hetzner bootstrap cloned the private repo successfully, then failed
because the private repo was still pinned to an older official snapshot whose
`mds_gcs_init.sh` did not yet understand `--git-auth-token-file`.

Resolution:
- sync official `main-candidate` fixes into the private customer
  `main-candidate` branch before relying on that branch for bootstrap

### 3. GitHub temporary clone tokens expire quickly

For live validation, GitHub's `temp_clone_token` worked for authenticated HTTPS
git clone/fetch, but it expired quickly enough that it is not suitable as the
documented customer credential model.

Operational conclusion:
- use a dedicated long-lived read-only Git credential file for customer docs
- keep `temp_clone_token` as a validation-only fallback

### 4. GCS non-interactive repo selection drifted into SSH

Even with an explicit HTTPS repo URL and token file, the GCS repo phase still
defaulted to SSH in non-interactive mode.

Resolution:
- the GCS repo phase now infers HTTPS correctly for explicit private HTTPS/token
  setups and no longer wanders into deploy-key setup

### 5. Fresh backend verification warned on missing fleet-candidate state

Fresh GCS installs emitted a warning because the candidate registry JSON file
did not exist yet.

Resolution:
- the registry now creates its empty durable state on first boot

### 6. Runtime git-sync still lacked private HTTPS auth

After bootstrap succeeded, `app/linux_dashboard_start.sh --real --prod` still
failed in the runtime git-sync step because the runtime launcher did not export
`MDS_GIT_AUTH_TOKEN_FILE`, and `tools/update_repo_ssh.sh` did not support
authenticated HTTPS git operations.

Resolution:
- launcher exports runtime git auth variables from `/etc/mds/gcs.env`
- runtime git-sync now supports authenticated HTTPS fetch/pull
- explicit HTTPS repo selection now stays HTTPS at runtime

### 7. Real mode marker path drift

The dashboard start script wrote `real.mode` under `gcs-server/`, while the
rest of MDS expects `real.mode` at the repo root.

Resolution:
- launcher now writes the canonical repo-root `real.mode`

## Live Hetzner Result

Validated private customer runtime:
- repo: private customer repo
- branch: `main-candidate`
- live commit: `2f935c19`
- backend health: `ok`
- dashboard serving on `3030`
- backend serving on `5000`

Current live URLs:
- dashboard: `http://203.0.113.10:3030`
- health: `http://203.0.113.10:5000/api/v1/system/health`

## Hardware Validation Status

The remaining external blocker is not in MDS:
- the Hetzner overlay peer is connected
- the hardware-node overlay peer is present in the mesh but currently `Idle`
- SSH from Hetzner to the node returns `No route to host`

Because of that, node-side real-hardware bootstrap validation cannot be
completed in this pass.

## Ready / Not Ready

Ready now:
- official bootstrap/runtime path for private HTTPS GitHub repos
- customer-private GCS install on Hetzner
- customer-private GCS runtime on Hetzner

Not yet closed:
- live hardware node bootstrap and enrollment on the real companion node
- customer SITL image build / packaging / MEGA publication

## Recommended Next Step

When the hardware node is reachable again:
1. run the official node bootstrap against the private repo
2. verify candidate announce / Fleet Enrollment
3. confirm the node appears on the live customer dashboard
4. only then start customer-specific implementation work
