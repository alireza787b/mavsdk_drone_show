# Fleet Candidate Registry Foundation

Date: 2026-04-10
Repo baseline: `c2038a79`
Status: completed

## Scope

This slice adds the durable GCS-side candidate registry that the design brief
called for. It closes the gap between node bootstrap / discovery and the later
operator enrollment workflow by giving GCS one canonical pending-candidate
state machine.

## What Changed

- added `gcs-server/fleet_candidates.py` as the durable registry service
- added canonical Fleet Enrollment routes in
  `gcs-server/api_routes/fleet_candidates.py`
- added typed enrollment schemas in `gcs-server/schemas.py`
- extended `src/gcs_api_routes.py` with canonical candidate route constants
- updated `app_fastapi.py` to expose registry helpers and include the new router
- updated heartbeat handling so candidate observation happens server-side as a
  best-effort side effect of accepted heartbeats
- cut `MissionConfig.js` over to the backend candidate registry instead of
  browser-side heartbeat diffing
- removed `buildPendingEnrollmentCandidates(...)` so pending enrollment is no
  longer computed through a second local algorithm

## Candidate Lifecycle

The registry now tracks:

- `pending_operator_review`
- `conflict`
- `accepted`
- `rejected`
- `ignored`
- `superseded`

Candidates are stored in:

- `runtime_data/fleet_candidates.json`
- `runtime_data/fleet_candidate_events.jsonl`

This keeps discovery / review state durable across GCS restarts without
mutating the real fleet manifest until the operator explicitly accepts or
replaces.

## Replacement Semantics

The field-spare scenario is now handled by the same backend workflow as any
other replacement.

Example:

- failed slot is `P12`
- standby node appears as `H101`
- candidate `hw-101` is reviewed and chosen as the replacement for `H12`

When that happens, the backend now:

- rewrites the target `config.json` row from `hw_id 12 -> 101`
- preserves `pos_id 12`
- rewrites the matching `swarm.json` assignment from `hw_id 12 -> 101`
- rewrites any `follow == 12` references to `follow == 101`

That avoids the earlier risk where replacement only touched fleet config and
left Smart Swarm follow chains stale.

## Announce Contract Decision

The explicit bootstrap announce route intentionally accepts a **narrow** v1
payload:

- node identity
- bootstrap/version info
- repo / branch
- network mode
- primary control IP
- MAVLink routing input info

It does **not** use GCS-derived runtime state as announce input. That keeps
node-local provisioning facts separate from GCS-observed fleet state.

## Operator / Frontend Impact

Mission Config pending candidates now come from the backend registry:

- pending and conflict nodes are shown from GCS state
- accepted / rejected / ignored candidates are hidden by default
- conflict reasons come from the registry instead of improvised browser rules

This keeps Mission Config as a read/review surface while the next slice builds
the dedicated accept / replace / recover workflow UI.

## Validation

Local validation:

- `python3 -m pytest tests/test_fleet_candidate_registry.py tests/test_gcs_fleet_candidates_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py::TestAPIV1Aliases::test_route_inventory_includes_current_core_surfaces tests/test_gcs_api_http.py::TestAPIV1Aliases::test_v1_fleet_heartbeat_post_alias`
- result: `13 passed`

Hetzner clean-sync validation:

- backend batch above in clean temp venv
- Mission Config Jest batch:
  - `src/pages/MissionConfig.test.js`
  - `src/services/gcsApiService.test.js`
  - `src/utilities/missionIdentityUtils.test.js`
- production dashboard build

Results:

- backend: `13 passed`
- frontend Jest: `3` suites passed, `40` tests passed
- build: passed

## Explicitly Not Done Yet

- no dedicated Fleet Enrollment operator page yet
- no accept / replace / reject dialog workflow yet
- no bootstrap script integration with `/api/v1/fleet/candidates/announce` yet
- config + swarm replacement save is still sequential, not transactional
- no recovery-specific operator path yet for “same physical drone, new companion”

## Next Slice

Recommended next checkpoint:

1. dedicated Fleet Enrollment operator workspace
2. explicit accept / replace / reject / ignore dialogs
3. separate “new node”, “replace existing”, and “recover same node” operator
   flows on top of the same registry
4. then wire bootstrap automation into the canonical announce path
