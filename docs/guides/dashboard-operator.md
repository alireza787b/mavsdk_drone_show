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
- selected card styling = whether a drone is included in dispatch scope; cards
  outside dispatch are muted and show an `Out` scope control/ribbon
- preflight summary = readiness blockers before command dispatch

By default, dispatch tracks visible online/degraded drones. If the operator
manually changes target scope, the dashboard stops auto-tracking until `Use
visible` is selected again.

## Link State Semantics

Drone cards distinguish:

- live: fresh trusted heartbeat or telemetry
- recently lost: short grace window after a dropped link
- stale: link evidence is old and should not count as live
- offline: stale threshold exceeded
- never seen: configured but no accepted heartbeat or telemetry has been observed in this GCS runtime
- blocked: link is live but preflight/readiness blocks operation

The dashboard should make these states visible without forcing the operator to
open every card.

During a brief link loss, cards may keep showing last-known values with muted
styling. Treat these as situational awareness only; command readiness and
preflight state must come from fresh telemetry or an explicitly accepted
heartbeat state.

GPS fix and mappable position are separate signals. A drone can report a raw
3D GPS fix while PX4 has not yet published a valid `GLOBAL_POSITION_INT`
coordinate. In that case dashboard cards show GPS quality but mark altitude,
home distance, and map placement as pending instead of rendering `0,0,0` as a
real location.

Each card header also includes an icon-only primary-link indicator. It follows
the node-reported default route, not every active interface:

- Ethernet shows a wired-link icon.
- Wi-Fi shows a Wi-Fi icon plus compact signal bars.
- USB/HiLink modems show a USB/4G icon.
- Cellular/GSM links show a mobile-link icon.

Hover or tap the icon for SSID, interface, signal, and internet probe details.
Keep the visible card text focused on flight state; add new transport details to
this icon cluster or the drill-down panel unless they are command-critical.

## SITL And REAL Safety

The sidebar runtime badge shows whether the GCS is running in `SITL` or `REAL`.
Runtime switching is handled from GCS Runtime. Heartbeat intake is mode-fenced so
SITL and real aircraft are not mixed after a restart.

Before sending commands, verify:

- the sidebar mode is correct
- the dispatch scope count matches the intended aircraft set
- selected cards show `In` and intentionally excluded cards show `Out`
- preflight has no unresolved blockers for the current target scope

## Related Guides

- [Fleet Ops](fleet-ops.md)
- [Runtime Config Sources](runtime-config-sources.md)
- [SITL Control](sitl-control.md)
- [Smart Swarm](../features/smart-swarm.md)
- [Drone Show](../features/drone-show.md)
- [Swarm Trajectory](../features/swarm-trajectory.md)
