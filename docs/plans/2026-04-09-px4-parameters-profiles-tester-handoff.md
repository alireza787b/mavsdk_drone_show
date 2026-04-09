# PX4 Parameters Profiles Tester Handoff

## Scope

This checkpoint finishes the operator-facing `PX4 Parameters` v1 refinement on
top of the already validated runtime slice:

- repo-backed PX4 parameter profiles now live under
  `resources/px4_param_profiles/`
- the dashboard has three explicit workspaces:
  - `Single Drone`
  - `Batch`
  - `Profiles`
- batch scope now starts at `None`
- saved profiles are the default repeatable fleet path
- raw manual batch entry remains available only as an explicit advanced mode
- the older `Apply Common Params` shortcut is no longer shown in the action UI
- phone/tablet now use a compact parameter card list plus detail dialog instead
  of forcing a desktop table/inline inspector layout
- batch apply can now skip offline drones only after explicit operator
  confirmation
- single-drone runtime now has a tracked `Reboot PX4` control on the page
- snapshot/write/import/batch/reboot operations now show minimal inline status
  notices, not only transient toasts
- repo storage is now explicit:
  - live fleet config stays in root `config*.json` / `swarm*.json`
  - reviewed PX4 parameter profiles live in `resources/px4_param_profiles/`
  - the legacy compatibility CSV defaults to `resources/common_params.csv`

## Operator Workflow

### Single Drone

- search/select one target drone
- refresh and inspect a live PX4 snapshot
- on compact screens, tap a parameter card to open a clean inspector dialog
- open the exact PX4 docs anchor for a parameter
- save one verified parameter change
- export a QGC `.params` file
- dispatch a tracked `Reboot PX4` command when the target drone is safe to
  reboot

### Batch

- explicitly choose `All`, `Cluster`, or `Selected`
- if some drones are offline, explicitly confirm whether to skip them and apply
  only to the online subset
- apply one approved saved profile to the chosen scope
- use `Advanced Manual Entry` only for one-off overrides
- review the last batch result per drone

### Profiles

- browse approved repo profiles
- review description, tags, recommended scope, and entries
- compare a profile against the current selected drone snapshot
- export typed MDS profile JSON
- send the selected profile directly into the batch workspace

## UI / UX Decisions

- reusable fleet baselines are now first-class profiles, not hidden CSV/action
  side paths
- the operator default is safer and less noisy: no implicit fleet-wide scope,
  and no raw batch composer by default
- profile review/apply is in-browser; profile creation/edit/save-new remains
  repo-managed in v1 so approved baselines stay deliberate and reviewable
- map/search/cluster selection conventions stay aligned with the rest of MDS
  instead of introducing a new selector model just for PX4 tuning
- compact/mobile behavior now follows the same progressive-disclosure rule used
  elsewhere in MDS: keep the default surface terse, move detail/edit controls
  into a focused dialog, and keep status feedback inline and minimal

## Validation

- Hetzner focused React batch:
  - `1 suite passed`
  - `8 tests passed`
- Hetzner production build:
  - passed
- prior live PX4 parameter runtime/SITL checkpoint remains valid underneath
  this UI slice:
  - live Hetzner plan `px4_params_runtime`: passed

## Tester Targets

- Dashboard root:
  - `http://204.168.181.45:3030`
- PX4 Parameters page:
  - `http://204.168.181.45:3030/px4-parameters`
- Health:
  - `http://204.168.181.45:5000/api/v1/system/health`

## Recommended Tester Flows

1. Open `Single Drone` on phone/tablet and desktop, refresh a snapshot, tap a
   parameter, and confirm the inspector/dialog shows current value, default,
   min/max, reboot flag, and the PX4 docs link cleanly.
2. Change one safe SITL parameter on one drone, save it, and confirm the
   verified result appears in the inline status area cleanly.
3. Use the `Reboot PX4` control on one disarmed SITL drone and confirm the
   command is accepted/tracked without leaving the page.
4. Open `Profiles`, review both built-in profiles, preview one against the
   selected drone, then send it into `Batch`.
5. In `Batch`, confirm scope starts at `None`, then apply a saved profile to:
   - all drones
   - one selected subset
6. Put one target offline, confirm the page warns about it, then explicitly
   choose whether to skip the offline target before applying to the online
   subset.
7. Open `Advanced Manual Entry` and confirm it feels clearly secondary, not the
   main fleet workflow.

## Deferred After Tester Feedback

- in-browser profile authoring/edit/save-new
- richer profile revisioning / approval workflow
- final retirement of the legacy backend `APPLY_COMMON_PARAMS` path after the
  broader action-pipeline audit
- in-browser profile authoring/preset management for fleet/sample config JSONs
