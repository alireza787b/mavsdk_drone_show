# Config JSON Migration — Design Document

**Date:** 2026-03-06
**Status:** Approved
**Tag:** v4.5.0-config-json

## Summary

Migrate drone fleet configuration from CSV (`config.csv`, `swarm.csv`) to JSON (`config.json`, `swarm.json`). Add support for optional/custom per-drone fields. Redesign the MissionConfig UI with a fleet table view that scales from 10 to 100+ drones.

## Motivation

- CSV can't handle optional fields cleanly (empty columns, no nesting)
- Embedding JSON in CSV cells breaks parsers
- Need extensible per-drone properties (color, notes, future: type, speed, sensors)
- Current card-based UI doesn't scale past ~20 drones
- All values in CSV are strings — no native types (int, bool, array)

## File Format

### config.json

```json
{
  "version": 1,
  "drones": [
    {
      "hw_id": 1,
      "pos_id": 1,
      "ip": "192.0.2.11",
      "mavlink_port": 14551,
      "serial_port": "/dev/ttyS0",
      "baudrate": 57600
    },
    {
      "hw_id": 2,
      "pos_id": 2,
      "ip": "192.0.2.52",
      "mavlink_port": 14552,
      "serial_port": "/dev/ttyS0",
      "baudrate": 57600,
      "color": "#FF6B00",
      "notes": "Replaced motor 2 on 2026-02-15"
    }
  ]
}
```

### config_sitl.json

```json
{
  "version": 1,
  "drones": [
    {"hw_id": 1, "pos_id": 1, "ip": "172.18.0.2", "mavlink_port": 14563, "serial_port": "", "baudrate": 0},
    {"hw_id": 2, "pos_id": 2, "ip": "172.18.0.3", "mavlink_port": 14564, "serial_port": "", "baudrate": 0}
  ]
}
```

### swarm.json

```json
{
  "version": 1,
  "assignments": [
    {"hw_id": 1, "follow": 0},
    {"hw_id": 3, "follow": 2, "offset_n": -5.0, "offset_e": -5.0, "offset_alt": 3.0, "body_coord": true}
  ]
}
```

### Design Decisions

| Decision | Rationale |
|----------|-----------|
| `version: 1` top-level field | Enables future schema migration without breaking old readers |
| `mavlink_port`, `baudrate` as numbers | Native types instead of CSV string-everything |
| `body_coord` as boolean | Semantic clarity over `0`/`1` |
| `serial_port: ""` for SITL | Consistent schema, empty string signals SITL mode |
| Separate config.json and swarm.json | Different lifecycles (hardware vs mission), different edit patterns |
| SITL/Real as separate files | Same approach as today, param-driven filename selection |
| `extra='allow'` in Pydantic | Users can add any custom fields — preserved on save |

### Known Optional Fields (v1)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `color` | string (hex) | null | Map pointer / UI accent color |
| `notes` | string | null | Operator notes for this drone |

Future fields (documented in schema as comments, not implemented):
- `drone_type`, `label`, `max_speed_ms`, `min_speed_ms`, `cruise_altitude_m`, `camera_interval_s`, `icon`

## Pydantic Schemas

```python
class DroneConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    hw_id: int = Field(..., ge=1)
    pos_id: int = Field(..., ge=1)
    ip: str = Field(..., pattern=r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')
    mavlink_port: int = Field(..., ge=1)
    serial_port: str = Field('')
    baudrate: int = Field(0, ge=0)

    # Optional known fields
    color: Optional[str] = Field(None, pattern=r'^#[0-9a-fA-F]{6}$')
    notes: Optional[str] = None

class FleetConfig(BaseModel):
    version: int = Field(1, ge=1)
    drones: List[DroneConfig]

class SwarmAssignment(BaseModel):
    model_config = ConfigDict(extra='allow')

    hw_id: int = Field(..., ge=1)
    follow: int = Field(0, ge=0)
    offset_n: float = Field(0.0)
    offset_e: float = Field(0.0)
    offset_alt: float = Field(0.0)
    body_coord: bool = Field(False)

class SwarmConfig(BaseModel):
    version: int = Field(1, ge=1)
    assignments: List[SwarmAssignment]
```

## SITL vs Real Mode

Unchanged logic — `params.py` checks for `real.mode` file:

| Mode | Config File | Swarm File |
|------|-------------|------------|
| Real | `config.json` | `swarm.json` |
| SITL | `config_sitl.json` | `swarm_sitl.json` |

`Params.config_file_name` and `Params.swarm_file_name` (renamed from `_csv_name`) determine which file is loaded.

## UI/UX Design

### Fleet Table View (Default)

Compact spreadsheet-like view. Scales to 100+ drones.

**Visible columns (default):** hw_id, pos_id, IP, Port, Status (live from heartbeat)
**Hidden until row expanded:** serial_port, baudrate, color, notes, custom fields

**Features:**
- Sortable columns (click header)
- Inline cell editing (double-click cell)
- Row expand (click row → shows detail panel below row)
- Status column: live heartbeat indicator (green/red/gray dot)
- Color swatch: if drone has `color` field, small dot in row
- Footer: "N drones | N online | N warnings"
- Sticky header on scroll

**Expanded row detail panel:**
- Serial port + baudrate (dropdowns)
- Color picker
- Notes textarea
- Custom fields as key-value editor with [+ Add Field] and [× Remove] buttons
- [Save] [Cancel] [Delete] buttons

### Card View (Toggle)

Toggle button: `[Table ●] [Cards ○]`
Cards preserved for single-drone detailed editing. Same data, different layout.

### Responsive Breakpoints

| Width | Layout |
|-------|--------|
| ≥1024px | Full table with all default columns |
| 768-1023px | Table hides Port column, compact spacing |
| <768px | List view: one row per drone (hw_id + IP + status), tap to expand |

### Import/Export

**Export dropdown:** "Download JSON" (native) / "Download CSV" (compat, core 6 fields only)
**Import:** Accepts `.json` or `.csv`, auto-detects, preview before apply

### Reusable Components

| Component | Purpose | Reused By |
|-----------|---------|-----------|
| `FleetTable` | Generic sortable/expandable table | Config page, Swarm page |
| `InlineEditCell` | Double-click-to-edit table cell | Any table |
| `KeyValueEditor` | Add/remove/reorder key-value pairs | Custom fields, future use |
| `ColorPicker` | Hex color input with swatch | Config, future use |
| `ImportExportMenu` | JSON/CSV import/export dropdown | Config, Swarm |

## Migration Scope

### Files to Change (~45 files)

**Core I/O (5 files):**
- `functions/file_utils.py` — add `load_json()`, `save_json()`, remove CSV config functions
- `gcs-server/config.py` — update load/save, remove CONFIG_COLUMNS/SWARM_COLUMNS
- `gcs-server/schemas.py` — update DroneConfig, add FleetConfig/SwarmConfig
- `gcs-server/app_fastapi.py` — update endpoints, git commit messages
- `src/params.py` — rename `config_csv_name` → `config_file_name`, update filenames/URLs

**Drone-side (5 files):**
- `src/drone_config/config_loader.py` — JSON parsing instead of csv.DictReader
- `src/drone_config/drone_config_data.py` — update docstrings
- `src/drone_config/__init__.py` — update docstrings
- `src/drone_communicator.py` — JSON parsing
- `src/drone_api_server.py` — update path reference

**Mission files (3 files):**
- `drone_show.py` — `read_config()` → JSON
- `smart_swarm.py` — `read_config_csv()`/`read_swarm_csv()` → JSON
- `swarm_trajectory_mission.py` — `read_config()` → JSON

**Shell scripts (2 files):**
- `multiple_sitl/multiple_sitl.sh` — jq instead of IFS=,
- `multiple_sitl/startup_sitl.sh` — jq instead of IFS=,

**Other Python (4 files):**
- `coordinator.py` — file existence check
- `process_formation.py` — filename reference
- `tools/rtk_streamer_gui/main.py` — JSON parsing
- `tools/recovery.sh` — file existence check

**Frontend (6 files):**
- `src/pages/MissionConfig.js` — new FleetTable component
- `src/components/DroneConfigCard.js` — adapt for JSON fields + custom fields
- `src/utilities/missionConfigUtilities.js` — remove CSV parsing, update field lists
- `src/pages/SwarmDesign.js` — update import/export
- `src/components/DroneCard.js` (swarm) — boolean body_coord
- Various comment updates (5+ files)

**Data files (12 files):**
- `config.csv` → `config.json`
- `config_sitl.csv` → `config_sitl.json`
- `swarm.csv` → `swarm.json`
- `swarm_sitl.csv` → `swarm_sitl.json`
- 6 resource templates in `resources/`
- `.gitignore` update

**Tests (5 files):**
- `tests/test_file_utils.py` — JSON test equivalents
- `tests/test_drone_config_components.py` — JSON mocks
- `tests/test_gcs_api_http.py` — update fixtures
- `tests/conftest.py` — update param names
- `tests/fixtures/drone_configs.py` — JSON generators

**Documentation (6+ files):**
- `docs/configuration_architecture.md`
- `docs/features/git-sync.md`
- `docs/features/swarm-trajectory.md`
- `docs/guides/csv-migration.md` → replace with JSON migration guide
- `docs/TODO_deferred.md`
- `docs/README.md`

## Verification Strategy

Multi-layer verification after each phase:

1. **Syntax check**: `python3 -m py_compile` on all modified Python, `bash -n` on shell scripts
2. **Unit tests**: `pytest tests/` — all must pass
3. **Grep audit**: Search for `\.csv`, `config_csv`, `swarm_csv`, `CONFIG_COLUMNS`, `SWARM_COLUMNS`, `DictReader`, `DictWriter` — zero hits in production code
4. **Shell check**: Verify `jq` parsing works with sample JSON files
5. **Frontend check**: No hardcoded CSV field arrays remain
6. **Doc check**: No references to config.csv/swarm.csv format remain in docs
7. **Integration**: Load config.json + swarm.json via API, verify endpoints return correct data
