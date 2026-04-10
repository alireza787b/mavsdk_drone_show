# PX4 Parameters Alignment Follow-Up

Date: 2026-04-10

## Why

After the grouped compact refinement, the operator review still found the
parameter rows reading as too center-weighted on touch/mobile and desktop-mode
phone layouts.

## What Changed

- rewrote the compact parameter row into a clearer operator list pattern:
  - parameter identity on the left
  - current value and safety/reference icons on the right
- removed the forced first-row selection on snapshot refresh so the page opens
  in a neutral scan state instead of pretending one parameter is already being
  edited
- tightened desktop table column alignment so the grid follows the same scan
  rule: names/groups left, current values trailing, restart state centered

## Validation

- Hetzner focused frontend suite:
  - `src/pages/Px4ParametersPage.test.js`
  - result: `11 passed`
- live browser captures checked again for mobile and tablet compact layouts

## Outcome

This follow-up is intended to make the PX4 Parameters page browse/glance
friendlier before the next operator browser pass.
