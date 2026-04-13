# SITL Control Operator Refinement

Date: 2026-04-13

## Summary

This refinement keeps `Instances` as the primary SITL Control work surface and
moves lower-frequency information behind compact secondary panels.

## What Changed

- added `POST /api/v1/system/sitl/instances` for single-instance create
- added `Add next` and `Add one with custom ID/IP` to the dashboard
- kept reconcile as the canonical fresh-range reset/prune workflow
- collapsed `Ops` and `Images` into secondary panels
- kept repo/tag selection split and auto-populated from discovered images
- added compact repo/image identity on each instance row
- retained file-backed log fallback when Docker stdout is empty

## Operator Intent

- `Reconcile`: rebuild the requested range and prune extras
- `Add next`: append one more container without pruning
- `Add one`: create a specific sparse instance such as `drone-10`
- `Restart` / `Remove`: affect only the selected container

## Validation

- focused backend SITL Control tests: passed
- focused frontend SITL Control tests: passed
- production dashboard build: passed

## Remaining Follow-Up

- optional `stop` action
- richer image provenance comparison
- admin-only container exec if later justified
