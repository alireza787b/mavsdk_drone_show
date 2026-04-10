# Mission Config Pending-Enrollment Cutover

Date: 2026-04-10
Repo baseline: `c0c676d2`
Status: completed

## Scope

This slice removes the unsafe Mission Config behavior that silently turned
heartbeat-only nodes into editable fleet config rows. It replaces that with an
explicit pending-enrollment view and reuses the same derived candidates inside
the replacement workflow.

## What Changed

- removed the heartbeat-driven auto-add effect from `MissionConfig.js`
- added a shared `buildPendingEnrollmentCandidates(...)` utility so candidate
  derivation is consistent and testable
- introduced a Mission Config review panel for heartbeat-visible nodes that are
  not yet enrolled into fleet config
- added explicit pending counts into Mission Config workspace stats and alert
  summaries
- renamed unsaved manual rows from “newly detected” semantics to explicit
  “draft assignment” semantics
- changed the replacement wizard to consume the same pending-candidate source
  instead of recomputing spares ad hoc from raw heartbeats

## Operator Impact

Mission Config no longer implies that an unknown node is already part of the
fleet just because it is sending heartbeats.

Operators now have three distinct states:

- enrolled fleet members: real `config.json` rows
- draft assignments: manual local edits not yet saved
- pending candidates: heartbeat-visible nodes not yet enrolled

This is the correct preparation for the later GCS candidate-registry workflow.

## Replacement / Spare Scenario

The field-spare workflow is intentionally the same path, not a parallel one.

Example:

- failed slot: `P12`
- standby node arrives by heartbeat as `H101`
- Mission Config shows `H101` under detected pending candidates
- `Replace drone` for slot `P12` consumes that same pending candidate
- later backend enrollment state can formalize the acceptance / replacement
  record, but the operator mental model stays single-path

This keeps spare-airframe replacement, reimaged-node recovery, and new-node
acceptance under one clean workflow family instead of splitting them into
separate mission-type-specific procedures.

## Validation

Focused Hetzner validation completed against the clean sync tree:

- `CI=true npm test -- --runInBand --watch=false src/pages/MissionConfig.test.js src/utilities/missionIdentityUtils.test.js`
- `npm run build`

Results:

- Jest: `2` suites passed, `14` tests passed
- production build: passed

## Explicitly Not Done Yet

- no backend GCS candidate registry yet
- no accept / replace / reject durable state machine yet
- no runtime persistence file for enrollment candidates yet
- no CLI / automation integration for enrollment actions yet

## Next Slice

Recommended next checkpoint:

1. add the backend candidate registry foundation on GCS
2. persist candidate review state under `runtime_data/`
3. expose canonical accept / replace / reject review routes
4. connect Mission Config to that registry without reviving heartbeat auto-add
