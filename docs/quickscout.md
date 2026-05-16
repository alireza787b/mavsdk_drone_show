# QuickScout

QuickScout is the MDS rapid SAR, surveillance, and reconnaissance planning mode. It produces PX4 Mission-style waypoint packages for one drone or a selected group of drones, then launches them through the normal tracked command pipeline.

Use QuickScout when the operator needs a fast, reviewed search plan: dispatch to a point, search around a last-known position, sweep an area, follow a multi-vertex corridor, monitor progress, abort/return, and recover the mission workspace later.

Related docs:

- [Mission Planning Workspace](features/mission-planning-workspace.md)
- [Telemetry Altitude Policy](guides/telemetry-altitude-policy.md)
- [Mapbox Setup](guides/mapbox-setup.md)
- [Dashboard Operator Guide](guides/dashboard-operator.md)

## Operator Workflow

1. Open `QuickScout`.
2. Choose the mission template: `Point Dispatch`, `Last Known`, `Area Search`, or `Corridor Search`.
3. Select aircraft by slot/position ID. Launch resolves those slots to the currently assigned hardware IDs.
4. Choose the planning position source:
   - `Live GPS` uses fresh drone global positions and can be launched after normal review.
   - `Origin Slots` uses the configured origin and launch slots for offline/staged planning.
5. Draw or enter the geometry:
   - Point dispatch and last-known search use one operator-selected point.
   - Area search uses a polygon.
   - Corridor search uses an ordered polyline with two or more vertices plus corridor width.
6. Set altitude, terrain following, sweep width, overlap, speed, camera interval, and return behavior.
7. Click `Compute Plan`.
8. Watch the planning progress dialog. Long planning uses a bounded job with status, phase text, cancel, retry, and actionable failure messages.
9. Review the mission package before launch: selected drones, geometry, altitude source, terrain state, estimated duration/distance, warnings, blockers, and return behavior.
10. Launch from the review dialog. Staged `Origin Slots` packages run live GPS/slot revalidation before dispatch.
11. Monitor progress, findings, handoff/export data, pause/resume availability, and abort/return state from the monitor workspace.

The page avoids silent fallbacks. If telemetry, origin, terrain, or geometry is unavailable, the UI shows the specific blocker instead of computing from default coordinates.

## Mission Templates

| Template | Geometry | Current behavior |
|----------|----------|------------------|
| `point_dispatch` | Single point | Builds a direct dispatch package to an operator-selected coordinate. |
| `last_known_point` | Single point plus radius | Builds a point-centered uncertainty search around the last known coordinate. |
| `area_sweep` | Polygon | Builds a boustrophedon/lawn-mower coverage path and partitions it across selected drones. |
| `corridor_search` | Multi-vertex polyline plus width | Buffers the route into a corridor and builds a coverage path along the corridor. |

QuickScout is influenced by established SAR and GCS planning patterns, including IAMSAR search concepts and QGroundControl-style polygon/corridor editing. The current implementation is not a complete IAMSAR pattern library. Expanding square, sector, track-line, parallel-track, contour, and coordinated vessel-aircraft searches remain explicit future extensions unless represented by the current templates.

## Safety Semantics

QuickScout uses PX4 Mission semantics:

- The mission is uploaded as an autonomous flight plan.
- PX4 Mission mode requires a valid global 3D position estimate.
- Local-position, VIO, or baro-only states can be useful for display, but they do not provide a safe map origin for global mission planning.
- Selected drones require fresh valid global position samples when their position is needed for assignment.
- `Origin Slots` planning is allowed for offline mission design only. It uses the configured origin and expected launch slots, marks the package as staged, and requires live GPS revalidation before launch.
- Launch revalidation checks that the configured origin has not changed and that assigned aircraft are near the planned launch slots. The launch token is short lived and single use.
- Default or placeholder telemetry such as `(0, 0)` is rejected unless the operator explicitly selected that coordinate as mission geometry.
- Last-known telemetry is treated as last-known, with age/source context, not as fresh position truth.

Terrain behavior is explicit:

- MSL cruise altitude is always shown as the mission altitude reference.
- AGL survey altitude can be terrain-assisted when terrain data is available.
- If terrain following is requested and elevation lookup cannot resolve required waypoints, planning fails with a terrain-unavailable state instead of silently falling back.
- Operators can disable terrain following when a fixed MSL plan is intended.

Abort behavior is explicit:

- `return_home`: command RTL/return behavior after abort or mission end.
- `land_current`: command landing at current position.
- `hold_position`: command hold/loiter where supported.

## Degraded Conditions

| Condition | Expected operator state |
|-----------|-------------------------|
| No Mapbox token | Leaflet fallback remains usable. Mapbox-specific drawing/satellite features may be unavailable. |
| Map tile provider unavailable | The shared map wrapper falls back from Mapbox to Leaflet, then from the default Leaflet satellite layer to OpenStreetMap where possible. |
| Stale telemetry | Planning blocks selected-drone origin/assignment when freshness cannot be trusted. |
| No GPS/global position | Global mission planning blocks; local altitude may still display under the telemetry policy. |
| Aircraft offline during planning | Use `Origin Slots` only for staged design, then revalidate live GPS before launch. |
| Configured origin missing | `Origin Slots` planning blocks and directs the operator to set origin in Mission Config. |
| Terrain provider failure | Terrain-following plans block with `quickscout_terrain_unavailable`; fixed-MSL planning remains possible if selected by the operator. |
| Backend planning takes too long | The planning job shows progress, can be canceled, and returns a bounded failed/expired state. |
| Degraded connectivity | Existing mission workspace and findings remain recoverable from the GCS store; active drone command state still depends on live command/telemetry links. |

## API Surface

QuickScout routes intentionally use the stable `/api/sar` subsystem root.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/sar/mission/plan` | Synchronous compatibility planning path. |
| `POST` | `/api/sar/mission/plan/jobs` | Create a bounded asynchronous planning job. |
| `GET` | `/api/sar/mission/plan/jobs/{job_id}` | Read planning job status, progress, result, or error. |
| `POST` | `/api/sar/mission/plan/jobs/{job_id}/cancel` | Request planning job cancellation. |
| `GET` | `/api/sar/missions` | List persisted mission workspaces. |
| `POST` | `/api/sar/mission/{mission_id}/revalidate-launch` | Revalidate live GPS/launch-slot alignment for staged configured-origin packages. |
| `POST` | `/api/sar/mission/launch` | Launch a reviewed mission package through tracked command dispatch. |
| `GET` | `/api/sar/mission/{mission_id}/workspace` | Recover mission package, status, controls, and findings. |
| `GET` | `/api/sar/mission/{mission_id}/status` | Read mission status and drone progress. |
| `GET` | `/api/sar/mission/{mission_id}/handoff` | Export the mission handoff bundle. |
| `POST` | `/api/sar/mission/{mission_id}/pause` | Pause/hold where available. |
| `POST` | `/api/sar/mission/{mission_id}/resume` | Resume a paused mission where available. |
| `POST` | `/api/sar/mission/{mission_id}/abort` | Abort with explicit return behavior. |
| `POST` | `/api/sar/mission/{mission_id}/progress` | Drone-side progress reporting. |
| `POST` | `/api/sar/findings` | Create a finding. |
| `GET` | `/api/sar/findings` | List findings for a mission. |
| `PATCH` | `/api/sar/findings/{finding_id}` | Update a finding. |
| `DELETE` | `/api/sar/findings/{finding_id}` | Delete a finding. |
| `POST` | `/api/sar/elevation/batch` | Batch terrain/elevation lookup. |

Planning job state is in memory. A GCS restart may lose active job status, but persisted mission packages and findings remain in the QuickScout store.

## Implementation Map

Backend:

- `gcs-server/sar/schemas.py`
- `gcs-server/sar/coverage_planner.py`
- `gcs-server/sar/service.py`
- `gcs-server/sar/terrain.py`
- `gcs-server/sar/store.py`
- `gcs-server/sar/routes.py`

Frontend:

- `app/dashboard/drone-dashboard/src/pages/QuickScoutPage.js`
- `app/dashboard/drone-dashboard/src/components/sar/`
- `app/dashboard/drone-dashboard/src/components/mission-planning/`
- `app/dashboard/drone-dashboard/src/services/sarApiService.js`
- `app/dashboard/drone-dashboard/src/utilities/missionGeometry.js`

Drone execution:

- `quickscout_mission.py`
- `src/drone_setup.py`
- `src/drone_communicator.py`

Tests:

- `tests/test_sar_coverage_planner.py`
- `tests/test_sar_api.py`
- `tests/test_gcs_sar_routes.py`
- `app/dashboard/drone-dashboard/src/pages/QuickScoutPage.test.js`
- `app/dashboard/drone-dashboard/src/services/sarApiService.test.js`
- `app/dashboard/drone-dashboard/src/utilities/missionGeometry.test.js`

## Validation Checklist

Before field handoff or a serious SITL demo:

- Compute point dispatch, last-known point, area search, and multi-vertex corridor search.
- Verify the planning job dialog reaches success, failure, canceled, or expired. No spinner should run indefinitely.
- Verify no selected-drone plan is accepted from stale, missing, or default `(0, 0)` telemetry.
- Verify Leaflet fallback with no Mapbox token.
- Verify terrain-following success and terrain-unavailable failure.
- Review launch package details before dispatch.
- Abort from monitor mode and confirm the chosen return behavior.
- Export the handoff bundle and confirm findings remain attached to the mission.

## External Design References

- [IAMSAR Manual Volume III](https://hamnetkzn.org.za/files/training/IAMSAR%20Manual%20Doc9731_vol3_en_2016%20Edition.pdf)
- [PX4 Mission Mode](https://docs.px4.io/main/en/flight_modes_fw/mission.html)
- [QGroundControl Plan View](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/plan_view/plan_view.html)
- [QGroundControl Corridor Scan](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/plan_view/pattern_corridor_scan.html)
- [NASA Display Standard](https://www.nasa.gov/reference/appendix-f-vol-2/)
- [NIST Public Safety UAS Portfolio](https://www.nist.gov/ctl/pscr/research-portfolios/uncrewed-aircraft-systems)
