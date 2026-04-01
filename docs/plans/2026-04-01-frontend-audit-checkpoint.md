# 2026-04-01 Frontend Audit Checkpoint

## Scope

- Recovered the prior Swarm Trajectory / full-product audit context from git history, local handoff notes, and `CHANGELOG.md`.
- Continued from the validated Hetzner SITL checkpoint instead of the dirty `/opt/mavsdk_drone_show` tree.
- Ran a live responsive audit against the Hetzner dashboard rather than only reading source.

## Live Baseline

- Hetzner GCS/dashboard runtime repo: `/root/mavsdk_drone_show_main_candidate_runtime_https`
- Clean recovery repo used for source changes: `/tmp/mavsdk_drone_show_resume`
- Branch used for local recovery work: `recovery-resume-2026-04-01`
- Last pre-audit synced runtime checkpoint before this slice: `9505ca51`

## What Was Audited

- Mobile route sweep on the live Hetzner dashboard:
  - `/`
  - `/mission-config`
  - `/globe-view`
  - `/manage-drone-show`
  - `/custom-show`
  - `/swarm-design`
  - `/swarm-trajectory`
  - `/trajectory-planning`
  - `/quickscout`
  - `/logs`
- Key state checks:
  - mobile nav overlay
  - dashboard command target selection
  - desktop light/dark captures for dashboard shell, mission config, and trajectory planning

## Implemented In This Slice

- Responsive dashboard shell and mission-control refinements were carried forward on top of the prior `9505ca51` mobile shell checkpoint.
- Added a deeper responsive pass for specialist pages:
  - `Trajectory Planning`
    - compact mobile mission brief metrics
    - mobile-first ordering that prioritizes live authoring above longer audit/policy sections
    - compact horizontal toolbar ribbon for phone widths
    - explicit mobile map container sizing for fallback map surfaces
  - `QuickScout`
    - stacked mobile top bar/search
    - mobile column layout groundwork for map + sidebar
    - explicit mobile map container sizing

## Verification Performed

- Hetzner production dashboard builds completed successfully after each frontend sync.
- Live screenshots were taken against the Hetzner dashboard in:
  - mobile light mode
  - desktop light mode
  - desktop dark mode
- Verified desktop/light/dark shell consistency for:
  - Dashboard
  - Mission Config
  - Trajectory Planning

## Findings

- The core dashboard shell is now materially better on mobile:
  - no stale left gutter
  - nav overlay behaves as expected
  - command-control and overview cards fit the viewport cleanly
- Mission Config is acceptable on mobile and strong on desktop/light/dark.
- Desktop light/dark token consistency for the audited core pages is acceptable.
- `Trajectory Planning` mobile is improved but remains the densest operator surface in the product; it is usable, but authoring is still a desktop/tablet-first workflow in practice.

## Deferred / Todo

- QuickScout is explicitly deferred from final acceptance in this slice.
- Treat the current QuickScout CSS work as groundwork only, not final operator-approved UI.
- Next pass should complete:
  - dedicated QuickScout mobile/desktop operator review
  - real-browser validation with the Mapbox token path
  - any remaining trajectory mobile polish after browser feedback

## Recommended Next Operator Test Order

1. Desktop dashboard shell, command control, mission config
2. Desktop trajectory planning authoring flow
3. Mobile dashboard shell and mission config smoke test
4. Swarm Design / Swarm Trajectory browser pass
5. QuickScout only after the deferred follow-up slice resumes

## Notes

- Heavy build/rebuild work stayed on Hetzner.
- Temporary audit screenshots were generated under `/tmp/mds_audit` and can be cleaned once this checkpoint is committed and the root report is copied.
