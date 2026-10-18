# Swarm operator workspace

Shared controls on Overview and Operate replace independent selection and start
paths. Formation editing remains separate. Three explicit actions: Takeoff,
Start Swarm, Return (sequential RTL, 10 s default). Node admission remains the
authority; no flight-control gains or PX4 checks change. Native RTL is not a
collision-avoidance mechanism. Observed aircraft state is separate from issuance.

## Acceptance

Focused frontend/backend regressions, production build and UI audit on Hetzner.
SITL-only two-aircraft takeoff/start/jog/stop/restart/return rehearsal; confirm
unchanged saved topology, both role reports and final landed/disarmed evidence.
REAL flight commands are not part of deployment validation.

Validated on Hetzner: 78 backend tests, 49 frontend tests, strict UI audit
(two pre-existing native-title debt findings), and production compilation.
The pinned two-aircraft SITL run verified Takeoff, both Swarm roles, a 3 m
leader jog with measured follower motion, Stop/Start, sequential RTL **10.006 s**
apart, both successful RTL callbacks, final disarm and unchanged saved topology.
JSON, telemetry CSV, altitude/timing plot and browser screenshots are retained
under the validation root's `evidence/operator-20261018/`. Browser probing opens
and cancels confirmations only; flight commands belong to the guarded SITL tool.

## Required follow-up: companion boot-sync authentication

Both companions' configured GitHub SSH origin rejected authentication during
the October 17 update (`Permission denied (publickey)`). Direct validated Git
patch transfer was a temporary workaround, not a boot-update solution.
Repair the existing supported repo credential provisioning and service-user
access, read back auth health, and verify fetch plus unattended boot sync on
both grounded boards. Do not add a second security mode, embed credentials in
git, or describe automatic updates as working before this is demonstrated.
