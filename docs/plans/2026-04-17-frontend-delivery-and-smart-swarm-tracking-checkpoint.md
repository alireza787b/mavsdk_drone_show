# 2026-04-17 Frontend Delivery and Smart Swarm Tracking Checkpoint

## Scope

This checkpoint closes two issues discovered during live review on the private
Hetzner stack and resolves them in the official repo first:

1. dashboard black-screen / stalled first-load behavior on weak links
2. lack of a clean, repeatable Smart Swarm tracking-proof workflow

## Frontend Delivery Findings

The live dashboard was being served by the lightweight SPA server with:

- a large uncompressed bootstrap bundle
- no immutable cache headers for fingerprinted assets
- no HTML shell cache guidance

That was enough to make first load look stuck on mobile or unstable links, even
when the app itself was healthy.

## Frontend Delivery Fixes

- added gzip support for large text assets in `tools/spa_static_server.py`
- added immutable cache headers for `/static/...`
- added `no-cache` for `/` and `index.html`
- kept SPA fallback behavior intact
- route-split `Overview` and `MissionConfig` so the bootstrap bundle shrinks

## Smart Swarm Findings

The current runtime no longer exhibits the earlier stale-state defect:

- leader freshness is coming from the dedicated Smart Swarm websocket stream
- follower command flow is executing cleanly
- repeated leader jog steps complete correctly

What still varies run-to-run is formation settling and controller response
during the first jog after acquisition. That is a control/settling question, not
the old transport pathology.

## Smart Swarm Proof Workflow Added

Added `tools/analyze_smart_swarm_tracking.py` plus focused tests.

The tool now:

- uses the same immediate precision-move path the dashboard live-jog UX uses
- records one follower against leader+offset expected state
- mixes body-frame and NED-frame jog steps
- emits JSON, CSV, and plot artifacts
- makes it possible to separate transport issues from controller issues

## Live Validation Summary

On the private Hetzner stack:

- dashboard first-load delivery improved materially after compression and route splitting
- Smart Swarm repeated jog-style leader steps completed cleanly
- follower tracking stayed in sub-meter horizontal error on the measured path

## Remaining Intentional Position

This checkpoint does **not** claim that all Smart Swarm tuning work is done.

It does claim:

- the old stale frontend asset-delivery problem is fixed
- the old stale leader-state defect is not what is dominating current follower behavior
- future tuning can now be evidence-driven instead of anecdotal
