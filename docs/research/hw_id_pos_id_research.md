# Hardware ID & Position ID: Deep Research Report

**Date:** 2026-03-05
**Status:** Implementation Complete (2026-03-05) — see resolved markers below
**Scope:** All MDS modules — drone show, smart swarm, search & rescue, leader-follower

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Implementation Analysis](#2-current-implementation-analysis)
3. [Industry Best Practices Comparison](#3-industry-best-practices-comparison)
4. [Bugs & Issues Found](#4-bugs--issues-found)
5. [Conceptual Design Analysis](#5-conceptual-design-analysis)
6. [File Inventory — All Code Touching hw_id/pos_id](#6-file-inventory)
7. [Recommendations](#7-recommendations)

---

## 1. Executive Summary

The MDS project uses a **two-layer identity model**:

| Concept | Description | Persistent? | Source of Truth |
|---------|-------------|-------------|-----------------|
| **hw_id** (Hardware ID) | Physical drone identity, printed/labeled on airframe | Yes — permanent per drone | `{N}.hwID` file on companion computer |
| **pos_id** (Position ID) | Choreography slot / formation position assigned to a drone | Configurable — can change between missions | `config.json` / `config_sitl.json` field |
| **detected_pos_id** | GPS-based auto-detected position at field | Runtime only | `PosIDAutoDetector` module |
| **MAV_SYS_ID** | PX4 autopilot system ID, set to equal hw_id | Semi-permanent (requires reboot) | PX4 parameter |

**Core design intent (confirmed correct):**
- `hw_id` = "which physical drone" (like a serial number)
- `pos_id` = "what role/trajectory this drone flies" (like a jersey number)
- Decoupling allows **hot-swap**: spare drone hw_id=10 can replace failed hw_id=3 by assigning pos_id=3
- Dense operator-facing dashboard surfaces use the compact shorthand `Pn|Hm`
- Example: `P3|H10` means `Position ID 3 | Hardware ID 10`
- The shorthand is for high-density cards, cluster scopes, and plots; configuration forms remain explicit with `Position ID` and `Hardware ID`

This is the **correct architectural pattern** used by all major commercial drone show platforms (Verge Aero, Skybrush/CollMot). However, the MDS implementation has **significant bugs, inconsistencies, and code duplication** that must be fixed.

---

## 2. Current Implementation Analysis

### 2.1 Hardware ID (.hwID File Mechanism)

**How it works:** A zero-byte file named `{N}.hwID` (e.g., `5.hwID`) exists in the project root directory. The filename (without extension) IS the hardware ID.

**Creation paths:**
| Path | File | Lines |
|------|------|-------|
| Enterprise init | `tools/mds_init_lib/identity.sh` | 43-69 |
| Legacy setup | `tools/raspberry_setup.sh` | 744-756 |
| SITL Docker | `multiple_sitl/create_dockers.sh` | 218-274 |

**Reading implementations (4 DUPLICATE copies!):**

| # | Location | Returns | Notes |
|---|----------|---------|-------|
| 1 | `src/drone_config/config_loader.py:get_hw_id()` L36 | `str` | Canonical — used by `DroneConfig.__init__()` |
| 2 | `drone_show_src/utils.py:read_hw_id()` L95 | `int` | Used by `drone_show.py` |
| 3 | `smart_swarm.py:read_hw_id()` L221 | `int` | Standalone copy |
| 4 | `actions.py:read_hw_id()` L173 | `int` | Standalone copy |

**Bug: Type inconsistency** — The canonical `ConfigLoader.get_hw_id()` returns `str`, while the 3 copies return `int`. This causes implicit conversions throughout the codebase.

### 2.2 Position ID (config.json Mapping)

**How it works:** `config.json` maps each `hw_id` to a `pos_id`. The drone loads trajectory from `Drone {pos_id}.csv`.

**Current JSON format:**
```json
{"version": 1, "drones": [
  {"hw_id": 1, "pos_id": 1, "ip": "100.96.240.11", "mavlink_port": 14551,
   "serial_port": "/dev/ttyS0", "baudrate": 57600}
]}
```

**[RESOLVED] Previously config.csv had COLLISION BUGS:**
```
hw_id=3,  pos_id=5   ← DUPLICATE pos_id=5
hw_id=5,  pos_id=5   ← DUPLICATE pos_id=5
hw_id=10, pos_id=5   ← TRIPLE pos_id=5 !!
hw_id=1,  pos_id=1   ← DUPLICATE pos_id=1
hw_id=7,  pos_id=1   ← DUPLICATE pos_id=1
hw_id=2,  pos_id=2   ← DUPLICATE pos_id=2
hw_id=8,  pos_id=2   ← DUPLICATE pos_id=2
```

These collisions mean multiple drones would fly identical trajectories and **collide mid-air**. The GCS backend detects this during validation but the file on disk contains these dangerous values.

### 2.3 Swarm CSV (Leader-Follower)

**Format:** `hw_id,follow,offset_n,offset_e,offset_alt,body_coord`

**Critical design note:** `swarm.json` uses `hw_id` (not `pos_id`) for the `follow` field. This means leader-follower relationships are tied to **physical drones**, not show positions. If you role-swap hw_id=7 to pos_id=1, followers still follow by hw_id, not by pos_id.

### 2.4 Auto-Detection (pos_id_auto_detector.py)

A background thread that:
1. Gets drone's GPS position
2. Converts to local NED using show origin
3. Compares against all known positions from trajectory CSVs
4. Finds closest `pos_id` within `max_deviation` (1.5m default)
5. Sets `drone_config.detected_pos_id`

**Ambiguity:** `detected_pos_id=0` means "undetected", but `pos_id=0` is technically valid per schema (`ge=0`). Should be `pos_id >= 1` or use `None`/`-1` for undetected.

### 2.5 MAV_SYS_ID Relationship

```
hw_id = MAV_SYS_ID (always equal)
gRPC port = 50040 + hw_id
```

This is set via:
- SITL: `export MAV_SYS_ID="$HWID"` in `startup_sitl.sh`
- Real: `init_sysid` action in `actions.py` — sets PX4 param and reboots FC

### 2.6 Data Flow Summary

```
[Setup Time]
  mds_node_init.sh → creates {N}.hwID file
  Operator → edits config.json (hw_id → pos_id mapping)

[Boot Time]
  coordinator.py → DroneConfig.__init__()
    → ConfigLoader.get_hw_id() reads .hwID → hw_id (str)
    → ConfigLoader.read_config() reads config.json → pos_id (int)
    → ConfigLoader.load_all_configs() → all positions from trajectory CSVs

[Runtime]
  heartbeat_sender.py → POST {hw_id, pos_id, detected_pos_id} to GCS
  drone_communicator.py → broadcast telemetry with hw_id, pos_id
  pos_id_auto_detector.py → sets detected_pos_id from GPS

[Mission Execution]
  drone_show.py / smart_swarm.py → loads "Drone {pos_id}.csv" trajectory

[GCS Server]
  Stores heartbeats by hw_id
  Polls telemetry by hw_id
  Sends commands targeting pos_ids (or all)
  Validates config: duplicate pos_id, missing trajectories, role swaps
```

---

## 3. Industry Best Practices Comparison

### 3.1 Verge Aero

- Uses concept of **"slots"** = geo-locked coordinates matching trajectory starting positions
- Drones are **fungible** — "every drone is the same and can be placed at any location"
- **Smart Slotting** algorithm considers entire fleet state, minimizes total distance
- **Continuous mode** auto-assigns as operators place drones in field
- Drone identity is separate from show position (same concept as hw_id vs pos_id)

**Key insight:** Verge Aero's system is fully automated — operators just place drones, the GCS auto-assigns positions. MDS could benefit from similar automation.

### 3.2 Skybrush (CollMot)

- Distinguishes **Physical IDs** (hardware) from **Show IDs** (prefixed with 's', like 's05')
- Show IDs correspond to specific trajectories
- **Automatic assignment** based on GPS proximity to takeoff positions
- **Manual assignment** also supported
- Has "Assign spares" feature for spare drone management
- Limitation: MAVLink `SYSID_THISMAV` limited to 1 byte (max ~250 drones per network)
- For >250 drones: `SHOW_GROUP` parameter extends address space (Skybrush Sidekick 1.8.0+)
- "Adapt show to venue" feature (June 2025) allows remapping takeoff positions on-site

**Key insight:** Skybrush uses the exact same Physical ID vs Show ID pattern as MDS's hw_id vs pos_id. This validates MDS's architectural decision.

### 3.3 PX4/ArduPilot Standards

- `MAV_SYS_ID` / `SYSID_THISMAV` = unique per physical drone (1-254)
- Each drone gets unique UDP port (14540 + N)
- System ID is permanent to the airframe, not the mission role
- Industry standard: **system ID = hardware identity**, mission role assigned separately

### 3.4 Academic Research

- **U-SMART Framework (2024)**: Unified Swarm Management and Resource Tracking — modular design allows adding/replacing agents (identity-agnostic slots) dynamically. FAA Remote ID requirements as a constraint.
- **UAV Swarms: Research, Challenges, and Future Directions (Springer, 2025)**: AI-driven reconfiguration allows drones to "switch roles by loading different behavior modules."
- **Generative AI for Unmanned Vehicle Swarms (arXiv, 2024)**: Unified scheduling where drones negotiate tasks and dynamically adjust routes — runtime identity/role reassignment.

### 3.5 Cross-Cutting Industry Patterns

1. **Two-layer identity model** — All mature platforms decouple hardware ID from mission/slot ID
2. **GPS-based slot resolution** — Pre-flight assignment by physical position, not pre-flashed config
3. **Companion computer as identity broker** — Show identity layer on companion, insulated from autopilot SYSID
4. **Continuous/automatic re-slotting** — Runtime identity reassignment = operational hot-swap
5. **MAVLink SYSID is the hard constraint** — 1-byte (1-255) ceiling for MAVLink-based fleets

### 3.6 Summary: MDS vs Industry

| Aspect | Verge Aero | Skybrush | PX4 Standard | MDS Current |
|--------|-----------|----------|--------------|-------------|
| Hardware ID | Implicit (radio ID) | Physical ID | MAV_SYS_ID | hw_id (.hwID file) |
| Show Position | Slot (geo-locked) | Show ID (s01, s02) | N/A | pos_id |
| Auto-assignment | Smart Slotting | GPS proximity | N/A | PosIDAutoDetector |
| Hot-swap | Place & auto-assign | Assign spares button | Manual param change | Edit config.json + restart |
| Spare management | Automatic | Assign spares feature | Manual | Manual (config.json) |

**Conclusion:** MDS's hw_id/pos_id concept is architecturally correct and matches industry best practices. The implementation needs cleanup.

---

## 4. Bugs & Issues Found

### 4.1 CRITICAL

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| C1 | **[RESOLVED]** ~~4 duplicate `read_hw_id()` implementations~~ | Consolidated to `ConfigLoader.get_hw_id()` | All callers delegate to single source |
| C2 | **[RESOLVED]** ~~hw_id type inconsistency: str vs int~~ | All code | Standardized to `int` internally, `str` only for CSV/JSON |
| C3 | **[RESOLVED]** ~~config.csv has duplicate pos_id values~~ | `config.json` | Fixed: unique pos_ids 1-10 assigned |
| C4 | **[RESOLVED]** ~~config.csv has deprecated x,y columns~~ | `config.json` | Fixed: migrated to JSON format |
| C5 | **[RESOLVED]** ~~`multiple_sitl.sh` reads x,y by column position~~ | `multiple_sitl.sh` | Fixed: reads from trajectory CSV via pos_id |
| C6 | **[RESOLVED]** ~~Schema `DroneConfig` has `connection_str` field~~ | `schemas.py` | Fixed: replaced with `mavlink_port` |

### 4.2 MODERATE

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| M1 | **`detected_pos_id=0` ambiguous** | `drone_state.py` L70, `schemas.py` L73 | 0 means "undetected" but `pos_id >= 0` is valid per schema |
| M2 | **Schema says "Position ID (0-based)"** | `schemas.py` L73 | All actual usage is 1-based (Drone 1, Drone 2...) |
| M3 | **Telemetry passes pos_id to `update()` but silently ignored** | `drone_communicator.py` L298, `__init__.py` L431 | Dead code — confusing |
| M4 | **Swarm follow uses hw_id, not pos_id** | `swarm.json`, `drone_state.py` L143 | If role-swapped, follower chains may break |
| M5 | **`MDS_HW_ID` in local.env not synced with .hwID** | `identity.sh`, `params.py` | Two sources of truth for same value |
| M6 | **[RESOLVED]** ~~Legacy `read_config.py` expects wrong column order~~ | Deleted | File deleted — zero callers |
| M7 | **`validate_csv_schema()` defined but never called** | `functions/file_utils.py` L124 | Unused validation code |
| M8 | **No multiple `.hwID` file protection at runtime** | `config_loader.py` L49-51 | `glob` picks first file found — filesystem-dependent order |

### 4.3 MINOR / IMPROVEMENTS

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| L1 | **Frontend `validateDrones()` rejects empty fields** | `missionConfigUtilities.js` L207 | Would reject valid SITL configs (empty serial/baudrate) |
| L2 | **No CSV schema versioning** | All CSV files | No way to detect format version |
| L3 | **Resource CSVs use old 8-column format** | `resources/*.csv` | Templates are outdated |
| L4 | **`+5` notation in swarm config** | `swarm.json` | Works but inconsistent formatting |

---

## 5. Conceptual Design Analysis

### 5.1 Is the hw_id/pos_id Split Correct?

**Yes — this is the correct design.** All major platforms use the same pattern:

| MDS Term | Verge Aero Term | Skybrush Term | Concept |
|----------|----------------|---------------|---------|
| hw_id | (implicit radio ID) | Physical ID | "Which physical drone" |
| pos_id | Slot | Show ID | "What role it plays" |

The decoupling enables:
- **Hot-swap:** Replace broken drone with spare, assign same pos_id
- **Fleet reuse:** Same drone fleet can fly different shows (different pos_id assignments)
- **Parallel prep:** Set up trajectory files by pos_id independent of which physical drones are available

### 5.2 Should Other Modes Use pos_id?

| Mode | Current hw_id/pos_id Usage | Recommendation |
|------|---------------------------|----------------|
| **Drone Show** | pos_id determines trajectory file | Correct — keep as-is |
| **Smart Swarm** | swarm.json uses hw_id for follow chains, pos_id for initial position | **Consider:** Should follow chains use pos_id? See §5.3 |
| **Leader-Follower** | Uses hw_id in swarm.json follow field | Same question as Smart Swarm |
| **Search & Rescue** | Under development | Should define: does "launch position" = pos_id? |
| **Swarm Trajectory** | Uses pos_id for trajectory file (same as drone show) | Correct — keep as-is |

### 5.3 Should swarm.json `follow` Reference hw_id or pos_id?

**Current:** `follow` references `hw_id` — "drone with hw_id=3 follows drone with hw_id=2"

**Problem scenario:**
1. Drone hw_id=2 fails
2. Spare hw_id=10 gets pos_id=2 in config.json
3. But swarm.json still says `follow=2` (hw_id=2, which is now dead)
4. Drone hw_id=3 can't find its leader!

**Options:**
- **Option A: Keep hw_id in swarm.json** — Simpler, but requires editing swarm.json when hot-swapping. Swarm relationships are about physical drones, not positions.
- **Option B: Use pos_id in swarm.json** — Better for hot-swap (spare drone inherits all relationships). But semantically changes the meaning of "follow".
- **Option C: UI auto-resolves** — Keep hw_id in swarm.json but have the UI/backend auto-update follow references when a role swap is made.

**Recommendation:** Option C — Keep the data model (hw_id), but add smart UI that warns/auto-updates when role swaps break follow chains.

### 5.4 Port Derivation from hw_id

Currently: `gRPC_port = 50040 + hw_id`

This means hw_id determines network ports. This is fine for small fleets but:
- hw_id gaps waste port space (hw_id 1,2,100 → ports 50041, 50042, 50140)
- hw_id > 65535-50040 = 15495 would overflow (unlikely but architecturally wrong)

**For military-grade:** Port assignment should be explicit in config, not derived. But for practical 100-drone fleets, this is fine.

---

## 6. File Inventory

### All files that read/write/use hw_id or pos_id:

#### Core Identity
| File | Role |
|------|------|
| `src/drone_config/config_loader.py` | Canonical `get_hw_id()`, reads config/swarm CSV |
| `src/drone_config/__init__.py` | DroneConfig facade, maps hw_id → pos_id |
| `src/drone_config/drone_config_data.py` | Immutable dataclass: `hw_id: str`, `pos_id: int` |
| `src/drone_config/drone_state.py` | `detected_pos_id`, `find_target_drone()` by hw_id |
| `src/constants.py` | `TelemetryIndex.HW_ID=1`, `POS_ID=2`, `GRPC_BASE_PORT` |

#### Mission Scripts (each has own read_hw_id!)
| File | Role |
|------|------|
| `drone_show.py` | Uses `utils.read_hw_id()`, loads `Drone {pos_id}.csv` |
| `smart_swarm.py` | Own `read_hw_id()`, reads config+swarm CSV |
| `swarm_trajectory_mission.py` | Uses `utils.read_hw_id()`, loads trajectory by pos_id |
| `actions.py` | Own `read_hw_id()`, `init_sysid` sets MAV_SYS_ID=hw_id |
| `drone_show_src/utils.py` | `read_hw_id()` returns int |

#### Communication / Telemetry
| File | Role |
|------|------|
| `src/heartbeat_sender.py` | Sends hw_id, pos_id, detected_pos_id to GCS |
| `src/drone_communicator.py` | Broadcasts telemetry with hw_id; receives & stores by hw_id |
| `src/drone_api_server.py` | Returns hw_id in command ACKs |
| `src/drone_setup.py` | Reports hw_id in execution results |
| `src/pos_id_auto_detector.py` | Auto-detects pos_id from GPS |

#### GCS Server (FastAPI)
| File | Role |
|------|------|
| `gcs-server/app_fastapi.py` | All endpoints keyed by hw_id |
| `gcs-server/config.py` | Config validation, position lookups, duplicate pos_id detection |
| `gcs-server/heartbeat.py` | Stores heartbeats by hw_id |
| `gcs-server/telemetry.py` | Polls drones by hw_id |
| `gcs-server/command.py` | Sends commands by hw_id/ip |
| `gcs-server/schemas.py` | Pydantic models with hw_id, pos_id fields |
| `gcs-server/origin.py` | Uses pos_id for position computation |

#### Frontend (React)
| File | Role |
|------|------|
| `app/.../constants/fieldMappings.js` | `HW_ID`, `POS_ID`, `DETECTED_POS_ID` constants |
| `app/.../pages/MissionConfig.js` | Config CRUD, "Reset All" sets pos_id=hw_id |
| `app/.../pages/SwarmDesign.js` | Swarm hierarchy by hw_id |
| `app/.../components/DroneConfigCard.js` | Shows hw_id, pos_id, role swap badge |
| `app/.../components/DroneCard.js` | Displays "Drone {hw_id}" |
| `app/.../components/DroneWidget.js` | Leader/follower role detection |
| `app/.../components/InitialLaunchPlot.js` | Detects hw_id != pos_id mismatch |
| `app/.../components/SaveReviewDialog.js` | Blocks save if pos_id has no trajectory |
| `app/.../components/OriginModal.js` | Uses pos_id for origin computation |
| `app/.../components/DeviationView.js` | Falls back to hw_id if pos_id missing |
| `app/.../utilities/missionConfigUtilities.js` | CSV parser (strict 6-column), export |
| legacy `app/.../pages/ImportShow.js` (removed 2026-04-03) | Historical trajectory fetch by hw_id |

#### SITL
| File | Role |
|------|------|
| `multiple_sitl/create_dockers.sh` | Creates .hwID in Docker containers |
| `multiple_sitl/startup_sitl.sh` | Reads .hwID, maps to pos_id for SITL spawn |
| `multiple_sitl/set_sys_id.py` | Sets MAV_SYS_ID from .hwID |
| `multiple_sitl/multiple_sitl.sh` | BROKEN: reads x,y by column position |

#### Setup / Provisioning
| File | Role |
|------|------|
| `tools/mds_init_lib/identity.sh` | Creates .hwID, writes local.env |
| `tools/mds_init_lib/verify.sh` | Verifies .hwID exists |
| `tools/raspberry_setup.sh` | Legacy .hwID creation |
| `tools/local.env.template` | Template with MDS_HW_ID |

#### Config Data Files
| File | Role |
|------|------|
| `config.json` | Real-mode config (JSON format with Pydantic validation) |
| `config_sitl.csv` | SITL config (correct 6-column format) |
| `swarm.json` | Real-mode swarm (follow by hw_id) |
| `swarm_sitl.csv` | SITL swarm |
| `resources/*.csv` | Template/example configs (old 8-column format) |

#### Legacy / Unused
| File | Role |
|------|------|
| `functions/read_config.py` | Annotated "legacy/unused", wrong column order |
| `functions/update_config_file.py` | Writes x,y columns (should be removed) |

---

## 7. Recommendations

### 7.1 Immediate Fixes (No Design Changes)

1. **[DONE] Fix config** — Migrated to config.json, removed x,y, fixed duplicate pos_ids
2. **[DONE] Fix `multiple_sitl.sh`** — Read positions from trajectory CSV
3. **Fix schema `DroneConfig`** — Replace `connection_str` with `mavlink_port`, fix "0-based" description
4. **Delete legacy `functions/read_config.py`**
5. **[DONE] Delete `functions/update_config_file.py`** — Legacy CSV writer removed
6. **Update resource CSVs** — Convert to 6-column format
7. **Fix `detected_pos_id` ambiguity** — Use `-1` or `None` for undetected, enforce `pos_id >= 1`

### 7.2 Code Consolidation (DRY)

1. **Consolidate `read_hw_id()`** — Delete copies in `utils.py`, `smart_swarm.py`, `actions.py`. All should use `ConfigLoader.get_hw_id()` and cast to int where needed.
2. **Standardize hw_id type** — Decide: `int` everywhere (preferred for arithmetic/port calculation) or `str` everywhere (preferred for CSV/JSON). Recommendation: **`int` internally, `str` for serialization**.
3. **Remove dead telemetry code** — Don't pass `pos_id` to `update()` in `drone_communicator.py`

### 7.3 Architectural Improvements

1. **Auto-update swarm follow chains on role swap** — When operator changes a drone's pos_id in config.json, warn if swarm.json follow chains reference the old hw_id and offer to update.
2. **Validate config.json on drone boot** — Currently drones load config without validation. Add startup check for duplicate pos_ids.
3. **Hot-swap workflow in UI** — Add a dedicated "Replace Drone" workflow:
   - Select failed drone (hw_id=3)
   - Select spare drone (hw_id=10)
   - Auto-assign pos_id=3 to hw_id=10
   - Auto-update swarm.json follow references if needed
   - Push config via git

### 7.4 Future Considerations

1. **[DONE] Move from CSV to JSON** — Config migrated to JSON with Pydantic validation and `extra='allow'` for custom fields.
2. **Central config service** — Instead of file-based config, consider a lightweight config API that drones pull from GCS on boot.
3. **Drone registry database** — For fleets > 50 drones, a SQLite or similar DB would be more appropriate than CSV.
