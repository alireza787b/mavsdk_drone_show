# Sequential Return and next field test

## Agreed scope

The first recovery mode is an interval-based queue on Smart Swarm Runtime.
Default interval: **10 seconds**, operator-editable from 1 to 300 seconds.
Review lists exact aircraft order. Stop following, confirm Hold, issue normal
tracked PX4 RTL to each aircraft in order. Wait for RTL execution confirmation,
then respect the minimum interval before the next submission. This mode does
not wait for each aircraft to land and does not assign altitude layers.

MDS owns the pending queue. Browser refresh/navigation preserves it; GCS
restart interrupts it without redispatch. Cancel remaining affects pending work;
already-issued commands continue. New MDS flight commands supersede the queue.
While waiting, pilot takeover, loss of armed Hold, stale telemetry, rejection
or unconfirmed RTL stops pending work. Normal saved roles/offsets remain intact.
Native PX4 RTL handles each issued return, including its own climb, destination,
descent, battery failsafes and pilot takeover. Timed dispatch is not collision
avoidance. Review clear return/waiting paths and battery reserve in the field.

## Flight settings recap

| Layer | Next-test decision |
| --- | --- |
| Customer MDS horizontal/vertical ceilings | Retain 6 / 1.25 m/s |
| Customer MDS acceleration/jerk | Retain 4 m/s² / 8 m/s³ |
| Outer position gain / velocity damping / feed-forward | Retain 0.5 / 0.35 / 1 |
| Position filtering / deadbands | Retain 0.35 s, XY 0.12 m / Z 0.10 m |
| Leader-loss policy | Retain bounded Hold/recovery, automatic promotion disabled |
| Stock official profile | Preserve 5 / 0.75 / 1 / 2; customer profile remains opt-in |
| PX4 horizontal velocity gain | Optional selected-aircraft trial: P 1.8 → 2.2; retain I 0.4 / D 0.2 |
| PX4 trajectory settings | Retain captured acceleration 3, maximum 5 m/s², jerk 8 m/s³; re-read actual aircraft before applying anything |
| EKF/arming thresholds, attitude gains, notch filters | No proposed blanket change supported by this flight |
| Routine logging | Apply/read back SDLOG_PROFILE=1 and SDLOG_MODE=0 while grounded |
| RTL parameters and homes | Read back before testing; this feature changes none |

The velocity-response trial is a reviewable repository profile, not an automatic
deployment. Test isolated gentle hover/starts/stops/reversal before paired flight;
restore the aircraft's captured settings if oscillation or overshoot increases.
Keep MDS shaping and EKF parameters fixed during that comparison.

Measured October 4 leader source age was median 56 ms / p95 182 ms, whereas the
downstream PX4 velocity waveform lag was approximately 0.71 s. These are waveform
measurements with alignment limits, not additive delays. The existing 6 m/s cap
already exceeded leader demand. The [full analysis](2026-10-06-field-flight-analysis-and-next-test.md)
contains evidence and tuning boundaries. Persistent compass/heading issues and
rover RTCM/RTK delivery still require field verification; base connection alone
is not rover RTK fix. Early GNSS drift cleared before takeoff in the reviewed
flight, which does not justify weakening EKF drift checks.

## Validation and release

All builds/tests run on Hetzner in an isolated validation root, separate from the
REAL client GCS. Unit/API tests cover order, minimum interval, rejection,
cancellation, stale telemetry, takeover, replay identity, restart interruption
and newer-command precedence. UI tests cover default interval, named review,
selection changes, refresh recovery, cancellation and lost-response retry.

The reusable SITL rehearsal is `tools/validate_sequential_return_runtime.py`.
It verifies canonical SITL mode before mutations, starts the reviewed saved
swarm, returns with the requested interval, checks landing/disarm and preserves
formation; JSON, CSV and altitude/timing plots are emitted. It never targets REAL.
Example:

```bash
python3 tools/validate_sequential_return_runtime.py \
  --base-url http://127.0.0.1:5038 --drone-ids 1 2 \
  --delay-sec 10 --output-dir /path/to/evidence
```

GCS/dashboard changes do not change drone-side runtime dependencies or startup.
The existing pinned SITL aircraft image can exercise the new GCS queue; a public
aircraft image rebuild is not needed for this GCS-only feature. No aircraft
gain or logging parameter is applied by copying the profiles into git.

Validated on Hetzner in `/root/mds-sequential-return-20261017.XNSX7X`:

- **55 backend/API tests passed**, including command-submission integration.
- **19 UI tests passed**, production build succeeded, strict UI audit passed
  with pre-existing debt reported separately.
- Chromium screenshots verified desktop and 390 px mobile, no horizontal
  overflow. Confirmation names the two targets and their planned interval.
- Two pinned PX4/Gazebo aircraft (`974ce185-field`, boot git/requirements sync
  disabled) passed takeoff, both Smart Swarm roles, Hold, ordered RTL **10.004 s
  apart**, both landed/disarmed, successful RTL callbacks and unchanged formation.
- `evidence/summary.json`, `telemetry.csv`, `sequential-return.png` and three UI
  screenshots contain the successful proof. This verifies the return workflow;
  it is not a new follower-control or hardware gain acceptance run.
- Initial rehearsal evidence is retained in `initial-firewall-run/`: an isolated
  validation callback port was blocked, causing a takeoff-result timeout despite
  successful flight; cleanup landed both. A temporary rule scoped to the Docker
  subnet restored callbacks before the clean passing run. REAL GCS settings and
  aircraft were not used for that rehearsal.

Deployment and Telegram delivery evidence will be recorded at handoff.
Deferred: trajectory planning, altitude layering, dynamic
collision avoidance, acceleration feed-forward and the ULog ready-retention fix.
