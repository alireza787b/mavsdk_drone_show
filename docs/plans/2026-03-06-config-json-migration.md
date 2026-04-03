# Config JSON Migration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate drone fleet configuration from CSV to JSON format, add optional custom field support, and redesign the config UI with a scalable fleet table.

**Architecture:** Replace `config.csv`/`swarm.csv` with `config.json`/`swarm.json`. Update Pydantic schemas to validate JSON with `extra='allow'` for custom fields. Replace all `csv.DictReader` usage with `json.load()`. Shell scripts use `jq`. Frontend gets a reusable `FleetTable` component. No backward compatibility — clean cutover.

**Tech Stack:** Python 3.10, FastAPI, Pydantic v2, React 18, `jq` for shell, pytest

**Design Doc:** `docs/plans/2026-03-06-config-json-migration-design.md`

---

## Phase 1: Core I/O & Schemas (Foundation)

Everything else depends on this. Get the data layer right first.

### Task 1: Update Pydantic Schemas

**Files:**
- Modify: `gcs-server/schemas.py` (DroneConfig class ~lines 70-90)
- Test: `tests/test_git_sync.py` (existing schema tests), `tests/test_schema_validation.py`

**Step 1: Update DroneConfig schema**

In `gcs-server/schemas.py`, replace the existing `DroneConfig` class:

```python
class DroneConfig(BaseModel):
    """Individual drone configuration.

    Core fields are required. Optional known fields (color, notes) have defaults.
    Unknown fields are preserved via extra='allow' for user custom properties.
    """
    model_config = ConfigDict(extra='allow')

    hw_id: int = Field(..., ge=1, description="Hardware ID (unique physical drone identifier)")
    pos_id: int = Field(..., ge=1, description="Position ID (maps to trajectory 'Drone {pos_id}.csv')")
    ip: str = Field(..., pattern=r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', description="IP address")
    mavlink_port: int = Field(..., ge=1, description="MAVLink UDP port")
    serial_port: str = Field('', description="Serial port device path (empty for SITL)")
    baudrate: int = Field(0, ge=0, description="Serial baudrate (0 for SITL)")

    # Optional known fields
    color: Optional[str] = Field(None, pattern=r'^#[0-9a-fA-F]{6}$', description="UI color (hex)")
    notes: Optional[str] = Field(None, description="Operator notes")
```

Note: `mavlink_port` and `baudrate` change from `str` to `int`.

**Step 2: Add FleetConfig and SwarmConfig wrapper schemas**

```python
class FleetConfig(BaseModel):
    """Top-level config.json schema"""
    version: int = Field(1, ge=1, description="Schema version for future migration")
    drones: List[DroneConfig]

class SwarmAssignment(BaseModel):
    """Individual swarm assignment"""
    model_config = ConfigDict(extra='allow')

    hw_id: int = Field(..., ge=1, description="Hardware ID")
    follow: int = Field(0, ge=0, description="Leader hw_id to follow (0 = independent)")
    offset_n: float = Field(0.0, description="North offset in meters")
    offset_e: float = Field(0.0, description="East offset in meters")
    offset_alt: float = Field(0.0, description="Altitude offset in meters")
    body_coord: bool = Field(False, description="True = body-frame offsets, False = NED-frame")

class SwarmConfig(BaseModel):
    """Top-level swarm.json schema"""
    version: int = Field(1, ge=1, description="Schema version")
    assignments: List[SwarmAssignment]
```

**Step 3: Update test_schema_validation.py**

Fix the existing broken tests to use correct field types (int hw_id, int mavlink_port):

```python
def test_valid_config():
    config = DroneConfig(
        hw_id=1, pos_id=1, ip='192.168.1.1',
        mavlink_port=14551, serial_port='/dev/ttyS0', baudrate=57600
    )
    assert config.hw_id == 1

def test_extra_fields_preserved():
    config = DroneConfig(
        hw_id=1, pos_id=1, ip='192.168.1.1',
        mavlink_port=14551, my_custom='hello'
    )
    assert config.model_extra == {'my_custom': 'hello'}

def test_fleet_config():
    fc = FleetConfig(version=1, drones=[
        DroneConfig(hw_id=1, pos_id=1, ip='10.0.0.1', mavlink_port=14551)
    ])
    assert len(fc.drones) == 1

def test_swarm_config():
    sc = SwarmConfig(version=1, assignments=[
        SwarmAssignment(hw_id=1),
        SwarmAssignment(hw_id=3, follow=2, offset_n=-5.0, body_coord=True)
    ])
    assert sc.assignments[1].body_coord is True
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_schema_validation.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add gcs-server/schemas.py tests/test_schema_validation.py
git commit -m "feat: update schemas for JSON config — FleetConfig, SwarmConfig, extra='allow'"
```

---

### Task 2: JSON I/O Functions in file_utils.py

**Files:**
- Modify: `functions/file_utils.py`
- Test: `tests/test_file_utils.py`

**Step 1: Add JSON load/save functions**

Add to `functions/file_utils.py`:

```python
import json

def load_json(file_path: str) -> Any:
    """Load and parse a JSON file. Returns parsed data or empty dict on error."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"JSON file not found: {file_path}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {file_path}: {e}")
        return {}

def save_json(data: Any, file_path: str, indent: int = 2) -> bool:
    """Save data as pretty-printed JSON. Returns True on success."""
    try:
        os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.write('\n')  # Trailing newline for git
        return True
    except Exception as e:
        logger.error(f"Failed to save JSON to {file_path}: {e}")
        return False
```

**Step 2: Write tests**

Add to `tests/test_file_utils.py`:

```python
def test_load_json(tmp_path):
    p = tmp_path / "test.json"
    p.write_text('{"version": 1, "drones": [{"hw_id": 1}]}')
    data = load_json(str(p))
    assert data['version'] == 1
    assert len(data['drones']) == 1

def test_load_json_missing_file(tmp_path):
    data = load_json(str(tmp_path / "nonexistent.json"))
    assert data == {}

def test_save_json(tmp_path):
    p = tmp_path / "out.json"
    result = save_json({"version": 1, "drones": []}, str(p))
    assert result is True
    loaded = json.loads(p.read_text())
    assert loaded['version'] == 1
```

**Step 3: Run tests**

Run: `python3 -m pytest tests/test_file_utils.py -v`
Expected: All pass

**Step 4: Commit**

```bash
git add functions/file_utils.py tests/test_file_utils.py
git commit -m "feat: add load_json/save_json to file_utils"
```

---

### Task 3: Update config.py — Config Loading/Saving Core

**Files:**
- Modify: `gcs-server/config.py`
- Modify: `src/params.py`

**Step 1: Update params.py filenames**

In `src/params.py`, change:
- `config_csv_name` → `config_file_name`, values: `"config_sitl.json"` / `"config.json"`
- `swarm_csv_name` → `swarm_file_name`, values: `"swarm_sitl.json"` / `"swarm.json"`
- `config_url` → update URL or remove if not used
- `swarm_url` → update URL or remove if not used

**Step 2: Update config.py**

Replace CSV-based loading with JSON:

```python
from functions.file_utils import load_json, save_json

CONFIG_FILE_PATH = os.path.join(BASE_DIR, Params.config_file_name)
SWARM_FILE_PATH = os.path.join(BASE_DIR, Params.swarm_file_name)

# Required fields for validation
CONFIG_REQUIRED_FIELDS = {'hw_id', 'pos_id', 'ip', 'mavlink_port'}
SWARM_REQUIRED_FIELDS = {'hw_id'}

def load_config(file_path=None):
    """Load fleet config from JSON. Returns list of drone dicts."""
    path = file_path or CONFIG_FILE_PATH
    data = load_json(path)
    if isinstance(data, dict) and 'drones' in data:
        return data['drones']
    if isinstance(data, list):
        return data  # Accept raw list for backward compat during migration
    return []

def save_config(config, file_path=None):
    """Save fleet config as JSON with version wrapper."""
    path = file_path or CONFIG_FILE_PATH
    wrapped = {"version": 1, "drones": config}
    save_json(wrapped, path)

def load_swarm(file_path=None):
    """Load swarm config from JSON. Returns list of assignment dicts."""
    path = file_path or SWARM_FILE_PATH
    data = load_json(path)
    if isinstance(data, dict) and 'assignments' in data:
        return data['assignments']
    if isinstance(data, list):
        return data
    return []

def save_swarm(swarm, file_path=None):
    """Save swarm config as JSON with version wrapper."""
    path = file_path or SWARM_FILE_PATH
    wrapped = {"version": 1, "assignments": swarm}
    save_json(wrapped, path)
```

Remove: `CONFIG_COLUMNS`, `SWARM_COLUMNS` constants (no longer needed).

**Step 3: Run tests**

Run: `python3 -m pytest tests/ -v --timeout=60`
Expected: May have test failures from old CSV fixtures — fix in Task 5

**Step 4: Commit**

```bash
git add src/params.py gcs-server/config.py
git commit -m "feat: config.py and params.py use JSON format"
```

---

### Task 4: Convert Data Files

**Files:**
- Convert: `config.csv` → `config.json`
- Convert: `config_sitl.csv` → `config_sitl.json`
- Convert: `swarm.csv` → `swarm.json`
- Convert: `swarm_sitl.csv` → `swarm_sitl.json`
- Convert: `resources/*.csv` → `resources/*.json` (6 config + 6 swarm templates)
- Delete: all old CSV config/swarm files (NOT trajectory CSVs)

**Step 1: Write conversion script**

Create `tools/migrate_csv_to_json.py`:

```python
#!/usr/bin/env python3
"""One-time migration script: convert config/swarm CSV files to JSON."""
import csv, json, sys, os, glob

def csv_to_config_json(csv_path):
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        drones = []
        for row in reader:
            drone = {}
            for k, v in row.items():
                k = k.strip()
                if k in ('hw_id', 'pos_id', 'mavlink_port', 'baudrate'):
                    drone[k] = int(v) if v.strip() else 0
                else:
                    drone[k] = v.strip()
            drones.append(drone)
    return {"version": 1, "drones": drones}

def csv_to_swarm_json(csv_path):
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        assignments = []
        for row in reader:
            a = {}
            for k, v in row.items():
                k = k.strip()
                if k in ('hw_id', 'follow'):
                    a[k] = int(v) if v.strip() else 0
                elif k == 'body_coord':
                    a[k] = bool(int(v)) if v.strip() else False
                elif k in ('offset_n', 'offset_e', 'offset_alt'):
                    a[k] = float(v) if v.strip() else 0.0
                else:
                    a[k] = v.strip()
            assignments.append(a)
    return {"version": 1, "assignments": assignments}

def convert(csv_path, converter):
    json_path = csv_path.rsplit('.csv', 1)[0] + '.json'
    data = converter(csv_path)
    with open(json_path, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    print(f"  {csv_path} → {json_path} ({len(data.get('drones', data.get('assignments', [])))} entries)")
    return json_path

if __name__ == '__main__':
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    print("Converting config files...")
    for name in ['config.csv', 'config_sitl.csv']:
        path = os.path.join(base, name)
        if os.path.exists(path):
            convert(path, csv_to_config_json)

    print("Converting swarm files...")
    for name in ['swarm.csv', 'swarm_sitl.csv']:
        path = os.path.join(base, name)
        if os.path.exists(path):
            convert(path, csv_to_swarm_json)

    print("Converting resource templates...")
    for csv_path in glob.glob(os.path.join(base, 'resources', 'config_*.csv')):
        convert(csv_path, csv_to_config_json)
    for csv_path in glob.glob(os.path.join(base, 'resources', 'swarm_*.csv')):
        convert(csv_path, csv_to_swarm_json)

    print("\nDone. Verify JSON files, then delete old CSVs.")
```

**Step 2: Run the conversion**

```bash
python3 tools/migrate_csv_to_json.py
```

**Step 3: Verify converted files look correct**

```bash
python3 -c "import json; d=json.load(open('config.json')); print(f'{len(d[\"drones\"])} drones, version={d[\"version\"]}')"
python3 -c "import json; d=json.load(open('swarm.json')); print(f'{len(d[\"assignments\"])} assignments')"
```

**Step 4: Delete old CSV config/swarm files**

```bash
rm -f config.csv config_sitl.csv swarm.csv swarm_sitl.csv
rm -f resources/config_*.csv resources/swarm_*.csv
```

**IMPORTANT:** Do NOT delete trajectory CSVs (`shapes/` directory) — those stay CSV.

**Step 5: Update .gitignore**

Replace `online_config.csv` with `online_config.json`.

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: convert config/swarm CSV files to JSON format

Converted via tools/migrate_csv_to_json.py:
- config.csv → config.json (with version wrapper)
- swarm.csv → swarm.json (with version wrapper)
- All SITL and resource templates converted
- Old CSV files deleted (trajectory CSVs unchanged)"
```

---

### Task 5: Fix Tests & Fixtures

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/fixtures/drone_configs.py`
- Modify: `tests/test_drone_config_components.py`
- Modify: `tests/test_gcs_api_http.py`
- Modify: `tests/test_gcs_api_websocket.py`

**Step 1: Update conftest.py**

Change `config_csv_name` → `config_file_name`, `swarm_csv_name` → `swarm_file_name` in all fixtures.

**Step 2: Update drone_configs.py fixtures**

Replace `drones_to_config_csv()` with `drones_to_config_json()`:

```python
def drones_to_config_json(drones):
    """Convert drone fixtures to config.json format"""
    return {
        "version": 1,
        "drones": [d.to_config_dict() for d in drones]
    }

def drones_to_swarm_json(drones):
    """Convert drone fixtures to swarm.json format"""
    return {
        "version": 1,
        "assignments": [d.to_swarm_dict() for d in drones]
    }
```

**Step 3: Update test mocks**

In `test_drone_config_components.py`: change `.csv` references to `.json`, update mock file content from CSV strings to JSON.

In `test_gcs_api_http.py`: update `mock_config` fixture if needed (already returns dicts, should work).

**Step 4: Run all tests**

```bash
python3 -m pytest tests/ -v --timeout=60
```

Fix any remaining failures.

**Step 5: Commit**

```bash
git add tests/
git commit -m "fix: update all test fixtures and mocks for JSON config format"
```

---

### GATE 1: Verify Foundation

```bash
# All tests pass
python3 -m pytest tests/ -v --timeout=60

# No CSV config references in core code
grep -rn 'config_csv_name\|CONFIG_COLUMNS\|SWARM_COLUMNS' gcs-server/ src/ --include='*.py' | grep -v __pycache__
# Expected: 0 matches

# JSON files exist and are valid
python3 -c "import json; json.load(open('config.json')); json.load(open('swarm.json')); print('OK')"
```

---

## Phase 2: Drone-Side & Mission Files

### Task 6: Update Drone Config Loader

**Files:**
- Modify: `src/drone_config/config_loader.py`
- Modify: `src/drone_config/drone_config_data.py` (docstrings)
- Modify: `src/drone_config/__init__.py` (docstrings)

**Step 1:** Replace `csv.DictReader` usage in `config_loader.py` with JSON parsing:

```python
import json

@staticmethod
def read_file(filename: str, source: str, hw_id: int) -> Optional[Dict]:
    """Read JSON config file and return the entry matching hw_id."""
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        # Support both wrapped {"drones": [...]} and raw [...] format
        entries = data.get('drones', data) if isinstance(data, dict) else data
        for entry in entries:
            if int(entry.get('hw_id', -1)) == hw_id:
                return entry
        logger.warning(f"hw_id {hw_id} not found in {filename}")
        return None
    except Exception as e:
        logger.error(f"Error reading {source} ({filename}): {e}")
        return None
```

Update `read_swarm()` similarly — parse JSON, look for `assignments` key.

Update `load_all_configs()` — replace `csv.DictReader` with `json.load()`.

**Step 2: Update docstrings** in `drone_config_data.py` and `__init__.py` — replace "config.csv" with "config.json".

**Step 3: Run tests**

```bash
python3 -m pytest tests/test_drone_config_components.py -v
```

**Step 4: Commit**

```bash
git add src/drone_config/
git commit -m "feat: drone config loader reads JSON instead of CSV"
```

---

### Task 7: Update drone_communicator.py

**Files:**
- Modify: `src/drone_communicator.py` (~lines 84-85)

**Step 1:** Replace CSV parsing with JSON:

```python
import json
# Replace: csv.DictReader usage
with open(Params.config_file_name, 'r') as f:
    data = json.load(f)
    config_list = data.get('drones', data) if isinstance(data, dict) else data
```

**Step 2: Commit**

```bash
git add src/drone_communicator.py
git commit -m "fix: drone_communicator reads JSON config"
```

---

### Task 8: Update Mission Files

**Files:**
- Modify: `drone_show.py` — `read_config()` function
- Modify: `smart_swarm.py` — `read_config_csv()`, `read_swarm_csv()`
- Modify: `swarm_trajectory_mission.py` — `read_config()`
- Modify: `process_formation.py` — `get_config_filename()`

**Step 1:** In each file, replace `csv.DictReader` with `json.load()`. Rename functions from `*_csv` to remove the suffix. Update the filename references from `.csv` to `.json`.

Pattern for each:

```python
import json

def read_config(filename):
    with open(filename, 'r') as f:
        data = json.load(f)
    entries = data.get('drones', data) if isinstance(data, dict) else data
    # ... rest of existing logic using entries as list of dicts
```

**Step 2: Run syntax check**

```bash
python3 -m py_compile drone_show.py smart_swarm.py swarm_trajectory_mission.py process_formation.py
```

**Step 3: Commit**

```bash
git add drone_show.py smart_swarm.py swarm_trajectory_mission.py process_formation.py
git commit -m "feat: mission files read JSON config instead of CSV"
```

---

### Task 9: Update Other Python Files

**Files:**
- Modify: `src/drone_api_server.py` — path reference
- Modify: `coordinator.py` — file existence check
- Modify: `tools/rtk_streamer_gui/main.py` — JSON parsing

**Step 1:** Update each file's config file references and parsing.

**Step 2: Commit**

```bash
git add src/drone_api_server.py coordinator.py tools/rtk_streamer_gui/main.py
git commit -m "fix: update remaining Python files for JSON config"
```

---

### GATE 2: Verify Python Layer

```bash
# Syntax check all modified Python files
python3 -m py_compile gcs-server/app_fastapi.py gcs-server/config.py gcs-server/schemas.py \
  src/params.py src/drone_config/config_loader.py src/drone_communicator.py \
  drone_show.py smart_swarm.py coordinator.py

# All tests pass
python3 -m pytest tests/ -v --timeout=60

# Zero CSV config references in Python (excluding trajectory, migration script, and tests)
grep -rn 'csv\.DictReader\|csv\.DictWriter\|config\.csv\|swarm\.csv\|config_csv_name\|swarm_csv_name' \
  gcs-server/ src/ *.py --include='*.py' | grep -v __pycache__ | grep -v trajectory | grep -v migrate
# Expected: 0 matches
```

---

## Phase 3: Shell Scripts

### Task 10: Update multiple_sitl.sh

**Files:**
- Modify: `multiple_sitl/multiple_sitl.sh`

**Step 1:** Replace `IFS=,` CSV parsing with `jq`:

```bash
# Before:
# while IFS=, read -r csv_hw_id csv_pos_id rest; do

# After:
get_coords_from_csv() {
    local hw_id=$1
    local config_file="$script_dir/../config_sitl.json"

    # Parse pos_id from JSON config
    pos_id=$(jq -r ".drones[] | select(.hw_id == $hw_id) | .pos_id" "$config_file")

    if [[ -z "$pos_id" || "$pos_id" == "null" ]]; then
        echo "Warning: hw_id $hw_id not found in config" >&2
        return 1
    fi

    # Read x,y from trajectory CSV (unchanged — trajectories stay CSV)
    local traj_file="$script_dir/../shapes_sitl/swarm/processed/Drone ${pos_id}.csv"
    # ... existing awk logic unchanged
}
```

**Step 2:** Verify jq is available or add check:

```bash
if ! command -v jq &>/dev/null; then
    echo "Error: jq is required. Install with: apt-get install -y jq" >&2
    exit 1
fi
```

**Step 3: Syntax check and test**

```bash
bash -n multiple_sitl/multiple_sitl.sh
```

**Step 4: Commit**

```bash
git add multiple_sitl/multiple_sitl.sh
git commit -m "feat: multiple_sitl.sh reads JSON config via jq"
```

---

### Task 11: Update startup_sitl.sh

**Files:**
- Modify: `multiple_sitl/startup_sitl.sh`

**Step 1:** Replace `IFS=,` config parsing with `jq`:

```bash
# Before:
# CONFIG_FILE="$BASE_DIR/config_sitl.csv"
# while IFS=, read -r hw_id pos_id ip mavlink_port serial_port baudrate; do

# After:
CONFIG_FILE="$BASE_DIR/config_sitl.json"

# Parse drone entry from JSON
drone_entry=$(jq -c ".drones[] | select(.hw_id == $HW_ID)" "$CONFIG_FILE")
if [[ -z "$drone_entry" ]]; then
    log_error "STARTUP" "hw_id $HW_ID not found in $CONFIG_FILE"
    exit 1
fi

pos_id=$(echo "$drone_entry" | jq -r '.pos_id')
ip=$(echo "$drone_entry" | jq -r '.ip')
mavlink_port=$(echo "$drone_entry" | jq -r '.mavlink_port')
```

**Step 2:** Add jq to Dockerfile if not present (check `multiple_sitl/Dockerfile`):

```dockerfile
RUN apt-get update && apt-get install -y jq
```

**Step 3: Syntax check**

```bash
bash -n multiple_sitl/startup_sitl.sh
```

**Step 4: Commit**

```bash
git add multiple_sitl/startup_sitl.sh
git commit -m "feat: startup_sitl.sh reads JSON config via jq"
```

---

### Task 12: Update Other Shell Scripts

**Files:**
- Modify: `tools/recovery.sh` — file existence check

**Step 1:** Update any `config.csv` references to `config.json`.

**Step 2: Commit**

```bash
git add tools/
git commit -m "fix: update shell scripts for JSON config filenames"
```

---

### GATE 3: Verify Shell Layer

```bash
# Syntax check all shell scripts
bash -n multiple_sitl/multiple_sitl.sh multiple_sitl/startup_sitl.sh

# Zero CSV config references in shell scripts
grep -rn 'config\.csv\|config_sitl\.csv\|swarm\.csv\|swarm_sitl\.csv\|IFS=,' \
  multiple_sitl/ tools/ --include='*.sh' | grep -v migrate | grep -v deprecated
# Expected: 0 matches
```

---

## Phase 4: GCS API Endpoints

### Task 13: Update app_fastapi.py Endpoints

**Files:**
- Modify: `gcs-server/app_fastapi.py`

**Step 1:** Update config save endpoint to handle JSON types:

The `/save-config-data` endpoint currently receives JSON from frontend and saves via `save_config()`. Since `save_config()` now writes JSON, the endpoint mostly just works. But update:

- Git commit messages: "config.csv" → "config.json"
- Startup log messages referencing config filenames
- The `validate_and_process_config()` — remove `x,y` stripping (already done, but verify)
- `save_swarm_route` commit message: "swarm.csv" → "swarm.json"

**Step 2:** Update `validate_and_process_config()` in `config.py` if needed — ensure it handles int types for `hw_id`, `pos_id` (no more string conversion from CSV).

**Step 3: Run API tests**

```bash
python3 -m pytest tests/test_gcs_api_http.py -v
```

**Step 4: Commit**

```bash
git add gcs-server/app_fastapi.py gcs-server/config.py
git commit -m "fix: update API endpoints and validation for JSON config"
```

---

## Phase 5: Frontend

### Task 14: Update missionConfigUtilities.js

**Files:**
- Modify: `app/dashboard/drone-dashboard/src/utilities/missionConfigUtilities.js`

**Step 1:** Update `expectedFields` and remove CSV-specific parsing:

```javascript
// Core required fields (always present)
export const CORE_FIELDS = ['hw_id', 'pos_id', 'ip', 'mavlink_port', 'serial_port', 'baudrate'];

// Known optional fields (shown in UI when present)
export const OPTIONAL_FIELDS = ['color', 'notes'];
```

**Step 2:** Update import function to accept both JSON and CSV:

```javascript
export function handleFileImport(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target.result;
      try {
        // Try JSON first
        const data = JSON.parse(text);
        const drones = data.drones || data; // Support wrapped and raw
        resolve(Array.isArray(drones) ? drones : []);
      } catch {
        // Fall back to CSV parsing
        const lines = text.trim().split('\n');
        const headers = lines[0].split(',').map(h => h.trim());
        const drones = lines.slice(1).map(line => {
          const values = line.split(',');
          const drone = {};
          headers.forEach((h, i) => { drone[h] = values[i]?.trim() || ''; });
          // Convert numeric fields
          ['hw_id', 'pos_id', 'mavlink_port', 'baudrate'].forEach(f => {
            if (drone[f]) drone[f] = parseInt(drone[f], 10) || 0;
          });
          return drone;
        });
        resolve(drones);
      }
    };
    reader.readAsText(file);
  });
}
```

**Step 3:** Update export to offer JSON (primary) and CSV (compat):

```javascript
export function exportConfigJSON(configData) {
  const data = { version: 1, drones: configData };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'config.json';
  link.click();
}

export function exportConfigCSV(configData) {
  const headers = CORE_FIELDS;
  const csv = [headers.join(','), ...configData.map(d => headers.map(h => d[h] ?? '').join(','))].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'config.csv';
  link.click();
}
```

**Step 4: Commit**

```bash
git add app/dashboard/drone-dashboard/src/utilities/missionConfigUtilities.js
git commit -m "feat: config utilities support JSON import/export"
```

---

### Task 15: Build FleetTable Component

**Files:**
- Create: `app/dashboard/drone-dashboard/src/components/FleetTable.js`
- Create: `app/dashboard/drone-dashboard/src/styles/FleetTable.css`

**Step 1:** Build the reusable FleetTable component.

Key features:
- Sortable column headers
- Inline cell editing (double-click)
- Expandable row detail panel
- Status column from heartbeat data
- Color swatch column
- Responsive: table → list at < 768px
- Footer with summary stats

The component receives `data`, `columns`, `onSave`, `onDelete`, `onAdd` as props — fully reusable for both config and swarm pages.

**Step 2:** Build the expanded row panel with:
- Serial port / baudrate fields
- Color picker input
- Notes textarea
- Key-value editor for custom fields ([+ Add Field], [× Remove])

**Step 3:** Style with design tokens from `DesignTokens.css`.

**Step 4: Commit**

```bash
git add app/dashboard/drone-dashboard/src/components/FleetTable.js \
       app/dashboard/drone-dashboard/src/styles/FleetTable.css
git commit -m "feat: FleetTable component — sortable, expandable, inline-edit"
```

---

### Task 16: Integrate FleetTable into MissionConfig.js

**Files:**
- Modify: `app/dashboard/drone-dashboard/src/pages/MissionConfig.js`
- Modify: `app/dashboard/drone-dashboard/src/components/DroneConfigCard.js` (keep as card view toggle)

**Step 1:** Replace the card-list rendering with FleetTable as default view. Keep DroneConfigCard as optional "Card View" toggle.

**Step 2:** Wire up the new optional fields (color, notes, custom) to the save flow — include all fields in the POST to `/save-config-data`.

**Step 3:** Update import/export buttons to use new JSON-first utilities.

**Step 4: Commit**

```bash
git add app/dashboard/drone-dashboard/src/pages/MissionConfig.js \
       app/dashboard/drone-dashboard/src/components/DroneConfigCard.js
git commit -m "feat: MissionConfig uses FleetTable with JSON config support"
```

---

### Task 17: Update SwarmDesign.js

**Files:**
- Modify: `app/dashboard/drone-dashboard/src/pages/SwarmDesign.js`

**Step 1:** Update import/export to handle JSON format. Replace Papa Parse CSV with JSON primary.

**Step 2:** Update field defaults — `body_coord` as boolean, not string '0'.

**Step 3:** Update header validation for JSON import.

**Step 4: Commit**

```bash
git add app/dashboard/drone-dashboard/src/pages/SwarmDesign.js
git commit -m "feat: SwarmDesign supports JSON swarm format"
```

---

### Task 18: Update Frontend Comments & UI Text

**Files:**
- Modify: Various frontend files with "config.csv" in comments/strings
- Check: legacy `ImportShow.js` (removed 2026-04-03), `QuickScoutPage.js`, `MissionPlanSidebar.js`

**Step 1:** Find and replace all "config.csv" references in user-facing text and comments.

```bash
grep -rn 'config\.csv\|swarm\.csv' app/dashboard/ --include='*.js' --include='*.jsx'
```

**Step 2:** Update each occurrence.

**Step 3: Commit**

```bash
git add app/dashboard/
git commit -m "fix: update frontend text and comments for JSON config"
```

---

### GATE 4: Verify Frontend

```bash
# Zero CSV config references in frontend code
grep -rn 'config\.csv\|swarm\.csv\|expectedFields.*baudrate' \
  app/dashboard/drone-dashboard/src/ --include='*.js' | grep -v node_modules
# Expected: Only export-CSV utility (intentional backward compat)

# If build environment available:
# cd app/dashboard/drone-dashboard && npm run build
```

---

## Phase 6: Documentation & Cleanup

### Task 19: Update All Documentation

**Files:**
- Modify: `docs/configuration_architecture.md`
- Modify: `docs/features/git-sync.md`
- Modify: `docs/features/swarm-trajectory.md`
- Modify: `docs/guides/csv-migration.md` → rename/replace with JSON guide
- Modify: `docs/TODO_deferred.md`
- Modify: `docs/README.md`
- Modify: `docs/apis/gcs-api-server.md`
- Modify: `docs/research/hw_id_pos_id_research.md`

**Step 1:** Update all docs to reference JSON format, new filenames, new schema examples.

**Step 2:** Create `docs/guides/config-json-format.md` — user guide for the JSON config format including how to add custom fields.

**Step 3: Commit**

```bash
git add docs/
git commit -m "docs: update all documentation for JSON config migration"
```

---

### Task 20: Final Grep Audit & Cleanup

**Step 1: Run exhaustive grep audit**

```bash
echo "=== CSV config references in Python ==="
grep -rn 'config\.csv\|config_csv\|swarm\.csv\|swarm_csv\|CONFIG_COLUMNS\|SWARM_COLUMNS\|DictReader\|DictWriter' \
  gcs-server/ src/ *.py functions/ --include='*.py' | grep -v __pycache__ | grep -v trajectory | grep -v migrate | grep -v deprecated

echo "=== CSV config references in shell ==="
grep -rn 'config\.csv\|config_sitl\.csv\|swarm\.csv\|swarm_sitl\.csv' \
  multiple_sitl/ tools/ scripts/ --include='*.sh' | grep -v migrate | grep -v deprecated

echo "=== CSV config references in frontend ==="
grep -rn 'config\.csv\|swarm\.csv' app/dashboard/drone-dashboard/src/ --include='*.js' | grep -v node_modules | grep -v exportConfigCSV

echo "=== CSV config references in docs ==="
grep -rn 'config\.csv\|swarm\.csv' docs/ --include='*.md' | grep -v 'plan\|CHANGELOG\|deprecated'
```

Expected: Zero matches (except intentional CSV export utility and historical changelog).

**Step 2:** Fix any remaining references found.

**Step 3: Run full test suite**

```bash
python3 -m pytest tests/ -v --timeout=60
```

**Step 4: Commit any remaining fixes**

```bash
git add -A
git commit -m "fix: final cleanup — remove all legacy CSV config references"
```

---

### GATE 5: Final Verification

```bash
# 1. All tests pass
python3 -m pytest tests/ -v --timeout=60

# 2. All Python files compile
find gcs-server/ src/ -name '*.py' ! -path '*__pycache__*' -exec python3 -m py_compile {} +

# 3. All shell scripts parse
bash -n multiple_sitl/multiple_sitl.sh multiple_sitl/startup_sitl.sh

# 4. JSON files are valid
python3 -c "
import json, glob
for f in ['config.json', 'config_sitl.json', 'swarm.json', 'swarm_sitl.json']:
    json.load(open(f))
    print(f'OK: {f}')
for f in glob.glob('resources/*.json'):
    json.load(open(f))
    print(f'OK: {f}')
"

# 5. Zero legacy references
grep -rn 'config_csv_name\|swarm_csv_name\|CONFIG_COLUMNS\|SWARM_COLUMNS' \
  gcs-server/ src/ --include='*.py' | grep -v __pycache__
# Expected: 0 matches

# 6. API smoke test (if server can run)
# python3 gcs-server/app_fastapi.py &
# curl -s localhost:5000/get-config-data | python3 -m json.tool
# curl -s localhost:5000/get-swarm-data | python3 -m json.tool
```

---

## Phase 7: Commit, Push, Tag

### Task 21: Final Commit & Tag

**Step 1: Review all changes**

```bash
git log --oneline main-candidate..HEAD
git diff --stat main-candidate..HEAD
```

**Step 2: Push**

```bash
git push origin main-candidate
```

**Step 3: Tag**

```bash
git tag v4.5.0-config-json
git push origin v4.5.0-config-json
```
