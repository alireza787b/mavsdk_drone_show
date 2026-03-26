# Drone Show Guide

**Mission Type:** `1` (`DRONE_SHOW_FROM_CSV`)  
**Advanced Alternate Mode:** `3` (`CUSTOM_CSV_DRONE_SHOW`)  
**Primary UI Surfaces:** `Show Design`, `Mission Config`, `Overview`

## Overview

MDS has two distinct CSV-based show workflows:

1. **Normal Drone Show**  
   Import a SkyBrush ZIP, generate one processed trajectory per drone, verify launch geometry, then schedule a synchronized multi-drone show.

2. **Custom CSV Drone Show**  
   An advanced/manual mode where every drone executes the same `active.csv` relative to its own launch frame. This is not the normal SkyBrush multi-drone pipeline.

Do not mix these mentally. The standard Drone Show path is the normal operator workflow. Custom CSV is a specialist test/research workflow.

## Standard Operator Flow

1. Open `Show Design`
2. Import a SkyBrush ZIP archive
3. Confirm the processed plots and metrics were generated
4. Open `Mission Config` and verify launch geometry / origin setup
5. Open `Overview`
6. Select `Drone Show from CSV`
7. Choose the control mode
8. Verify the launch-readiness snapshot
9. Schedule the trigger time
10. Monitor execution and be ready to send `HOLD`, `LAND`, or `RTL` if required

## Import Pipeline

`POST /import-show` now stages the incoming ZIP before replacing the live show folders. That means:

- nested ZIP layouts are accepted
- duplicate drone CSV basenames are rejected
- processed files are only swapped into the live directories after the full conversion succeeds
- the operator gets a truthful summary: raw CSV count, processed drone count, generated plots, warnings, and next steps

The related dashboard surfaces are:

- `Show Design` for import, visualization, and export
- `Mission Config` for launch geometry and origin review
- `Overview` for live readiness and mission dispatch

## Origin Behavior in Stock SITL

The official stock SITL package ships with one tracked demo default origin:

- `data/origin.sitl.default.json`
- current location: **Azadi Stadium**

Fresh SITL uses that file only as a fallback seed so first-time testers get a consistent launch-reference baseline without a manual `/set-origin`.

Important distinction:

- `data/origin.sitl.default.json` is the tracked stock demo default
- `data/origin.json` is the local runtime override created after an operator changes origin from the dashboard or API
- the runtime override is intentionally untracked and takes precedence over the packaged SITL default on that machine
- if you want to return that server to the stock Azadi baseline, remove the local `data/origin.json` runtime override

So the stock demo comes up consistent out of the box, but operators can still change origin later without editing the repository.

## Control Modes

### 1. GLOBAL mode with Auto Global Launch Corrector

**Recommended for the normal outdoor Drone Show workflow.**

- uses global GPS setpoints
- uses a shared configured origin from GCS
- validates live launch-position deviations before start
- allows approximate launch placement within the configured tolerance envelope
- aborts if a drone is too far from its expected start position

Use this when:

- operators want shared-origin correction
- GPS quality is good
- the imported SkyBrush show is the active mission

### 2. GLOBAL mode with manual placement

- uses global GPS setpoints
- does **not** use shared-origin correction
- each drone uses its own captured launch position as origin
- launch accuracy depends on precise operator placement

Use this when:

- you intentionally want the legacy manual-placement behavior
- operators can place every aircraft exactly on its intended launch point

### 3. LOCAL mode

- uses local NED feedforward setpoints
- does not require the shared-origin correction path
- waypoint zeroing uses the trajectory CSV first row
- accuracy depends entirely on local estimator quality and exact manual placement

Current implementation note:

- the launch path still captures a telemetry-derived launch position before flight
- that means LOCAL mode is the right control-path audit target today, but it is not yet the final fully GPS-independent workflow

Use this when:

- you are testing local-frame execution
- you intentionally want the local-frame control path
- you have already validated the PX4/local-estimator and launch/home-reference workflow for this deployment

### 4. Custom CSV mode

`CUSTOM_CSV_DRONE_SHOW` is intentionally **local-only**.

- every drone executes the same `shapes/active.csv` or `shapes_sitl/active.csv`
- no shared-origin correction is used
- no per-drone imported SkyBrush file selection happens here
- the dashboard now treats this as an advanced/manual path, not a normal show-import mode

Use this when:

- you authored one local-frame path and want each drone to replay it independently
- you are doing research or specialized bench/SITL testing

## Trigger Timing and Synchronization

Drone Show missions are scheduled by `triggerTime` and start through the coordinator:

- the operator can launch with a relative delay or specific time-of-day trigger
- the drone-side scheduler starts preparing slightly early via `trigger_sooner_seconds`
- the executer waits until the requested synchronized start time before beginning trajectory execution

Operational guidance:

- keep clocks synchronized, especially on real hardware
- rehearse the actual delay window you intend to use
- verify the fleet is already `READY` before scheduling the trigger

## Launch Readiness

The `Overview` mission card now checks the real blockers for the standard Drone Show path:

- imported show exists
- origin is configured when auto correction is enabled
- live telemetry is available for launch-position verification
- critical placement errors are absent

Warnings remain visible for:

- GPS-quality concerns
- manual-placement assumptions
- non-critical placement drift

That keeps the operator signal focused on actual launch blockers instead of generic page state.

## Overrides and Safety Actions

Generic flight actions remain available during or after a show:

- `HOLD`
- `LAND`
- `RTL`
- `KILL` only for true emergency cases

These are still per-drone commands. Rehearse your abort policy before flight testing so operators know when to use:

- a single-drone override
- a group/fleet action from the dashboard controls
- a mission cancel followed by explicit recovery commands

## Read-only Demo and Tester Setups

If the GCS is using the official repository over HTTPS with no authenticated push access:

- set `MDS_GIT_AUTO_PUSH=false`
- imports and saves still modify the local working tree
- the backend now fails fast instead of hanging on a username/password prompt

That is the correct mode for most SITL/demo/tester VPS setups.

For writable production workflows:

- use verified non-interactive git credentials
- keep `MDS_GIT_AUTO_PUSH=true`
- confirm the repository/branch in `/etc/mds/gcs.env`

## Custom CSV Operational Note

There is currently no equivalent SkyBrush ZIP upload UX for Custom CSV mode. The active CSV file is still an advanced/manual workflow artifact.

That is intentional for now:

- it avoids mixing the standard imported-show pipeline with a rare expert-only mode
- it keeps operator expectations clear

If later phases add a dedicated upload/editor flow for `active.csv`, it should stay visually separate from the normal Drone Show import flow.
