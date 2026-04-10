# PX4 Parameters Grouped Compact Refinement

Date: 2026-04-10

## Why

Browser review on phone and touch desktop-mode still showed the PX4 Parameters
list behaving like a squeezed table instead of a scan-first operator picker.

Main issues:

- rows felt visually centered and crowded
- too much inline metadata stayed visible in the browsing surface
- compact browsing could not reliably stay on a manually opened PX4 group
- touch/desktop-mode-on-mobile still needed to preserve the dialog workflow

## What Changed

- compact/touch browsing is now grouped by PX4 section when search is empty
- compact search still flattens matching rows for direct lookup
- compact rows now prioritize:
  - parameter name
  - current value
  - minimal safety/reference icons
- richer metadata stays in the detail dialog instead of the list row
- compact group state no longer snaps back to the selected parameter's section
  after the operator manually opens another group
- the dialog workflow remains the same on phone, tablet, and touch desktop-mode

## Validation

- Hetzner focused frontend suite:
  - `src/pages/Px4ParametersPage.test.js`
  - result: `11 passed`

## Outcome

This checkpoint is intended to make the PX4 Parameters page ready for another
browser pass before wider expert-tester handoff.
