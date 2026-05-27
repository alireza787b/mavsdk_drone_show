# PX4 SITL Preflight Issue: "No connection to the GCS"

## Verified Findings (2026-03-21)

- The coordinator's `HeartbeatSender` is **not** a MAVLink heartbeat sender. It sends HTTP POST requests to the GCS API (`src/heartbeat_sender.py`), so it cannot clear PX4's `gcs_connection_lost` flag.
- Current PX4 `main` in the affected container (`53bec94205`, March 21, 2026) clears `gcs_connection_lost` only when Commander receives telemetry with `heartbeat_type_gcs`, which comes from incoming MAVLink `HEARTBEAT` messages of type `MAV_TYPE_GCS`.
- `mavlink-router` being up does not satisfy the PX4 GCS-link requirement by itself. A real MAVLink GCS client still has to send heartbeats back toward PX4.
- The earlier `param set` vs `param set-default` theory was misleading. In the same generated `rcS`, `COM_RC_IN_MODE` is set with `param set ... 4` before a later `param set-default COM_RC_IN_MODE 1`, and runtime still keeps `COM_RC_IN_MODE=4`.
- The generated `build/.../rcS` mutation is not a reliable fix point for this warning. A clean A/B repro on the live VPS container kept the warning with the rcS block present, but removed it when PX4 was launched with `PX4_PARAM_NAV_DLL_ACT=0` and `PX4_PARAM_COM_DL_LOSS_T=0`.
- Running `HEADLESS=1 make px4_sitl gz_x500` manually inside the container is **not** a valid end-to-end MDS startup test. That bypasses `multiple_sitl/startup_sitl.sh`, so it skips the MDS `PX4_PARAM_*` launch overrides and runtime `mavsdk_server` checks.

## Confirmed Root Cause

There were two separate problems:

1. The system assumed the coordinator's application heartbeat meant PX4 had a GCS connection. It does not. PX4 only cares about MAVLink `HEARTBEAT` traffic from a `MAV_TYPE_GCS` endpoint.
2. The repository was applying SITL parameter overrides by editing the generated build `rcS`. In practice, the trustworthy fix path is PX4's native `PX4_PARAM_*` launch-time override mechanism, which applies after the airframe defaults are loaded.

## Follow-up Regression Found During Verification

After the GCS/preflight issue was fixed, takeoff still failed in one rebuilt Docker image even though `is_ready_to_arm` was already `true`.

That turned out to be a separate packaging problem:

- the image had been rebuilt from a clean git checkout
- `mavsdk_server` is required at runtime by `actions.py`
- `mavsdk_server` is not tracked in git
- the clean-image rebuild accidentally removed `/root/mavsdk_drone_show/mavsdk_server`

Symptoms:

- the legacy `POST /api/send-command` path in use at that time accepted `TAKE_OFF`
- `DroneSetup` launched `actions.py`
- `actions.py` exited with code `1`
- the structured child log showed: `mavsdk_server executable not found.`

Final mitigation:

- `multiple_sitl/startup_sitl.sh` now verifies `mavsdk_server` before PX4/coordinator startup and auto-downloads it when missing
- `tools/build_custom_image.sh` now ensures `mavsdk_server` exists before committing a custom image
- mission failure logging now falls back to child `stdout` when `stderr` is empty, so the real cause is visible in the parent log

## Second Follow-up Regression Found During End-to-End Takeoff Verification

After the `mavsdk_server` packaging issue was fixed, the next `TAKE_OFF` attempt still failed in Docker SITL even though:

- `is_ready_to_arm` was `true`
- the command was accepted by the legacy `/api/send-command` path in use at that time
- `actions.py` existed and could be found

That turned out to be an application-runtime issue in our own code, not PX4 or MAVSDK:

- `DroneSetup.execute_mission_script()` used `asyncio.create_subprocess_exec()`
- in the coordinator runtime, the active event-loop policy did not provide a usable child watcher for that API
- the failure surfaced as `NotImplementedError` from `asyncio.events.get_child_watcher()`

Symptoms:

- `TAKE_OFF` was accepted
- `DroneSetup` attempted to launch `actions.py`
- mission execution failed immediately with a traceback ending in `NotImplementedError`

Final mitigation:

- `src/drone_setup.py` now keeps the normal `asyncio.create_subprocess_exec()` path when available
- if that path raises `NotImplementedError`, it falls back to `subprocess.Popen` and monitors the child via `asyncio.to_thread`
- this fix stays inside our application layer and does **not** patch or vendor-modify PX4, MAVSDK, Gazebo, or other third-party code

## Problem Statement

When running PX4 SITL with Gazebo Harmonic (`make px4_sitl gz_x500`) inside Docker
containers, the health and arming checks persistently warn:

```
WARN [health_and_arming_checks] Preflight Fail: No connection to the GCS
```

This warning appears even after `mavlink-router` is running and the coordinator is
healthy. The application was exchanging HTTP heartbeats with the GCS API, but that
traffic does **not** satisfy PX4 Commander's MAVLink GCS-link requirement. The WARN
level (not INFO) suggests `NAV_DLL_ACT > 0` at runtime, which **blocks arming**.

## Current System State (Working Except This Issue)

- **PX4**: Latest main branch (commit `53bec94205`), built with `gz_x500` target
- **Gazebo**: Harmonic 8.11.0 (gz-harmonic meta-package)
- **Container OS**: Ubuntu 22.04
- **mavlink-router**: v3, routing on `0.0.0.0:14550`
- **Coordinator**: Running, HTTP heartbeats to the GCS API working
- **Telemetry**: Drone position/velocity data routed out correctly

## Legacy Investigation Notes (Historical Only)

The sections below explain why the old rcS-mutation theory looked plausible at the time. They are retained for context only. The active fix path is **not** build-`rcS` mutation anymore; it is launch-time `PX4_PARAM_*` overrides plus ensuring `mavsdk_server` is present in the image/runtime.

### Approach 1: rcS Override Block

The retired helper previously injected a managed block into the BUILD rcS at
`build/px4_sitl_default/etc/init.d-posix/rcS`:

```bash
# BEGIN MDS SITL OVERRIDES
param set MAV_SYS_ID 1
param set COM_RC_IN_MODE 4
param set NAV_RCL_ACT 0
param set NAV_DLL_ACT 0
param set COM_DL_LOSS_T 0
param set CBRK_SUPPLY_CHK 894281
param set SDLOG_MODE -1
# END MDS SITL OVERRIDES
```

**Result**: Block is present in the build rcS. Other params apply correctly
(`COM_RC_IN_MODE: 3 -> 4`, `CBRK_SUPPLY_CHK: 0 -> 894281`). But the
`WARN [health_and_arming_checks] Preflight Fail: No connection to the GCS`
persists, indicating `NAV_DLL_ACT` is not effectively 0 at the time the check runs.

### Approach 2: Source ROMFS Modification

Also tried modifying the source ROMFS rcS and the airframe defaults directly.
**Reverted** — modifying PX4 upstream source files is not maintainable across
`git pull` updates.

## Root Cause Analysis

### PX4 Source Code (the check)

File: `src/modules/commander/HealthAndArmingChecks/checks/rcAndDataLinkCheck.cpp`

```cpp
// GCS connection
reporter.failsafeFlags().gcs_connection_lost = context.status().gcs_connection_lost;

if (reporter.failsafeFlags().gcs_connection_lost) {
    bool gcs_connection_required = _param_nav_dll_act.get() > 0;
    NavModes affected_modes = gcs_connection_required ? NavModes::All : NavModes::None;
    events::LogLevel log_level = gcs_connection_required ? events::Log::Error : events::Log::Info;

    reporter.armingCheckFailure(affected_modes, health_component_t::communication_links,
                                events::ID("check_rc_dl_no_dllink"),
                                log_level, "No connection to the ground control station");

    if (gcs_connection_required && reporter.mavlink_log_pub()) {
        mavlink_log_warning(reporter.mavlink_log_pub(), "Preflight Fail: No connection to the GCS");
    }
}
```

Key logic:
- If `NAV_DLL_ACT > 0` → GCS required → WARN level → **blocks arming**
- If `NAV_DLL_ACT == 0` → GCS not required → INFO level → does NOT block arming

### The gz_x500 Airframe Default

File: `ROMFS/px4fmu_common/init.d-posix/airframes/4001_gz_x500`

```bash
param set-default NAV_DLL_ACT 2   # RTL on data link loss
```

### rcS Execution Order

```
Line 126: param reset_all SYS_AUTOSTART SYS_PARAM_VER CAL_* ...  # Wipes all non-excluded params
Line 127: set AUTOCNF yes

Line 131: param set MAV_SYS_ID $((px4_instance+1))

Line 133: # BEGIN MDS SITL OVERRIDES
Line 136: param set NAV_DLL_ACT 0          # Our override
Line 140: # END MDS SITL OVERRIDES

Line 142: if [ $AUTOCNF = yes ]
Line 143:     param set SYS_AUTOSTART $SYS_AUTOSTART

Line 232: . "$autostart_file"              # Sources 4001_gz_x500
          # → param set-default NAV_DLL_ACT 2
```

### Historical Hypothesis (Disproven)

`param set` should override `param set-default`. After `param reset_all` wipes
everything, our `param set NAV_DLL_ACT 0` explicitly sets the value. The
airframe's subsequent `param set-default NAV_DLL_ACT 2` should NOT override it
because `param set-default` only applies when no explicit value exists.

This turned out **not** to explain the live behavior. The WARN output uses
`mavlink_log_warning` which only fires when `_param_nav_dll_act.get() > 0`, but
the reliable fix was to use PX4's launch-time `PX4_PARAM_*` override path rather
than editing the generated build `rcS`.

At the time, the working theories were:

1. `param set` after `param reset_all` does NOT properly mark the param as "user-set",
   so `param set-default` overrides it later
2. There's a second `param reset_all` or similar operation happening after our block
3. The `SYS_AUTOCONFIG=1` auto-configuration cycle has side effects we don't understand
4. `param set-default` in the current PX4 version has different semantics than expected

## Investigation Checklist Used

1. **Verify the actual runtime value** of `NAV_DLL_ACT`:
   - Connect to PX4 shell (`pxh>`) and run `param show NAV_DLL_ACT`
   - Or via MAVLink: `PARAM_REQUEST_READ` for `NAV_DLL_ACT`

2. **Test `param set` vs `param set-default` semantics** after `param reset_all`:
   - In pxh: `param reset_all && param set NAV_DLL_ACT 0 && param show NAV_DLL_ACT`
   - Then: `param set-default NAV_DLL_ACT 2 && param show NAV_DLL_ACT`
   - Does the value stay 0 or change to 2?

3. **Consider alternative approaches**:
   - Move overrides to AFTER the airframe loads (e.g., in a `4001_gz_x500.post` file)
   - Use `param set` instead of `param set-default` in the airframe itself (but this
     modifies upstream)
   - Find a PX4-standard mechanism for user overrides that runs after airframe init
   - Use environment variable `PX4_SIM_OVERRIDES` or similar if it exists

4. **Check if there's a circuit breaker** for the GCS preflight check specifically
   (like `CBRK_SUPPLY_CHK` for power supply check)

5. **Check if `gcs_connection_lost` in `context.status()` is the actual issue** —
   maybe the flag stays true despite mavlink-router being connected because the
   MAVLink heartbeat hasn't been received by Commander yet

## File References

| File | Purpose |
|------|---------|
| `multiple_sitl/startup_sitl.sh` | Main SITL startup script (lines 725-765, 870-898) |
| `multiple_sitl/create_dockers.sh` | Creates Docker containers from template |
| `PX4: src/modules/commander/HealthAndArmingChecks/checks/rcAndDataLinkCheck.cpp` | The preflight check |
| `PX4: src/modules/commander/Commander.cpp` | Sets `gcs_connection_lost` flag |
| `PX4: ROMFS/px4fmu_common/init.d-posix/airframes/4001_gz_x500` | Airframe defaults |
| `PX4: ROMFS/px4fmu_common/init.d-posix/rcS` | Main startup script |

## Environment Details

- **Remote server**: `root@203.0.113.10`
- **Docker image**: `mavsdk-drone-show-sitl:v5` (also tagged as `mavsdk-drone-show-sitl:latest`)
- **Container**: Created via `bash multiple_sitl/create_dockers.sh 1`
- **startup_sitl.sh** runs inside container at `/tmp/mds_startup_sitl.sh`
- **PX4 path inside container**: `/root/PX4-Autopilot/`
- **MDS path inside container**: `/root/mavsdk_drone_show/`
- **Build rcS**: `/root/PX4-Autopilot/build/px4_sitl_default/etc/init.d-posix/rcS`

## Success Criteria

1. PX4 SITL starts without `WARN` level "No connection to GCS" (INFO is acceptable)
2. `actions.py` can find `mavsdk_server`, so accepted `TAKE_OFF` commands can execute
3. Solution must NOT modify PX4 upstream source files (must survive `git pull`)
4. Solution must be applied cleanly via `startup_sitl.sh` and image build tooling without modifying PX4 upstream source files
5. Solution must be configurable (not hardcoded) — see `DEFAULT_SITL_PARAM_OVERRIDES`
   in `startup_sitl.sh` line 104
