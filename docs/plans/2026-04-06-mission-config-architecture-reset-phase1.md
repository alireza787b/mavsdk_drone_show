# 2026-04-06 Mission Config Architecture Reset Phase 1

## Scope

Reset the Mission Config primary workflow so the operator reaches the assignment wall faster, can start with issue-first filters, and does not have to parse full transport/network/git detail on every card.

## Implemented

- added issue-first assignment filters alongside the existing cluster scope in `MissionConfig.js`
- kept the primary Mission Config surface focused on:
  - save/add actions
  - search
  - issue filters
  - cluster scope
  - visible-status summary
- kept lower-priority tools demoted into the secondary Mission Config panels instead of the primary work path
- compacted `DroneConfigCard` read-only mode so the default card emphasizes:
  - airframe identity
  - mission slot
  - slot verification state
  - compact runtime summary chips
- kept transport/network/git/additional metadata behind a disclosure instead of always-expanded blocks
- fixed `ControlButtons` secondary-mode layout so the secondary tools panel no longer renders with an empty primary column
- fixed the stale `PrecisionMoveDialog` hook-dependency lint warning surfaced during the build pass

## Validation

### Local

- `git diff --check`

### Hetzner

- `CI=true npm test -- --runInBand --watch=false src/components/CommandSender.test.js src/components/ControlButtons.test.js src/components/DroneConfigCard.test.js`
  - result: `3` suites passed, `10` tests passed
- `npm run build`
  - result: compiled successfully with no new lint warnings from this slice

## Notes

- validation was run against the Hetzner dashboard repo with installed frontend dependencies at `/root/mavsdk_drone_show/app/dashboard/drone-dashboard`
- the previous ssh build polling approach was replaced with a tmux/log-based remote build check to avoid spawning duplicate `react-scripts build` processes

## Next

- Phase 2: shared operator scope model between dashboard card visibility and command targeting
- Phase 3: trajectory authoring-first/mobile map fixes
