# PX4 Parameters Responsive Handoff Refinement

## Why This Slice Happened

The first browser smoke pass showed that the initial `PX4 Parameters` handoff
was not ready for external testers:

- phone/tablet layout was effectively desktop-first and unreadable
- parameter metadata existed in the data model but was buried in the layout
- compact row selection opened "below the table" instead of in a focused
  operator surface
- batch apply blocked too aggressively when some targets were offline
- single-drone runtime actions lacked a page-local `Reboot PX4` control
- write/read/import/batch flows relied too heavily on transient toasts instead
  of durable inline status feedback

## What Changed

### Single Drone

- added compact/mobile rendering with:
  - searchable filtered-target select
  - parameter cards instead of the full data grid
  - focused inspector dialog on row/card tap
- kept the desktop side inspector for larger screens
- surfaced metadata more clearly in compact mode:
  - current value
  - type/unit
  - default delta
  - range
  - reboot flag
  - PX4 docs link in the inspector
- added inline status notices for:
  - snapshot refresh
  - single write/verify
  - import compare/apply
  - tracked reboot command lifecycle
- added a tracked page-local `Reboot PX4` control using the existing command
  lifecycle helper and the existing `REBOOT_FC` action path

### Batch

- changed the offline-target behavior from hard stop to explicit operator choice
- if the selected scope contains offline drones, the page now:
  - warns clearly
  - requires explicit confirmation to skip offline drones
  - applies only to the online subset when confirmed
- improved the last-result summary so operators see applied/verified/failed
  counts at a glance

### Profiles

- kept the browser workflow intentionally narrow:
  - review
  - diff
  - export
  - apply in batch
- made the repo-managed profile doctrine more explicit in-page so operators know
  where add/edit/remove work actually lives today:
  - `resources/px4_param_profiles/`

## Validation

- Hetzner focused frontend suite:
  - `src/pages/Px4ParametersPage.test.js`
  - `8 passed`
- Hetzner production build:
  - passed
- the prior validated PX4 parameter runtime/SITL gate remains the runtime
  foundation under this UI-only slice:
  - `px4_params_runtime`: passed

## Deployment Note

When syncing a local worktree to Hetzner, do **not** copy the local worktree
`.git` pointer into the remote validation tree. Use plain-file sync or a real
clone, and exclude `node_modules` on subsequent syncs after `npm ci`.

## Remaining Deferred Items

- in-browser profile authoring/edit/save-new
- richer grouped/category views if live PX4 metadata quality proves consistent
- final retirement of the legacy `APPLY_COMMON_PARAMS` action path after the
  broader action-pipeline audit
