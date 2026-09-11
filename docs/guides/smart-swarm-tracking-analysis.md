# Two-Drone Smart Swarm Field Rehearsal

`tools/analyze_smart_swarm_tracking.py` is the evidence-gated SITL rehearsal
for the first two-aircraft field workflow. It intentionally targets H1 as the
leader and H2 as the follower; it is not a general multi-drone benchmark.

The fixed topology is NED: H2 follows H1 at `+6 m north`, zero east, and zero
vertical offset. Smart Swarm acquires that offset from H2's actual takeoff
position; no precision-move prestaging hides an acquisition defect.

## Run

Run on the validated Hetzner GCS host, with the GCS already in reconciled SITL
mode and a two-drone SITL fleet online:

```bash
venv/bin/python3 tools/analyze_smart_swarm_tracking.py \
  --base-url http://127.0.0.1:5030 \
  --api-token-file /path/to/gcs-bearer-token \
  --output-dir /mnt/HC_Volume_106468352/mds-validation/two-drone-swarm
```

The bearer token is read from the file only. Do not put a raw token on the
command line or in an environment variable. In a trusted lab deployment where
the API is intentionally unauthenticated, omit `--api-token-file`.

Before any command or temporary configuration write, the validator checks the
runtime-status endpoint and refuses to run unless the running and configured
modes both say `sitl` with no restart reconciliation pending. It never commits
the temporary swarm resource to git.

## Sequence and safety gates

1. Readiness and idle baseline for H1/H2.
2. Snapshot the complete swarm resource, then apply the temporary H1/H2 NED
   assignments with `commit=false`.
3. Paired TAKEOFF and airborne altitude proof.
4. Record initial formation error without moving H2 separately.
5. Fresh, independently advancing H1/H2 `/ws/swarm-state` samples.
6. Smart Swarm start through the dashboard's saved-cluster/session API and
   stable formation proof.
7. Repeated northward H1 precision jogs; verify displacement, H2 reacquisition,
   fresh streams, and continuing reports from both roles. Defaults are two
   1 m jogs; use `--jog-north-m 8 --repeat-jogs 2` to exercise longer catch-up.
8. Paired HOLD recovery, airborne proof, then paired LAND and idle proof.

On every SITL failure path the tool attempts LAND for each armed selected
drone, waits for both to be idle, and only then restores the complete saved
swarm resource with `commit=false`. If grounded state cannot be verified, the
restore is deferred and reported rather than mutating a live configuration.

## Evidence

The output directory contains a JSON summary, CSV samples, and plots:

- `smart_swarm_tracking_summary.json` — ordered gates, command outcomes,
  freshness evidence, cleanup/restore status, and honest PASS/FAIL result.
- `smart_swarm_tracking_samples.csv` — relative N/E and **Up** deltas (altitude
  is positive up), errors, sequence numbers, and sample age.
- `smart_swarm_tracking_timeseries.png` — expected/actual relative N/E/Up and
  horizontal/altitude error over the sequence.
- `smart_swarm_tracking_relative.png` — follower relative plan-view track.
- `smart_swarm_tracking_overlay.png` — leader and expected/actual follower
  world paths.
- `smart_swarm_tracking_3d.png` — the same paths with world Down as the third
  axis.

The plots are diagnostic evidence, not a flight-safety authorization. Review
the JSON gates and command results first.

## Related guidance

- [Smart Swarm](../features/smart-swarm.md)
- [SITL comprehensive guide](sitl-comprehensive.md)
- [SITL validation platform](sitl-validation-platform.md)
- [Agent SITL audit loop](../superpowers/specs/2026-03-26-ai-agent-sitl-audit-loop.md)
