# Official Bootstrap Hardware Closeout

Date: 2026-04-11
Branch: `main-candidate`
Validated release head: `e74b448d`

## Scope Closed

This closeout finishes the official MDS bootstrap and fleet-enrollment hardening needed before starting a private customer demo fork.

Validated surfaces:

- official wrapper flow for companion-node bootstrap
- existing-node `--force` rerun path through `mds_node_init.sh`
- private/custom repo bootstrap auth ordering fixes
- NetBird reuse and candidate announce flow
- node identity / local env generation
- GCS candidate enrollment metadata
- real Raspberry Pi CM4 + Holybro PX4 hardware path over NetBird to Hetzner GCS

## Real Hardware Validation

Validated against:

- GCS host: Hetzner `100.82.107.61`
- companion node: Holybro CM4 `100.82.72.33`
- runtime user: `droneshow`
- hardware ID: `101`

Final live result on `e74b448d`:

- bootstrap completed successfully through the official wrapper
- verification summary reported `PASS: 13`, `WARN: 0`, `FAIL: 0`
- candidate announce succeeded with `pending_operator_review`
- node identity manifest carried:
  - `repo_url`
  - `branch=main-candidate`
  - `commit=e74b448d`
  - `network_mode=netbird`
  - `primary_control_ip=100.82.72.33`
- `/etc/mds/local.env` was regenerated cleanly with:
  - `MDS_HW_ID`
  - `MDS_GCS_IP`
  - `MDS_GCS_API_BASE_URL`
  - `MDS_REPO_URL`
  - `MDS_BRANCH`

## Main Fixes In This Stream

- wrapper installers now prepare private-repo auth before first clone
- wrapper installers now support piped `curl | bash` execution cleanly
- node bootstrap now prefers `requirements-node.txt` on companion hardware
- associative-array-dependent shell paths were removed from verification and service helpers
- verification summary and NTP writes are no longer broken by `IFS=$'\n\t'`
- non-interactive MAVLink auto-config now applies Raspberry Pi UART boot-file fixes
- node identity and bootstrap reports preserve repo/branch/commit metadata
- announce parsing now supports both nested and direct candidate response shapes
- repository verification now works under root against a repo owned by `droneshow`
- MAVSDK latest-version fetch now keeps stdout machine-readable

## Local Validation

Focused regression slices passed during closeout:

- `68 passed` on the bootstrap/enrollment shell + Python regression batch
- targeted announce/bootstrap batches also passed repeatedly during intermediate checkpoints

## Remaining Explicit Debt

Not blocking this phase:

- move Hetzner demo runtime from official repo to the private client repo
- first real candidate acceptance on the client fleet config, not just announce
- client SITL image/release packaging
- optional operator-facing cleanup of the bootstrap banner still showing `unknown` branch/commit inside repo-local init

## Release Recommendation

This official stream is ready to promote from `main-candidate` to `main` and tag before starting the client-specific private fork rollout.
