# 2026-04-01 Hetzner SITL Checkpoint

Commit: `9b4b9b4b` (`Gate drone show validator on live launch probes`)
Branch: `main-candidate`
Runtime host: `root@203.0.113.10`
Runtime repo: `/root/mavsdk_drone_show_main_candidate_runtime_https`

## What Passed

- Drone Show runtime validation passed end to end on Hetzner for drones `1,2,3`:
  - global auto
  - global manual
  - local delayed
  - custom CSV
  - single-drone LAND override drill
- Smart Swarm runtime validation passed end to end on Hetzner for drones `1,2,3`:
  - takeoff
  - cluster settle
  - in-flight reassignment
  - leader-only RTL
  - follower hold/land
  - saved swarm assignment restoration
- Swarm Trajectory runtime validation passed end to end on Hetzner for drones `1,2,3` using `--prepare-short-profile`

## Root-Cause Fixes Locked In

- Drone Show validator now recreates the SITL fleet between its internal mode runs instead of assuming completed shows leave the fleet on valid launch pads.
- Drone Show validator now gates dispatch on the same live per-drone launch-readiness probe used by backend submit validation.
- Drone Show validator now retries only the specific transient `Live launch readiness probe failed` submit rejection, instead of retrying arbitrary `HTTP 400` responses.
- Smart Swarm validator now restores selected saved follow assignments after its reassignment drill.

## Operational Note

- Drone Show / SkyBrush completion does not guarantee aircraft return to the exact original launch slots.
- Because of that, a fresh `multiple_sitl/create_dockers.sh 3` reset is the clean baseline between mission families and before browser handoff.

## Browser Handoff State

The server was restaged after validation and the dashboard stack was relaunched in production-style SITL mode.

- Dashboard URL: `http://203.0.113.10:3030`
- GCS health: `http://203.0.113.10:5000/health`
- tmux session: `MDS-GCS`

Verified after launch:

- `curl http://127.0.0.1:5000/health` -> `{"status":"ok",...}`
- `curl -I http://127.0.0.1:3030` -> `HTTP/1.0 200 OK`
- `/api/telemetry` shows drones `1,2,3` online, idle, disarmed, and ready

## Commands Used

```bash
cd /root/mavsdk_drone_show_main_candidate_runtime_https
export MDS_REPO_URL=https://github.com/alireza787b/mavsdk_drone_show.git
export MDS_BRANCH=main-candidate
export MDS_SITL_GIT_SYNC=true

bash multiple_sitl/create_dockers.sh 3
venv/bin/python tools/validate_drone_show_runtime.py \
  --base-url http://127.0.0.1:5000 \
  --repo-root /root/mavsdk_drone_show_main_candidate_runtime_https \
  --drone-ids 1 2 3 \
  --expected-show-count 5

venv/bin/python tools/validate_smart_swarm_runtime.py \
  --base-url http://127.0.0.1:5000 \
  --drones 1,2,3

venv/bin/python tools/validate_swarm_trajectory_runtime.py \
  --base-url http://127.0.0.1:5000 \
  --repo-root /root/mavsdk_drone_show_main_candidate_runtime_https \
  --drone-ids 1 2 3 \
  --prepare-short-profile

bash multiple_sitl/create_dockers.sh 3
export MDS_BRANCH=main-candidate
bash app/linux_dashboard_start.sh --prod --sitl
```

## Next Suggested Step

- Use the browser against `http://203.0.113.10:3030` and test the operator workflow.
- Keep `tmux attach -t MDS-GCS` open on the host if live backend logs are needed during browser testing.
