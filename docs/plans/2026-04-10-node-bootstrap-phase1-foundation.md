# 2026-04-10 Node Bootstrap Phase 1 Foundation

## Scope

First implementation checkpoint for the node bootstrap and fleet enrollment redesign.

This slice intentionally stops before candidate-enrollment APIs. It closes the bootstrap
foundation so later enrollment work has one canonical provisioning path and one
machine-readable identity surface.

## What Changed

- kept `tools/install_mds_node.sh` as the only public one-line bootstrap entry
- kept `tools/mds_node_init.sh` as the only supported init engine
- removed the remaining public script/help wording that still implied a
  Raspberry-Pi-only bootstrap path
- added `/etc/mds/node_identity.json` as the structured node manifest written by
  `mds_node_init.sh`
- added optional `--report-json PATH` support to emit a machine-readable
  bootstrap report for Ansible, CI, and future MCP / agent workflows
- updated active deployment docs to:
  - describe `node_identity.json`
  - document report output
  - clean up golden-image guidance so cloned images remove node-local identity
  - clarify that secrets belong in vault/secret-store flows, not in repo files

## Node Identity Manifest

The bootstrap now writes a structured manifest at:

- `/etc/mds/node_identity.json`

Current fields:

- `node_uuid`
- `hw_id`
- `hostname`
- `role_hint`
- `repo_url`
- `branch`
- `bootstrap_version`
- `bootstrap_status`
- `network_mode`
- `primary_control_ip`
- `netbird_enabled`
- `mavlink_routing_mode`
- `mavlink_input_type`
- `mavlink_input_device`
- `local_env_file`
- `node_identity_file`
- `updated_at`

This is the first machine-readable identity seam for later:

- candidate announce
- enrollment review
- replacement / recovery workflows
- AI / MCP / automation tooling

## Validation

Focused validation completed:

- `bash -n tools/install_mds_node.sh`
- `bash -n tools/mds_node_init.sh`
- `bash -n tools/mds_init_lib/identity.sh`
- `bash -n tools/mds_init_lib/prereqs.sh`
- `./tools/mds_node_init.sh --help`
- `./tools/install_mds_node.sh --help`
- repo scan confirming active docs/scripts no longer point operators at
  `install_rpi.sh` / `mds_init.sh` / `raspberry_setup.sh`
- `git diff --check`

No full hardware bootstrap run was claimed in this slice. The next live validation
should happen after the enrollment-side changes land, so the new identity manifest
and candidate flow can be exercised together.

## Explicitly Not Done Yet

- no candidate registry on GCS yet
- no enrollment / accept / replace / reject routes yet
- Mission Config still needs the unsafe heartbeat auto-add removal in the next slice
- no mavlink-anywhere repo changes yet
- no Hetzner hardware-style integration run yet

## Next Slice

Recommended next checkpoint:

1. remove Mission Config heartbeat auto-add
2. replace it with derived pending-candidate visibility
3. keep replacement awareness alive from the same derived source
4. then add the real GCS candidate registry / state machine in the following slice
