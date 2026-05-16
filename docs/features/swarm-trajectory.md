# Swarm Trajectory

Status: active hardening and operator validation
Mission type: `4` (`SWARM_TRAJECTORY`)
Primary page: `Swarm Trajectory`
Advanced editor: `Advanced Route Editor` (`/trajectory-planning`)

Swarm Trajectory is the MDS global-coordinate trajectory workflow for processed leader/follower swarm missions. It is different from QuickScout: QuickScout produces PX4 Mission-style SAR packages, while Swarm Trajectory processes precise leader routes into per-drone MDS trajectory files for coordinated Mission Type 4 execution.

Related docs:

- [Mission Planning Workspace](mission-planning-workspace.md)
- [Smart Swarm](smart-swarm.md)
- [Telemetry Altitude Policy](../guides/telemetry-altitude-policy.md)
- [Dashboard Operator Guide](../guides/dashboard-operator.md)
- [Mapbox Setup](../guides/mapbox-setup.md)

## Operator Workflow

1. Open `Swarm Design` and verify the intended leaders, followers, offsets, and clusters.
2. Open `Swarm Trajectory`.
3. In `Plan or Import Leader Route`, choose a top leader.
4. Click the leader-route map to add waypoints, or use the compact numeric form for precise entry.
5. Each map click selects the new waypoint and fills the latitude, longitude, altitude, time, speed, and heading fields.
6. Use `Auto ETA` for normal route authoring: the planner derives waypoint time from distance, altitude change, and preferred speed. Use `Fixed time` only when the arrival time must be pinned.
7. Use `Auto yaw` for normal arrival-leg heading. Use `Manual` only when the leader must hold a specific heading at a waypoint.
8. Edit, delete, select from the map, or reorder draft waypoints on the page. Route time, required speed, climb/descent, and yaw summaries reflow after each change.
9. Choose altitude input:
   - `MSL` stores the entered altitude directly.
   - `AGL` queries terrain/elevation and stores the derived MSL mission altitude.
10. Click `Assign to Leader` to upload the drafted route as that leader's raw CSV.
11. Optionally use CSV upload for legacy/imported leader routes.
12. Click `Process Swarm Trajectory Package`.
13. Watch the processing job dialog. It shows phase, progress, cancel request state, success, failure, and retry state.
14. Review validation blockers, warnings, cluster status, leader/follower preview paths, plots, and downloadable outputs.
15. Commit outputs when the deployment needs git traceability or propagation.
16. Transfer/launch from the Dashboard Mission Trigger as Mission Type 4 after readiness is clear.
17. Clear/reset only when intentionally removing the active route package.

The old trajectory-planning route remains available as `Advanced Route Editor` for lower-level route editing while its map authoring tools are migrated into Swarm Trajectory. The primary operator workflow no longer requires starting there for normal leader-route authoring.

## Product Semantics

Swarm Trajectory uses global latitude/longitude and stored MSL altitude throughout the processed package.

| Concept | Meaning |
|---------|---------|
| Leader route | The operator-authored path for a top leader. |
| Follower path | A generated per-drone route derived from the leader route and `swarm.json` offsets. |
| Cluster | A top leader plus the followers that depend on it directly or through a nested chain. |
| Validation | Backend readiness truth for commit/transfer/launch review. |
| Preview | Downsampled processed paths and cluster relationships for visualization. |
| Commit | Git record/sync boundary for generated artifacts, not a safety guarantee by itself. |
| Dashboard Mission Type 4 | The actual execution dispatch surface. |

This mode is not live Smart Swarm. Smart Swarm is the live leader/follower control mode. Swarm Trajectory generates individual per-drone files before execution.

## Safety Model

Swarm Trajectory is MDS/offboard-style trajectory execution. PX4 Offboard-style operations require continuous external setpoint proof-of-life and position/pose data appropriate to the setpoints. MDS runtime code owns that execution behavior; the planner must make the route package explicit before the operator dispatches it.

Operator-visible safety rules:

- Only top leaders are authored or uploaded manually.
- Follower outputs are generated from the current swarm hierarchy and offsets.
- Validation blocks commit/transfer when the processed package cannot be trusted.
- Unknown swarm structure, missing clusters, missing leader uploads, stale processed outputs, and missing processed drones are blockers.
- Partial outputs are visible as partial, not launch-ready.
- AGL is an authoring convenience. The package stores MSL altitude.
- Terrain/elevation lookup failure blocks AGL waypoint save unless the operator switches to MSL input.
- The first waypoint is the route entry anchor; later waypoints define route motion.
- Map-authored waypoints default to automatic ETA and automatic arrival yaw after the route-entry anchor.
- Fixed-time waypoints calculate required inbound speed and are blocked when they exceed the configured safe envelope.
- Dashboard launch readiness remains the final dispatch gate.

## Altitude And Terrain

| Mode | Operator enters | Stored in mission package | Failure behavior |
|------|-----------------|---------------------------|------------------|
| `MSL` | Mean sea level altitude | Entered MSL altitude | Validated against altitude bounds. |
| `AGL` | Target clearance above terrain | Terrain elevation plus target AGL as MSL | Blocks if terrain/elevation is unavailable for the waypoint. |

Terrain assistance is waypoint-based. It is not full continuous terrain-following across every point of every long segment. Long routes over changing terrain need denser waypoint sampling or a later dedicated terrain-follow validation pass.

Swarm Trajectory AGL authoring uses the backend elevation endpoint, not the visual map widget, so Mapbox and Leaflet follow the same terrain contract. If the backend terrain provider cannot resolve a point, the AGL save is blocked instead of silently substituting an estimate.

Sea-level terrain references are valid. A resolved ground elevation of `0.0 m MSL` must not be treated as missing data.

## Degraded Conditions

| Condition | Expected operator state |
|-----------|-------------------------|
| No Mapbox token | Leaflet fallback remains available. |
| Terrain provider unavailable | AGL waypoint authoring blocks with a specific terrain error; MSL authoring remains available. |
| No valid processed package | Validation reports blockers; commit/transfer is blocked. |
| Missing leader upload | The leader/cluster is shown as missing upload; processing cannot make a complete package. |
| Partial follower output | The affected cluster is shown as partial; review and reprocess before launch. |
| Processing takes too long | The async processing job dialog shows progress, can request cancel, and ends in a bounded terminal state. |
| GCS restart during processing | In-memory job state can be lost. Raw and processed trajectory files remain on disk. |
| Degraded telemetry | Planning artifacts remain reviewable, but Dashboard launch readiness depends on live command/telemetry truth. |

## API Surface

The canonical API namespace is `/api/v1/swarm-trajectories/*`. The old versionless `/api/swarm/...` family is retired and should not be reintroduced.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/v1/swarm-trajectories/leaders` | Read top leaders, follower hierarchy, and upload status. |
| `POST` | `/api/v1/swarm-trajectories/upload/{leader_id}` | Upload one leader CSV. |
| `GET` | `/api/v1/swarm-trajectories/status` | Read raw/processed/plot counts and cluster state. |
| `GET` | `/api/v1/swarm-trajectories/recommendation` | Read whether processing is needed. |
| `POST` | `/api/v1/swarm-trajectories/process` | Synchronous compatibility processing path. |
| `POST` | `/api/v1/swarm-trajectories/process/jobs` | Create an asynchronous processing job. |
| `GET` | `/api/v1/swarm-trajectories/process/jobs/{job_id}` | Read job status, progress, result, or error. |
| `POST` | `/api/v1/swarm-trajectories/process/jobs/{job_id}/cancel` | Request processing-job cancellation. |
| `GET` | `/api/v1/swarm-trajectories/validate` | Validate processed package readiness. |
| `GET` | `/api/v1/swarm-trajectories/preview` | Read downsampled per-drone paths and cluster preview data. |
| `POST` | `/api/v1/swarm-trajectories/elevation/batch` | Resolve terrain/elevation for waypoint authoring. |
| `GET` | `/api/v1/swarm-trajectories/policy` | Read planner limits/defaults from backend params. |
| `POST` | `/api/v1/swarm-trajectories/clear-processed` | Clear processed outputs and plots. |
| `POST` | `/api/v1/swarm-trajectories/clear` | Clear raw, processed, and plot artifacts. |
| `POST` | `/api/v1/swarm-trajectories/clear-leader/{leader_id}` | Clear one leader upload and dependent outputs. |
| `DELETE` | `/api/v1/swarm-trajectories/remove/{leader_id}` | Remove one leader upload and dependent outputs. |
| `POST` | `/api/v1/swarm-trajectories/clear-drone/{drone_id}` | Clear one processed drone output and stale plots. |
| `GET` | `/api/v1/swarm-trajectories/download/{drone_id}` | Download one processed drone CSV. |
| `GET` | `/api/v1/swarm-trajectories/download-kml/{drone_id}` | Download one drone KML. |
| `GET` | `/api/v1/swarm-trajectories/download-cluster-kml/{leader_id}` | Download one cluster KML. |
| `POST` | `/api/v1/swarm-trajectories/commit` | Commit/push or locally record generated artifacts according to GCS writeback mode. |
| `GET` | `/api/v1/swarm-trajectories/plots/{filename}` | Serve generated plot images. |

Processing job state is in memory. A GCS restart may lose active job status, but raw uploads and processed artifacts remain in the configured trajectory workspace.

## CSV Contract

Leader input CSV columns:

```csv
Name,Latitude,Longitude,Altitude_MSL_m,TimeFromStart_s,EstimatedSpeed_ms,Heading_deg,HeadingMode,AltitudeReference,TargetAgl_m,GroundElevation_m,TerrainAccurate,TimingMode,PreferredSpeed_ms,CalculatedHeading_deg
WP1,35.000000,51.000000,120.0,0.0,0.0,25.0,manual,MSL,0.0,0.0,true,manual_time,8.0,25.0
WP2,35.001000,51.002000,125.0,45.0,8.0,63.0,auto,MSL,0.0,0.0,true,auto_speed,8.0,63.0
```

The first eight columns remain compatible with older leader CSVs. The trailing metadata columns preserve modern authoring intent for altitude, terrain, timing, and heading review.

`TimingMode=auto_speed` means the operator supplied preferred speed and the planner derived `TimeFromStart_s`. `TimingMode=manual_time` means the operator pinned the time and the planner derived required speed for review. `HeadingMode=auto` stores the calculated inbound arrival yaw; `HeadingMode=manual` stores the operator-owned heading.

Processed output CSVs are generated per drone and include time, global position, velocity, acceleration, yaw, mode, and LED fields used by the runtime trajectory executor.

## File Layout

```text
shapes/ or shapes_sitl/
  swarm_trajectory/
    raw/
      Drone 1.csv
    processed/
      Drone 1.csv
      Drone 2.csv
    plots/
      drone_1_trajectory.jpg
      cluster_leader_1.jpg
      combined_swarm.jpg
```

Same-host SITL may use a shared `shapes_sitl/swarm_trajectory/` workspace so the GCS and containers see the same generated files without dirtying container repos. Hardware and remote deployments still require the normal commit/push/sync flow.

## Implementation Map

Backend:

- `gcs-server/api_routes/swarm_trajectory.py`
- `functions/swarm_trajectory_service.py`
- `functions/swarm_trajectory_processor.py`
- `functions/swarm_trajectory_utils.py`
- `functions/swarm_global_calculator.py`
- `functions/swarm_analyzer.py`
- `functions/swarm_plotter.py`
- `gcs-server/schemas.py`

Frontend:

- `app/dashboard/drone-dashboard/src/pages/SwarmTrajectory.js`
- `app/dashboard/drone-dashboard/src/pages/TrajectoryPlanning.js`
- `app/dashboard/drone-dashboard/src/components/trajectory/`
- `app/dashboard/drone-dashboard/src/components/mission-planning/`
- `app/dashboard/drone-dashboard/src/services/droneApiService.js`
- `app/dashboard/drone-dashboard/src/services/gcsApiService.js`
- `app/dashboard/drone-dashboard/src/utilities/swarmTrajectoryDraft.js`

Runtime:

- `swarm_trajectory_mission.py`
- `src/drone_setup.py`
- `src/params.py`

Tests:

- `tests/test_swarm_trajectory_service.py`
- `tests/test_gcs_swarm_trajectory_routes.py`
- `app/dashboard/drone-dashboard/src/pages/SwarmTrajectory.test.js`
- `app/dashboard/drone-dashboard/src/pages/TrajectoryPlanning.test.js`
- `app/dashboard/drone-dashboard/src/utilities/swarmTrajectoryDraft.test.js`

## Validation Checklist

Before field handoff or a serious SITL demo:

- Author a two-or-more-waypoint leader route on the Swarm Trajectory page.
- Confirm map clicks select the new waypoint and populate latitude, longitude, altitude, time, speed, and heading fields.
- Edit, delete, select from the map, and reorder waypoints.
- Confirm ETA, required speed, climb/descent, and heading summaries reflow after each route change.
- Save a waypoint in MSL mode.
- Attempt AGL mode with terrain available and verify derived MSL output.
- Attempt AGL mode with terrain unavailable and verify it blocks with a clear error.
- Assign the route to a top leader.
- Process through the async job dialog and verify success, failure, and cancel behavior where possible.
- Review validation blockers/warnings/advisories.
- Verify leader and follower preview paths, clusters, and role labels.
- Commit outputs in the intended writeback mode.
- Launch from Dashboard Mission Type 4 only after readiness is clear.
- Clear/reset the package and verify validation returns to missing-upload/missing-output state.
- Repeat with no Mapbox token to confirm Leaflet fallback.

## Explicit Deferrals

- Full automated multi-drone deconfliction is not complete.
- Terrain assistance is waypoint-based, not full continuous terrain-following.
- Advanced automated replanning after a route or cluster fault is not complete.
- In-memory processing jobs are acceptable for bounded UI progress, but durable job state is a future backend hardening item.
- No-GPS/VIO execution beyond display and readiness signaling remains a runtime-specific validation topic, not a global-route planner guarantee.

## External Design References

- [PX4 Offboard Mode](https://docs.px4.io/main/en/flight_modes/offboard.html)
- [PX4 Mission Mode](https://docs.px4.io/main/en/flight_modes_fw/mission.html)
- [QGroundControl Plan View](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/plan_view/plan_view.html)
- [NASA Display Standard](https://www.nasa.gov/reference/appendix-f-vol-2/)
- [NIST Public Safety UAS Portfolio](https://www.nist.gov/ctl/pscr/research-portfolios/uncrewed-aircraft-systems)
