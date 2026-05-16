# Mission Planning Workspace

MDS uses shared mission-planning patterns across QuickScout and Swarm Trajectory without hiding the difference between the mission modes.

QuickScout is a SAR/surveillance workflow that produces PX4 Mission-style waypoint packages. Swarm Trajectory is an MDS trajectory workflow that processes leader routes into per-drone Mission Type 4 outputs. The UI components are shared where operator behavior should be consistent: map drawing, geometry summaries, altitude controls, progress dialogs, review dialogs, and actionable errors.

## Shared Operator Rules

- Show the mission type, selected drones, geometry validity, altitude source, terrain state, readiness, and next action on the main screen.
- Keep long explanations in docs and tooltips.
- Never show an indefinite spinner. Long work must have phase text, progress, timeout/failure state, cancel where supported, and retry.
- Treat warnings, blockers, degraded states, and advisory states separately.
- Center review, launch, cancel, abort, and destructive-action dialogs.
- Preserve explicit operator coordinates, including `(0, 0)`, but never convert blank inputs or missing telemetry into `(0, 0)`.
- Show stale telemetry as stale. Do not treat last-known data as fresh position truth.
- Keep Mapbox optional. Leaflet fallback must stay usable.

## Map And Geometry

| Geometry | Used by | Notes |
|----------|---------|-------|
| Point | QuickScout point dispatch and last-known search | One explicit coordinate selected by map click or coordinate input. |
| Polyline | QuickScout corridor search, Swarm route authoring | Two or more ordered points. Corridor search also needs a corridor width. |
| Polygon | QuickScout area search | Three or more vertices. |
| Waypoint sequence | Swarm Trajectory leader route | Ordered global waypoints with altitude, timing, and heading intent. |

Mapbox is preferred when configured because it supports richer map/draw behavior. Without a token, MDS uses Leaflet. If the default Leaflet tile source is unavailable, the shared map wrapper can fall back to OpenStreetMap rather than leaving a blank map.

## Altitude And Position Policy

MDS separates display altitude from map-trusted global position. The [Telemetry Altitude Policy](../guides/telemetry-altitude-policy.md) is the source of truth for display ordering.

Planning policy:

- Global waypoint planning requires valid global coordinates.
- `relative_home`, `local_ned`, and `baro` are useful display sources but are not map coordinates by themselves.
- QuickScout `Live GPS` planning needs fresh valid global position samples when planner assignment depends on selected-drone location.
- QuickScout `Origin Slots` planning uses configured origin launch slots for offline/staged design only. It is persisted with provenance and must pass live GPS/slot revalidation before launch.
- Swarm Trajectory stores global latitude/longitude and MSL altitude in the mission package.
- AGL authoring must be backed by terrain/elevation data before it is converted into MSL.
- Terrain provider failures must be visible and actionable.

## Job And Error Policy

QuickScout planning and Swarm Trajectory processing both expose asynchronous job endpoints for long work.

Common job states:

- `queued`
- `running`
- `succeeded`
- `failed`
- `canceled`
- `expired`

The frontend should show:

- current phase and message
- progress percent when available
- cancel action when the backend can accept it
- a terminal state for every job
- the backend error code/message when failed
- a retry path where operator input is still valid

Current QuickScout planning jobs and Swarm Trajectory processing jobs are in-memory. A GCS restart can lose active job status, but persisted QuickScout missions/findings and Swarm raw/processed trajectory artifacts remain on disk.

## Mode Differences

| Topic | QuickScout | Swarm Trajectory |
|-------|------------|------------------|
| Operator intent | Rapid SAR/recon dispatch and search coverage | Precise global trajectory processing for a leader/follower swarm |
| Runtime semantics | PX4 Mission-style autonomous waypoint upload | MDS trajectory/offboard-style Mission Type 4 execution |
| Primary geometry | Point, polygon, corridor polyline | Ordered leader waypoint sequence |
| Multi-drone behavior | Partition coverage where the template supports it | Generate per-drone files from leader/follower cluster graph |
| Launch surface | QuickScout review/launch then monitor | Dashboard Mission Trigger after validation/commit/transfer review |
| Required position truth | Global mission geometry and fresh selected-drone global positions for assignment | Global route geometry; launch readiness depends on runtime telemetry/preflight |
| Terrain behavior | Optional terrain following for search waypoints | AGL authoring converts terrain-assisted waypoint altitudes into stored MSL |

## Field Scenarios

Coast guard/SAR point response:

- Use QuickScout `Point Dispatch` or `Last Known`.
- Select the responding aircraft.
- Verify the point, altitude, return behavior, and telemetry freshness.
- Launch only after the review dialog has no blockers.

Shoreline or road search:

- Use QuickScout `Corridor Search`.
- Click multiple route vertices along the shoreline, road, or drift line.
- Set corridor width and altitude/terrain behavior.
- Compute and review the generated coverage strip.

Wide area sweep:

- Use QuickScout `Area Search`.
- Draw a polygon around the assigned search box.
- Verify sweep width, overlap, and selected drones.
- Launch after partitioning and terrain warnings are clear.

Planned coordinated surveillance pass:

- Use Swarm Trajectory.
- Verify `Swarm Design` first.
- Author/import a leader route, assign it, process, validate, preview cluster paths, commit/transfer if required, then launch Mission Type 4 from Dashboard.

Degraded connectivity:

- Do not treat missing map tiles or stale telemetry as proof that a mission is safe.
- Existing stored workspaces can help recover context.
- Launch/readiness still requires live preflight and command truth.

No GPS/local-position-only case:

- Altitude may still display from `local_ned` or `baro`.
- Global map planning and PX4 Mission upload should block until valid global position truth exists.
- Swarm global route authoring can continue as a draft, but execution readiness remains blocked by runtime preflight.

## External Design References

- [IAMSAR Manual Volume III](https://hamnetkzn.org.za/files/training/IAMSAR%20Manual%20Doc9731_vol3_en_2016%20Edition.pdf)
- [PX4 Mission Mode](https://docs.px4.io/main/en/flight_modes_fw/mission.html)
- [PX4 Offboard Mode](https://docs.px4.io/main/en/flight_modes/offboard.html)
- [QGroundControl Plan View](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/plan_view/plan_view.html)
- [QGroundControl Corridor Scan](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/plan_view/pattern_corridor_scan.html)
- [NASA Display Standard](https://www.nasa.gov/reference/appendix-f-vol-2/)
- [NIST Public Safety UAS Portfolio](https://www.nist.gov/ctl/pscr/research-portfolios/uncrewed-aircraft-systems)
