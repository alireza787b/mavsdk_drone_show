# Node Bootstrap Candidate Announce Integration

Date: 2026-04-10
Baseline: `b1d7b8ff`
Checkpoint: `pending commit`
Status: implemented and validated

## Summary

This slice wires the generic companion-node bootstrap path into the canonical
 fleet candidate registry instead of leaving discovery split between local node
 identity and separate manual GCS awareness.

## What Changed

- added `tools/mds_init_lib/announce.sh`
- added `tools/mds_node_announce.sh`
- integrated candidate announce as the final `mds_node_init.sh` phase
- added `--gcs-api-url`, `--announce-report-json`, and `--announce-timeout`
  to `mds_node_init.sh`
- added `--gcs-api-url` and `--announce-report-json` passthrough help to
  `tools/install_mds_node.sh`
- extended `/etc/mds/local.env` support with `MDS_GCS_API_BASE_URL`
- extended `/etc/mds/node_identity.json` with:
  - `created_at`
  - `last_bootstrap_at`
- extended bootstrap reports with announce result fields:
  - `gcs_api_url`
  - `announce_status`
  - `announce_http_status`
  - `announce_candidate_id`
  - `announce_registration_state`
  - `announce_message`

## Behavioral Rules

- bootstrap still provisions the node even if candidate announce cannot reach
  the GCS
- candidate announce is now a clean discovery step, not a second bootstrap path
- operators and automation can re-run discovery later with:
  - `sudo ./tools/mds_node_announce.sh`
- URL resolution order is:
  1. `--gcs-api-url`
  2. `MDS_GCS_API_BASE_URL`
  3. `MDS_GCS_API_BASE_URL` from `local.env`
  4. `MDS_GCS_IP` / `--gcs-ip` with default port `5000`

## Validation

Local:

- `python3 -m pytest tests/test_mds_node_announce_script.py -q`
  - `3 passed`
- `bash -n tools/install_mds_node.sh tools/mds_node_init.sh tools/mds_node_announce.sh tools/mds_init_lib/announce.sh tools/mds_init_lib/identity.sh`
- `./tools/mds_node_init.sh --help`
- `./tools/mds_node_announce.sh --help`

Hetzner clean sync:

- `python -m pytest tests/test_mds_node_announce_script.py tests/test_fleet_candidate_registry.py tests/test_gcs_fleet_candidates_routes.py tests/test_gcs_api_http.py::TestAPIV1Aliases::test_route_inventory_includes_current_core_surfaces -q`
  - `14 passed`
- remote `bash -n` on the changed bootstrap scripts
- remote `./tools/mds_node_init.sh --help`
- remote `./tools/mds_node_announce.sh --help`

## Notes

- this slice does not add a second provisioning engine
- this slice does not yet add named bootstrap profile files or Ansible
  inventory templates as first-class repo assets
- this slice keeps the discovery channel cleanly separated from GCS acceptance
  and slot replacement semantics
