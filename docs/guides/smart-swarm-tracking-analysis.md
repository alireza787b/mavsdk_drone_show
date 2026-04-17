# Smart Swarm Tracking Analysis

This guide captures the operator-grade proof path for Smart Swarm follower tracking.

Use it when you need to answer a concrete question:

- does the follower still track the leader after Smart Swarm starts?
- are body-frame and NED-frame leader jogs reflected in follower motion?
- is the problem transport freshness or controller behavior?

## What It Measures

The canonical tool is:

```bash
venv/bin/python3 tools/analyze_smart_swarm_tracking.py \
  --base-url http://127.0.0.1:5000 \
  --drone-ids 1 2 3 4 \
  --leader-id 1 \
  --follower-id 2 \
  --output-dir /tmp/smart_swarm_tracking_run
```

The tool uses the same immediate command path the dashboard uses for leader jogs:

1. take off the selected cluster
2. start Smart Swarm
3. wait for formation lock
4. dwell briefly so the formation finishes settling
5. dispatch repeated jog-sized `PRECISION_MOVE` steps on the leader
6. mix `body` and `ned` frames
7. land and restore the baseline

During that run it records one follower against the leader and assignment:

- expected relative `N/E/D`
- actual relative `N/E/D`
- horizontal error
- altitude error
- leader/follower stream sequence data
- leader path, expected follower path, and actual follower path

## Why This Tool Exists

Generic operator telemetry is not the right surface for diagnosing Smart Swarm timing.

This tool samples the dedicated Smart Swarm websocket stream and lets you separate:

- frontend/browser delivery issues
- GCS command acceptance/execution issues
- leader-state freshness problems
- actual follower-controller lag

## Output Artifacts

The output directory contains:

- `smart_swarm_tracking_summary.json`
- `smart_swarm_tracking_samples.csv`
- `smart_swarm_tracking_timeseries.png`
- `smart_swarm_tracking_relative.png`
- `smart_swarm_tracking_overlay.png`
- `smart_swarm_tracking_3d.png`

Read them this way:

- `timeseries`: expected vs actual relative `N/E/D` plus horizontal/altitude error over time
- `relative`: follower relative track against expected offset for each jog stage
- `overlay`: leader path plus expected and actual follower paths in one 2D plan view
- `3d`: same proof in 3D for quick sanity checks

## Current Interpretation Rule

If the cluster is stable before jogs start and the tracked follower remains in sub-meter horizontal error during repeated jog-sized leader steps, the old stale-poll failure mode is not the primary runtime problem anymore.

At that point:

- transport is good enough for the tested path
- command flow is good enough for the tested path
- remaining variance is primarily controller/settling behavior

## Practical Notes

- run the tool from the repo venv; it depends on the same Python stack the GCS uses
- on a host machine, `requirements.txt` already includes `aiohttp` and `matplotlib`
- let the formation settle before aggressive leader motion
- test both `body` and `ned` leader moves
- keep one follower fixed as the tracked subject for comparable plots
- recreate the SITL fleet before reruns if the baseline looks dirty

## Related Guides

- [Smart Swarm Guide](../features/smart-swarm.md)
- [SITL Validation Platform](sitl-validation-platform.md)
- [SITL Comprehensive Guide](sitl-comprehensive.md)
