# 2026-04-16 Smart Swarm Runtime Closeout

## Scope

This closes the official-first Smart Swarm runtime redesign stream that started
from the 2026-04-15 audit and Phase 1 implementation.

The goal for this closeout was:

- repair the remaining runtime gaps found during contract-demo review
- prove the fixes on the official branch, not only in local unit tests
- harden the acceptance tooling around real degraded-network behavior
- remove known runtime ambiguity before syncing anything into the private
  client repo

## Final Fixes Closed In This Slice

### 1. Recent-link presence truth for leader-only control and sync

GCS-side command and sync routing now treat a drone as recently online when
either:

- heartbeat freshness is current, or
- telemetry freshness still proves the link is alive

This closed the case where a drone could still be alive enough for control, but
the routing layer rejected it because heartbeat alone had not refreshed yet.

Files:

- `gcs-server/link_presence.py`
- `gcs-server/command.py`
- `gcs-server/app_fastapi.py`

### 2. Live leader reassignment reconnect

Followers now force a leader-stream reconnect when the assigned leader target
changes at runtime.

This closed the bug where a follower could locally adopt a new `follow` value
yet continue consuming the old leader's stream until a later restart or hard
timeout.

Files:

- `smart_swarm.py`
- `tests/test_smart_swarm_target_switch.py`

### 3. Custom-branch runtime git status and sync behavior

Drone git-status now goes through the shared git manager so custom branches
without an upstream report cleanly instead of throwing fatal `@{u}` noise.

The SSH repo sync helper no longer ends with a redundant final `git pull` after
`fetch + reset --hard origin/<branch>` has already pinned the runtime. That old
final pull could fail on customer/private branch setups even though the runtime
was already in the correct state.

Files:

- `functions/git_manager.py`
- `src/drone_api_server.py`
- `tools/update_repo_ssh.sh`

### 4. Leader-dropout validation path

The reusable Smart Swarm validator now supports a SITL leader-dropout drill by
pausing the active leader container, validating follower promotion / continued
tracking, then unpausing and confirming recovery.

This closes a major acceptance gap: failover is no longer only a unit-test
claim, it has an official reusable runtime proof path.

Files:

- `tools/validate_smart_swarm_runtime.py`
- `tests/test_validate_smart_swarm_runtime.py`

### 5. Stateful GCS worker recycle fix

The strict runtime acceptance pass exposed a real production bug: Gunicorn's
request-count recycle could restart the single worker mid-validation, which
destroyed the in-memory command tracker and caused a false `404` on command
status lookup during a long Smart Swarm run.

The official launcher now disables worker recycle by default for the stateful
single-worker runtime unless an explicit positive max-request value is supplied.

File:

- `gcs-server/start_gcs_server.sh`

## Validation

### Local focused regression ring

Passed:

```bash
python3 -m pytest \
  tests/test_validate_smart_swarm_runtime.py \
  tests/test_command_system.py \
  tests/test_link_presence.py \
  tests/test_smart_swarm_target_switch.py \
  tests/test_git_manager.py \
  tests/test_drone_api_http.py -q
```

Result:

- `141 passed`
- `1 skipped`

### Hetzner official runtime proof

Official runtime path:

- `/root/mavsdk_drone_show_smart_swarm_runtime_clean`

Validated on live SITL:

1. baseline Smart Swarm runtime pass
2. explicit leader-dropout/failover pass
3. strict-tolerance runtime pass after the worker-recycle fix

Key strict-tolerance settle evidence:

- initial cluster settle:
  - max horizontal error ≈ `0.07m`
  - max altitude error ≈ `0.03m`
- post-reassignment settle:
  - drone `2` horizontal error ≈ `0.054m`
  - drone `3` horizontal error ≈ `0.061m`
  - both altitude errors ≈ `0.041m` or below

Artifact paths:

- `/root/mavsdk_drone_show_smart_swarm_runtime_clean/artifacts/sitl-validation/smart-swarm-runtime-20260416-final.json`
- `/root/mavsdk_drone_show_smart_swarm_runtime_clean/artifacts/sitl-validation/smart-swarm-runtime-20260416-dropout.json`
- `/root/mavsdk_drone_show_smart_swarm_runtime_clean/artifacts/sitl-validation/smart-swarm-runtime-20260416-tight-final.json`

## Important Operational Note

The strict validator failure that previously returned `HTTP Error 404: Not
Found` was not a Smart Swarm controller failure. It was a backend runtime
failure caused by worker recycle destroying command-tracker state mid-command.

That distinction matters:

- the controller/tracking quality under strict tolerances was already strong
- the runtime contract around long-lived command tracking was the actual bug
- the official fix is therefore in the launcher/runtime behavior, not in
  loosening Smart Swarm tolerances

## Remaining Explicit Deferred Item

Still intentionally deferred:

- browser/admin exec terminal

This item is unrelated to Smart Swarm runtime correctness and was not pulled
into this closeout.
