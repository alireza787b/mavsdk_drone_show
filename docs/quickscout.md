# QuickScout - Search Operations Module

Template-driven rapid-search mission mode for SAR and reconnaissance workflows, using durable GCS mission state, tracked command launch/control, PX4 Mission Mode execution, and operator-reviewed findings.

## Overview

QuickScout adds a new mission mode (`QUICKSCOUT = 5`) for rapid search operations. The GCS plans a mission package, partitions assigned coverage across selected drones, launches via the shared tracked-command pipeline, and keeps a durable mission workspace for recovery, monitoring, and findings review.

## Architecture

```
GCS Dashboard (React)               GCS Server (FastAPI)                Drone (PX4)
  QuickScoutPage.js          -->    POST /api/sar/mission/plan    -->  coverage_planner.py
  Template-aware planning           QuickScoutService                   Compute/search package
  Review launch package             QuickScoutStore                     Persist mission + findings

  Click "Launch"             -->    POST /api/sar/mission/launch  -->  drone_communicator.py
                                    tracked command dispatch            Write waypoints JSON
                                                                        drone_setup.py
                                                                        quickscout_mission.py
                                                                        (PX4 Mission upload)

  Monitor progress           <--    GET /api/sar/mission/{id}/status
  DroneStatusCards                  service/store                 <--  POST /progress reports
  Findings review                   /api/sar/findings
```

## Supported Templates

- `area_sweep`: polygon coverage search
- `last_known_point`: point-centered uncertainty search
- `corridor_search`: route-centered buffered search strip

All templates currently resolve into one coverage-package flow for execution, while keeping template metadata explicit for review, recovery, and future MCP/AI-agent integration.

## Planning Algorithm

1. Convert polygon vertices from lat/lng to local ENU (East-North-Up) coordinates using `pymap3d`
2. Create a Shapely polygon from ENU coordinates
3. Generate parallel sweep lines across the polygon's bounding box (spaced by `sweep_width_m * (1 - overlap_percent/100)`)
4. Clip sweep lines to the polygon boundary
5. Connect clipped segments in alternating direction (boustrophedon/lawn-mower pattern)
6. For N drones: partition waypoints into N roughly-equal sectors
7. Assign sectors to drones by GPS proximity (greedy nearest-match)
8. Convert ENU waypoints back to lat/lng with altitude

## API Endpoints

All endpoints are prefixed with `/api/sar`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/mission/plan` | Compute coverage plan for a search area |
| GET | `/missions` | List persisted QuickScout missions for recovery |
| POST | `/mission/launch` | Launch a planned mission to drones |
| GET | `/mission/{id}/workspace` | Recover persisted mission package and live status |
| GET | `/mission/{id}/status` | Get mission status and drone progress |
| GET | `/mission/{id}/handoff` | Get the canonical mission handoff/export bundle |
| POST | `/mission/{id}/pause` | Pause executing drones |
| POST | `/mission/{id}/resume` | Resume paused drones |
| POST | `/mission/{id}/abort` | Abort mission with return behavior |
| POST | `/mission/{id}/progress` | Drone progress report (from drone) |
| POST | `/findings` | Create a mission finding |
| GET | `/findings` | List findings for a mission |
| PATCH | `/findings/{id}` | Update a finding |
| DELETE | `/findings/{id}` | Delete a finding |
| POST | `/elevation/batch` | Batch terrain elevation lookup |

## Configuration

### Survey Parameters (SurveyConfig)

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `sweep_width_m` | 30.0 | 0-500 | Width between sweep lines (meters) |
| `overlap_percent` | 10.0 | 0-50 | Overlap between adjacent sweeps |
| `cruise_altitude_msl` | 50.0 | 0-500 | Transit altitude MSL (meters) |
| `survey_altitude_agl` | 40.0 | 0-300 | Survey altitude AGL (meters) |
| `cruise_speed_ms` | 10.0 | 0-25 | Transit speed (m/s) |
| `survey_speed_ms` | 5.0 | 0-15 | Survey speed (m/s) |
| `camera_interval_s` | 2.0 | 0-30 | Camera capture interval (seconds) |
| `use_terrain_following` | true | - | Adjust altitude for terrain |

### Return Behaviors

- `return_home` (default): RTL after survey completion
- `land_current`: Land at current position
- `hold_position`: Hold/loiter at last waypoint

## Dependencies

**GCS Server only** (not needed on drones):
- `shapely>=2.0.0` - Polygon operations and sweep line clipping
- `pymap3d` - Coordinate conversions (lat/lng <-> ENU)

**Frontend**:
- `@mapbox/mapbox-gl-draw` - Polygon drawing on map
- `react-map-gl` / `mapbox-gl` - Map rendering (existing dependency)

## Frontend

The QuickScout page is accessible from the sidebar menu and provides two modes:

- **Plan Mode**: select a mission template, define search geometry, configure survey/profile settings, review coverage packaging, and launch
- **Monitor Mode**: view drone progress, mission/package context, control availability, evidence-backed findings review, mission handoff/export, and finding-led follow-up search seeding

The map view shows coverage paths color-coded per drone (solid for survey legs, dashed for transit), plus findings markers and search footprint previews for point/corridor templates.

## File Structure

```
gcs-server/sar/
  __init__.py
  schemas.py              # Pydantic models
  coverage_planner.py     # Boustrophedon algorithm
  terrain.py              # Terrain elevation helpers
  service.py              # QuickScout application service
  store.py                # Durable SQLite mission + findings store
  mission_manager.py      # Legacy mission facade still used by older internal helpers
  routes.py               # FastAPI APIRouter

quickscout_mission.py     # Drone-side PX4 mission executor

app/dashboard/drone-dashboard/src/
  pages/QuickScoutPage.js
  components/sar/          # All QuickScout UI components
  services/sarApiService.js
  styles/QuickScout.css

tests/
  test_sar_schemas.py
  test_sar_coverage_planner.py
  test_sar_api.py
```

## Drone-Side Execution

The drone receives waypoints via the standard command dispatch flow:

1. GCS sends QUICKSCOUT command with waypoints array
2. `drone_communicator.py` writes waypoints to `/tmp/quickscout_{hw_id}_{mission_id}.json`
3. `drone_setup.py` launches `quickscout_mission.py` as a subprocess
4. `quickscout_mission.py`:
   - Connects to PX4 via MAVSDK
   - Builds `MissionItem` list from waypoints (with camera actions)
   - Uploads mission, arms, and starts
   - Monitors progress and reports to GCS via POST `/api/sar/mission/{id}/progress`
   - LED feedback: blue (init) -> yellow (upload) -> white (executing) -> green (complete)

## Current V1 Boundaries

QuickScout is significantly more mature than the original PoC, but it is still an evolving search-operations subsystem. The current validated baseline includes:

- template-aware planning and recovery
- tracked launch / hold / abort control semantics
- durable mission state on GCS
- durable findings workflow with operator review
- evidence-reference editing on findings
- canonical mission handoff/export bundle plus monitor-mode brief/export workflow
- reusable findings-aware, template-complete QuickScout SITL validators covering `area_sweep`, `last_known_point`, and `corridor_search`, plus single-drone and multi-drone launch-control drills with evidence refs and mission handoff/export

Still deferred:

- mid-mission add/remove-drone retasking
- deeper follow-up package generation from current airborne state beyond finding-seeded replans
- advanced retask / fault-injection SITL scenarios beyond the validated findings-aware launch-control gates
- broader raw MAVLink / `mavlink2rest` style debug surfaces
