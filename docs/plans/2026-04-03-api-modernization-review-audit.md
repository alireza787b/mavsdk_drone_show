Date: 2026-04-03
Status: completed
Owner: API modernization stream

Summary

- performed a merge-readiness review of the API-modernization stream from code-maintainer, contract-design, and future MCP/tooling perspectives
- conclusion: the stream is not ready to tag or merge to `main`
- conclusion detail: the GCS-side cleanup is substantially improved, but the drone-side API is still mixed-generation and still teaches/uses legacy routes as first-class surface

Findings

1. Drone-side canonical migration is incomplete and is still blocked by first-party legacy callers.
   - `gcs-server/app_fastapi.py` still polls drone telemetry from `/get_drone_state`
   - `gcs-server/app_fastapi.py` still polls drone git status from `/get-git-status`
   - `gcs-server/api_routes/commands.py` still reads drone home position from `/get-home-pos`
   - `gcs-server/command.py` still probes live armability through `/api/live-armability`
   - `functions/git_manager.py` still fetches remote drone git status from `/get-git-status`
   - this means the repo still depends operationally on legacy drone paths even though canonical drone aliases were introduced

2. The drone API still lacks a complete canonical route set.
   - the mounted inventory includes canonical aliases for state, commands, health, home/global-origin, network, swarm config, and local-position
   - the mounted inventory still has no canonical `/api/v1/git/status`
   - the mounted inventory still preserves legacy drone paths as first-class expected routes rather than compatibility-only debt scheduled for retirement

3. Active docs still reinforce the legacy-first drone contract.
   - `docs/apis/drone-api-server.md` documents `GET /get_drone_state`, `POST /api/send-command`, `GET /get-home-pos`, and `GET /get-git-status` as the main interface
   - `docs/features/git-sync.md` still describes the monitoring flow as polling each drone's `/get-git-status` endpoint
   - `gcs-server/schemas.py` still describes the drone git payload as matching the raw `/get-git-status` response

4. Command input contracts are not fully future-proof for MCP/tooling yet.
   - `gcs-server/api_routes/commands.py` still accepts raw JSON via `_parse_required_json_object(...)` instead of a strongly enforced canonical request model
   - `gcs-server/schemas.py` explicitly marks `SubmitCommandRequest` as a legacy helper/reference schema rather than the live request contract
   - `src/drone_api_server.py` still defines `CommandRequest` with `extra='allow'`, which weakens machine-validated contract guarantees on the drone side

5. The GCS stream surface is cleaner, but that is not the remaining blocker.
   - `/ws/telemetry`, `/ws/heartbeats`, and `/ws/git-status` are now intentionally documented as canonical transport roots
   - this review does not recommend changing that policy before the remaining drone-route debt is closed

Merge Readiness Verdict

- not ready for `main`
- not ready for tag/release
- safe to continue on `main-candidate`

Required next slices before merge

1. Introduce shared canonical drone route constants and move first-party callers onto them.
2. Add canonical drone git-status route support and migrate tooling/docs/tests.
3. Retire remaining drone legacy aliases only after runtime callers and docs no longer depend on them.
4. Strengthen live command request models for both GCS submit and drone execute surfaces.
5. Re-run targeted local and Hetzner validation after each drone-side slice.
