# PX4 Parameter Profiles

Repo-backed PX4 parameter profiles live here.

Design rules:

- one JSON file per profile
- filename must match `profile_id`
- entries use the same typed `component_id/name/value_type/value` contract as the
  `px4-params` APIs
- GCS is the source of truth for listing/loading profiles
- drones never read these files directly

Current usage:

- operators can review these profiles in the dashboard `PX4 Parameters` page
- profiles can be exported as typed MDS JSON
- batch apply uses the same tracked `px4-params` patch-job path as manual writes

Logging profiles:

- **Routine Flight Logging** sets `SDLOG_PROFILE=1`, `SDLOG_MODE=0`: default
  flight topics, recorded from arming to disarming. Use this after diagnostics
  to remove the additional system-identification streams and long ground-time
  recording. It does not capture stationary pre-arm warnings.
- **Navigation Diagnostics** sets `SDLOG_PROFILE=9`, `SDLOG_MODE=2`: default
  plus system-identification topics, recorded from boot to shutdown. Use for a
  short, deliberate diagnostic session with sufficient SD space, then restore
  both routine values. Restoring mode alone leaves the extra topic profile.

Both profiles change only logging. Review against the installed PX4 firmware,
snapshot previous values, apply while grounded and disarmed, restart, and
verify parameter readback and actual ULog topic coverage. File size depends on
firmware, topics and duration; the routine profile is not a fixed-size promise.
Adding a repository profile does not automatically apply it to an aircraft.

`horizontal_velocity_response_trial.json` is an optional **single-aircraft
trial**, changing only `MPC_XY_VEL_P_ACC` to 2.2 (captured field baseline 1.8).
It leaves I/D, EKF, preflight checks, trajectory limits and RTL settings alone.
It is not hardware-validated or applied by boot sync. Snapshot each aircraft's
actual values and review the diff, then compare isolated hover, gentle starts,
braking and reversals before any paired-flight trial. Restore the snapshot if
oscillation/overshoot increases. The [October 4 analysis](../../docs/plans/2026-10-06-field-flight-analysis-and-next-test.md)
explains why downstream velocity response, rather than another speed-ceiling
increase, is the next tuning candidate.

Minimal shape:

```json
{
  "profile_id": "fleet_geofence_guardrail",
  "name": "Fleet Geofence Guardrail",
  "description": "Starter fleet safety baseline for geofence and RC exception handling.",
  "recommended_scope": "fleet",
  "tags": ["starter", "safety", "geofence"],
  "entries": [
    {
      "component_id": 1,
      "name": "GF_ACTION",
      "value_type": "int",
      "value": 3
    }
  ]
}
```
