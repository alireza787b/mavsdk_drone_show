Date: 2026-04-03
Status: completed
Owner: API modernization stream

Summary

- reviewed the API-modernization result for merge readiness with maintainer, backend-contract, frontend-integration, and MCP-readiness criteria
- confirmed that the GCS-side modernization is materially advanced, but the overall API stream is not yet complete because the drone-side contract is still mixed-generation
- concluded that `main-candidate` should not be merged to `main` as the "API modernization complete" checkpoint yet

Findings

1. High: drone-side legacy routes are still first-class public contract, not temporary compatibility.
   - `src/drone_api_server.py` still mounts the legacy routes directly alongside the v1 aliases for state, command submission, home, global origin, network, swarm config, and local position.
   - `src/drone_api_server.py:727` exposes `GET /get-git-status` with no canonical `/api/v1/...` peer.
   - `src/drone_api_server.py:789` exposes `GET /get-position-deviation` with no canonical `/api/v1/...` peer.
   - `tests/test_api_route_inventory.py:148-179` freezes both the v1 routes and the legacy drone routes as expected current surface.
   - Unlike the GCS inventory, the drone inventory has no retirement assertions that prove those legacy paths are on the way out.

2. High: first-party internal callers still depend on legacy drone URLs.
   - `gcs-server/app_fastapi.py:256` polls `/get_drone_state`.
   - `gcs-server/app_fastapi.py:296` polls `/get-git-status`.
   - `gcs-server/telemetry.py:284` builds the drone telemetry URL from `Params.get_drone_state_URI`.
   - `gcs-server/api_routes/commands.py:106` fetches `/get-home-pos`.
   - `gcs-server/command.py:445` still calls `/api/live-armability` instead of the canonical `/api/v1/preflight/armability`.
   - `src/telemetry_subscription_manager.py:53` polls `Params.get_drone_state_URI`.
   - `functions/git_manager.py:218` still hardcodes `/get-git-status`.
   - `src/params.py:191-221` still treats legacy route names as the primary configurable URIs.

3. High: the drone API documentation is still legacy-first and misleading for a "complete modernization" claim.
   - `docs/apis/drone-api-server.md:16-18` says canonical routes are being introduced, but the endpoint catalog that follows is still documented under legacy paths such as `/get_drone_state`, `/api/send-command`, `/get-home-pos`, and `/get-git-status`.
   - `docs/apis/drone-api-server.md:6` still labels the surface "Production Ready" while the modernization stream is still explicitly in migration.
   - `tests/README.md:91-99` also teaches only the legacy drone endpoints.

4. Medium-High: the canonical drone surface is only partially typed and is not yet machine-contract-grade.
   - Only the state, armability, command, and v1 health routes currently declare `response_model`s in `src/drone_api_server.py`.
   - The other public drone routes return ad hoc dictionaries without formal response models:
     - `src/drone_api_server.py:672-697` home
     - `src/drone_api_server.py:699-725` global origin
     - `src/drone_api_server.py:727-777` git status
     - `src/drone_api_server.py:789-844` position deviation
     - `src/drone_api_server.py:846-863` network status
     - `src/drone_api_server.py:865-874` swarm config
     - `src/drone_api_server.py:876-914` local position
   - This weakens OpenAPI fidelity and makes later MCP wrapping harder.

5. Medium-High: the drone command contract is still permissive and stringly typed for future automation.
   - `src/drone_api_server.py:84-89` allows arbitrary extra fields on `CommandRequest`.
   - `src/drone_api_server.py:87-88` models `missionType` and `triggerTime` as strings.
   - `src/drone_api_server.py:450-669` returns HTTP 200 for both accepted and rejected commands, moving semantic failure into the payload only.
   - `docs/apis/drone-api-server.md:176` documents that rejection-via-HTTP-200 behavior as the contract.
   - This may be workable for current GCS flow, but it is not the cleanest contract for external automation, auth policy, or agent tooling.

6. Medium: the shared-contract cleanup is asymmetric between GCS and drone.
   - `src/gcs_api_routes.py` exists and centralizes canonical GCS route constants.
   - There is no equivalent shared drone-route constants module; first-party drone callers still use literal legacy strings or `Params` legacy URI fields.
   - `gcs-server/schemas.py:337-338` still explicitly defines the drone git schema around the raw `/get-git-status` response.

Verdict

- API modernization is not complete end to end.
- The GCS-side contract can reasonably be called modernized enough for continued use.
- The overall program is not merge-ready as a "clean, future-proof API baseline" until the drone-side contract is brought to the same standard.

Required next slices before merge-to-main

1. Introduce shared canonical drone route constants and stop treating legacy route names as primary config.
2. Add the missing canonical drone routes, especially for git status and any remaining drone-only diagnostics that should survive.
3. Migrate all first-party GCS/tool/runtime callers onto canonical drone routes.
4. Rewrite the drone API docs and test docs so canonical routes are the source of truth and legacy paths are either retired or explicitly marked transitional.
5. Add typed response/request models for the remaining public drone routes so OpenAPI is usable for future MCP and auth layers.
6. Reassess the command ACK contract and decide deliberately whether rejected commands stay HTTP 200 or move to stronger API semantics.
7. Only after those slices pass local plus Hetzner validation should this stream be tagged and merged to `main`.
