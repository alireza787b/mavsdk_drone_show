# Dashboard Operator Guide

This guide describes the main MDS Operations Dashboard route.

## Purpose

The dashboard is the operator's first-glance control surface for fleet status,
dispatch scope, command readiness, and high-priority mission actions.

Use it to:

- confirm which drones are online, delayed, unavailable, ready, or armed
- keep dispatch scope aligned with visible live drones
- review command preflight state before launch or recovery actions
- trigger supported missions and recovery commands
- drill into a drone card only when more detail is needed

## Operator Model

The dashboard uses a compact command model:

- visible card wall = what the operator is currently reviewing
- dispatch scope = what command actions will target
- `Use visible` = copy the currently visible commandable drones into dispatch scope
- selected card styling = whether a drone is included in dispatch scope
- preflight summary = readiness blockers before command dispatch

By default, dispatch tracks visible online/degraded drones. If the operator
manually changes target scope, the dashboard stops auto-tracking until `Use
visible` is selected again.

## Link State Semantics

Drone cards distinguish:

- online: fresh trusted telemetry
- degraded: telemetry is delayed but still recently known
- lost/offline: telemetry is stale or unavailable
- never seen: configured but no live heartbeat has been observed in this GCS session

The dashboard should make these states visible without forcing the operator to
open every card.

## SITL And REAL Safety

The sidebar runtime badge shows whether the GCS is running in `SITL` or `REAL`.
Runtime switching is handled from GCS Runtime. Heartbeat intake is mode-fenced so
SITL and real aircraft are not mixed after a restart.

Before sending commands, verify:

- the sidebar mode is correct
- the dispatch scope count matches the intended aircraft set
- preflight has no unresolved blockers
- selected/unselected cards match the operational intent

## Related Guides

- [Fleet Ops](fleet-ops.md)
- [Runtime Config Sources](runtime-config-sources.md)
- [SITL Control](sitl-control.md)
- [Smart Swarm](../features/smart-swarm.md)
- [Drone Show](../features/drone-show.md)
- [Swarm Trajectory](../features/swarm-trajectory.md)

