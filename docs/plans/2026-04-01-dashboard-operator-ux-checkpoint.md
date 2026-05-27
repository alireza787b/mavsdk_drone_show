# 2026-04-01 Dashboard Operator UX Checkpoint

## Commit

- `main-candidate`: `65db8652`
- Commit message: `Refine operator dashboard filters and theme bootstrap`

## Scope Completed

- bootstrapped theme selection before React mounts so mobile `Auto` / `Light` applies earlier and updates the browser `theme-color`
- aligned runtime font loading with the design tokens by switching the dashboard shell to `IBM Plex Sans` and `IBM Plex Mono`
- added reusable cluster-scope filtering to Dashboard Overview so the card wall now matches the Mission Config / Swarm Design filtering model
- shortened mission and action card labels while keeping fuller meaning in tooltips, confirmation flows, and detailed mission briefs
- reduced repeated wording in Command Control and renamed the dispatch metrics block to `Preflight Snapshot`
- tightened Mission Config hero/identity guidance copy for mobile readability
- improved Drone Actions, Drone Detail, and Smart Swarm light-theme surfaces so they no longer drift as far from the main shell

## Validation

### Local

- targeted tests passed:
  - `src/utilities/dronePresentation.test.js`
  - `src/components/MissionTrigger.test.js`
  - `src/components/DroneActions.test.js`
  - `src/components/CommandSender.test.js`
- result: `4/4` suites passed, `17/17` tests passed

### Hetzner

- runtime repo synced to `65db8652`
- production dashboard build completed successfully on Hetzner
- GCS restarted in tmux session `MDS-GCS`
- 3-drone SITL fleet restaged successfully
- verification:
  - `http://203.0.113.10:3030` returns `200`
  - `http://203.0.113.10:5000/health` returns `{"status":"ok"}`
  - `http://203.0.113.10:5000/api/telemetry` shows drones `1,2,3` online and `ready`
  - `http://203.0.113.10:5000/git-status` shows GCS and drones `1,2,3` synced on `65db8652`

## Screenshot Notes

- fresh live captures reviewed:
  - mobile overview
  - mobile mission config
  - desktop overview
- the live captures confirm:
  - dashboard shell and sidebar are still stable after the theme/bootstrap changes
  - command-control wording is shorter and less repetitive
  - Mission Config hero copy/chips are denser on phone width
- dark-mode automated capture remains less trustworthy than real-device review in this environment, so handheld operator confirmation is still needed from a real browser

## What To Test Next

1. Mobile dashboard in your real dark-mode phone browser:
   - verify `Auto` follows device dark mode
   - verify explicit `Light` now looks like a true light theme instead of a softened dark theme
   - verify command/action cards feel concise enough
2. Mobile Mission Config:
   - verify the top section feels informative but not noisy
   - verify search plus cluster scope are understandable
3. Swarm Design:
   - verify light/dark contrast and overall density
   - verify the cluster-scope/filter model still feels operator-friendly
4. Drone details:
   - verify contrast, tab layout, and readability on phone width

## Known Follow-Up

- QuickScout remains intentionally deferred and is not part of this UI acceptance slice yet
- a real-browser dark-mode pass is still required because headless capture is not a reliable substitute for your actual device theme behavior
