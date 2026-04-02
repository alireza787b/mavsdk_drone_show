# 2026-04-01 Operator UI Checkpoint

## Scope

- Continued from the recovered frontend checkpoint on `origin/main-candidate` instead of the dirty `/opt/mavsdk_drone_show` tree.
- Focused this slice on the operator-critical browser path the user is actively testing:
  - Dashboard / Command Control
  - Mission Config
  - Drone detail / assignment editing
  - shared theme behavior
  - shared compact identity cues
- Kept heavy validation on Hetzner and used lightweight local screenshots only against the live Hetzner URLs for rendered UI review.

## Main Changes

- Tightened mobile/theme behavior:
  - theme application now updates document root, body, `theme-color`, and `color-scheme` together
  - light mode uses a brighter daylight shell instead of a barely softened dark shell
  - theme selector active state is more explicit
- Tightened Command Control:
  - shorter visible copy
  - compact search help disclosure instead of repeating long instructions inline
  - less decorative selection controls
  - shorter mission card labels/categories while preserving detail in tooltips/briefs
- Tightened Mission Config:
  - denser top identity summary cards
  - brighter light-theme shadows/surfaces
  - shorter identity guidance copy
  - cluster scope summary shortened and aligned with saved topology language
- Tightened Drone Detail / config editing:
  - removed several dark-only hardcoded colors from role-swap, field editor, assignment, and confirmation surfaces
  - status callouts now use shared success/info/warning/danger tokens
- Durability/docs:
  - corrected `pos_id` documentation back to 1-based
  - defined the operator shorthand `Pn|Hm`
  - added test coverage for the compact identity formatter

## Validation

- Hetzner targeted frontend tests passed:
  - `CommandSender.test.js`
  - `DroneActions.test.js`
  - `MissionDetails.test.js`
  - `dronePresentation.test.js`
  - `missionIdentityUtils.test.js`
  - `swarmDesignUtils.test.js`
  - `swarmTrajectoryLaunchReadiness.test.js`
- Result: `7` suites passed, `39` tests passed.
- Hetzner production build completed successfully after sync.
- Live rendered captures reviewed against Hetzner:
  - dashboard mobile
  - dashboard desktop
  - mission config mobile
  - mission config tablet
  - swarm design mobile

## Findings

- The actively tested operator path is now materially cleaner and more legible than the earlier broken mobile state.
- Light mode is now visually distinct in the live rendered dashboard rather than reading like slightly lighter dark mode.
- Mission Config top summary density is improved, though the button wall is still the busiest mobile block on that page.
- Swarm Design mobile is acceptable in current state, but its header copy and action cluster remain denser than Dashboard / Mission Config.
- There are still older theme leaks outside this checkpoint path, especially in some MUI-heavy Drone Show surfaces and deeper trajectory pages; those should be handled in a follow-up UI slice rather than mixed blindly into this checkpoint.

## Next Recommended Browser Pass

1. Mobile dashboard in `Auto`, `Dark`, and `Light`
2. Mobile Mission Config
3. Desktop dashboard / command control
4. Desktop Mission Config
5. Swarm Design and Swarm Trajectory

## Operator Notation

- `Pn|Hm` means `Position ID n | Hardware ID m`
- Example: `P1|H7` means the aircraft is assigned to mission slot `1` and the physical airframe identity is hardware `7`
- Use the compact form on dense operator surfaces only; keep explicit `Position ID` / `Hardware ID` labels in edit forms
