# 2026-04-01 Dashboard UI Hardening Checkpoint

## Scope

This checkpoint resumes the recovered Swarm Trajectory / product-audit work with a dashboard-first UI hardening slice. The goal of this pass was to make the primary operator shell behave like a usable field console on phone, tablet, and desktop before handing the browser back for broader operator testing.

Audited surfaces in this slice:

- dashboard shell and sidebar
- overview / fleet summary
- command control shell
- mission trigger / mission details surfaces used inside command control
- git / sync status utilities shown in the shell

QuickScout remains explicitly deferred for a later dedicated UI pass.

## Implemented

### Operator shell and breakpoints

- moved the dashboard into a clearer tablet/mobile breakpoint strategy so the overlay sidebar engages earlier instead of keeping the fixed desktop rail too long
- cleaned mobile shell spacing so phone-width layouts stop behaving like cropped desktop canvases
- moved the desktop sidebar collapse control inside the shell and switched it to directional chevrons instead of the floating close-button treatment
- increased collapsed-shell touch targets for better tablet usability

### Theme and token cleanup

- strengthened light/dark design tokens for secondary and tertiary text contrast
- enabled explicit `color-scheme` signaling so native controls align better with light/dark mode
- replaced the confusing cycle-only sidebar theme control with an explicit selector in expanded mode and surfaced the effective mode label (`Auto (Light)` / `Auto (Dark)`)
- normalized several shell/action surfaces to the shared token system instead of leaving hardcoded palette fragments in place

### Dashboard / command-control layout

- made overview summary cards stack cleanly on phone widths
- tightened command-control header, scope card, and target-selection layout for tablet and phone widths
- preserved denser multi-card layouts on tablet/desktop so the dashboard still scans well with larger fleets
- converted narrow-screen notification behavior from overlay-style positioning to content-safe placement

### Mission diagnostics consistency

- moved placement-status color treatment in Mission Details from hardcoded hex values to design-token-driven colors
- fixed mission diagnostic sections that still used dark-biased hardcoded borders/backgrounds
- added narrow-screen wrapping for long deviation/readiness rows so the mission diagnostics do not overflow on handheld layouts

## Validation

### Local

- `CI=true npm test -- --runInBand --watch=false src/components/CommandSender.test.js src/components/MissionDetails.test.js`
- result: passed

### Hetzner

- synced updated dashboard source into the Hetzner runtime repo
- rebuilt the dashboard on Hetzner successfully
- verified the live frontend served the rebuilt assets:
  - `main.001e0e05.js`
  - `main.209effe7.css`
- captured live screenshots from the Hetzner-served build for:
  - mobile light
  - mobile dark
  - tablet light
  - tablet dark
  - desktop light
  - desktop dark

## Current Runtime Notes

At the end of the UI hardening pass, the visual dashboard state is improved and validated, but the runtime sync banner still reflects real backend state rather than stale frontend assets:

- the Hetzner runtime repo was intentionally left dirty during the live UI iteration/build cycle
- the drone containers were still reported on commit `9505ca51`
- the GCS repo still reported commit `81198551` before the final push/cleanup stage
- telemetry showed drone `3` present but stale, which is why the overview showed `3` visible drones but only `2` online links

The next operational cleanup step after committing/pushing this slice is:

1. fast-forward the Hetzner runtime repo to the pushed `main-candidate` commit and clear the temporary dirty state
2. rebuild/serve from that clean commit
3. run repo sync so the 3 SITL drones match the new GCS commit
4. verify `/git-status` and `/telemetry` again before browser handoff

## Outcome

This slice is ready to checkpoint as the dashboard/operator-console hardening pass that precedes the next broader browser test round.
