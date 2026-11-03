# Formation delivery validation — 2026-11-03

## Scope

Source update for ordinary live Smart Swarm: two aircraft, pilot-owned leader,
follower with the saved formation, explicit Takeoff/Start/Hold/Managed Return.
Configuration delivery is independent of leader motion telemetry. No PX4 gain,
EKF, flight-speed, acceleration, jerk or default leader-promotion change is included.

The [moving-handover checkpoint](2026-11-01-swarm-configuration-delivery-checkpoint.md)
remains authoritative for unfinished continuous role transfer and durable
automatic-promotion persistence. Do not change leaders during a flight to test
capabilities that have not passed that acceptance gate.

## Findings and fixes

- Sequential GCS polling let offline manifest entries delay healthy aircraft
  snapshots beyond their freshness limit. Independent bounded async polling and
  per-peer outage backoff remove that coupling without relaxing freshness checks.
- Dashboard-only authentication previously treated the machine configuration
  watch differently from its HTTP resource. They now use the same policy;
  full API authentication still protects both.
- Rejected native launch preparation could be mislabeled as an outdated
  coordinated-Takeoff client. Preserve the actual blocker before checking
  capability on prepared responses. Modern node rejection responses explicitly
  advertise their protocol support. Missing observations remain fail-closed.
- Invalid recovery settings could throw before protective Hold. Validate finite,
  ordered recovery timings at startup; invalid values restore documented defaults.
- A failed rehearsal interrupted a new swarm process during initialization.
  The subsequent grounded aircraft remained in Offboard with native PX4
  armability false. Explicit Hold restored readiness, without rebooting or
  changing thresholds. The restart validator now waits for the new effective
  installation and native Offboard before judging the transition complete.
  This is not evidence that arbitrary repeated-sortie or handover behavior is
  flight-cleared.

## Evidence

All builds/tests/runs use the remote validation host, never the editing VPS.
Evidence packages use generic aircraft IDs only. Accepted rehearsals so far:

| Rehearsal | Evidence |
| --- | --- |
| Two-aircraft Takeoff, Start, live spacing, Hold, apply while held, Land | Passed; applying while held did not start a mission |
| 6m to 10m horizontal spacing, NED → Body → NED | Passed; effective revision and settled position checked |
| 4.5s local leader outage | Passed; protective Hold, stable native Offboard rejoin, saved roles unchanged |
| Managed Return, 10s interval | Passed; both aircraft returned and disarmed |
| 14s leader outage, expired recovery, explicit Stop/Start | Passed; no late automatic resume, new effective installation and native Offboard confirmed, then Hold/Land/disarm/plan restore |

The combined targeted regression suite passed **519 tests**. Do not present a
table entry as hardware evidence: these are PX4 SITL
tests. No real-aircraft arm or flight command is part of this phase.
Six additional native readiness probes after the final landing (three per
aircraft) all passed without reboot or parameter changes.

### End-of-mission modes

Do not force Hold after every landing. Existing swarm shutdown stops its own
setpoint producers and requests Offboard-stop/Hold only while it still owns
fresh airborne Offboard control. Pilot takeover, native Return/Land and disarm
take precedence. A stale or unknown ownership observation is not permission to
issue a new mode command. After an interrupted mission, a grounded Offboard
state requires an explicit operator Hold and a new native readiness check;
do not silently clear it in a background telemetry callback. Normal end-to-end
rehearsals finish grounded/disarmed, with native control released.

## Release boundary

Keep the sole working base SITL image. A clean replacement image, compressed
archive and MEGA replacement are deferred until storage permits. Runtime source
sync on an existing image is development validation, not a new pinned release.
Record source deployment separately from image provenance. Preserve customer
fleet IDs, names, offsets, origins, assets and local secrets when integrating.

## Storage and documentation

Cleanup removed unused daemon-package versions, archived system journals and
byte-identical incoming copies of retained release artifacts. Protected project
histories, flight evidence, active dependencies and the working image remain.
System journals removed by vacuum cannot be recovered; duplicate release inputs
can be recreated from retained binaries.

Public concept diagrams use synthetic geometry with no customer identities,
addresses, locations or flight assets. See the
[Smart Swarm guide](../features/smart-swarm.md#operator-model). Real evidence plots
must be reviewed for the same privacy constraints before publication. Label
concepts versus measured data and never depict staggered RTL as collision avoidance.
