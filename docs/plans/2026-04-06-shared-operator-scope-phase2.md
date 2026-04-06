## 2026-04-06 Shared Operator Scope Phase 2

### Context

External review feedback showed that Dashboard card filtering and Command Control targeting were technically explicit but operationally too disconnected. The requirement for this phase was to bridge those surfaces without silently turning card visibility into dispatch scope.

### Landed

- `Overview` now owns the current command-target state so the dashboard can present one explicit operator scope model instead of hiding command scope inside `CommandSender`.
- `CommandSender` now supports controlled scope props, so the same selected / cluster / all targeting state can be driven from higher-level pages and reused later in Mission Config and Swarm Design.
- the dashboard now exposes an explicit bridge action:
  - `Use visible cards as scope`
- `CommandSender` now exposes the same explicit bridge from inside the target panel:
  - `Use N visible cards as scope`
- card-wall filtering still remains visual until the operator applies it deliberately; there is no unsafe implicit dispatch-scope mutation.
- visible-scope adoption now leaves a persistent operator cue:
  - `scopeSource=card-wall` notice in Command Control
  - per-card `Command scope` / `Command cluster` badges on the drone wall
- the Connected Drones header now shows both visible-card count and current command-scope summary so the operator can compare them at a glance.
- the target-panel action label was clarified from `Select visible` to `Select matches`.

### Build / lint hardening found during validation

- `DroneWidget.js` now imports `PropTypes` correctly; the first Hetzner build caught the missing import.
- `CommandSender.js` now includes the controlled setter callbacks in the relevant hook dependency list; the final Hetzner build is clean again.

### Validation

- local `git diff --check`: passed
- Hetzner focused Jest:
  - `src/components/CommandSender.test.js`
  - `src/components/ControlButtons.test.js`
  - `src/components/DroneConfigCard.test.js`
  - result: `3` suites passed, `11` tests passed
- Hetzner production build:
  - result: compiled successfully

### Notes

- This phase intentionally did **not** make visible cards silently become dispatch scope.
- `TrajectoryPlanning.js` already has separate in-progress work for the next slice and is not part of this checkpoint.

### Next

- Phase 3: Trajectory Planning / Swarm Trajectory authoring-first redesign
- then Mission Config shell compression using the compact-top-shell findings from the parallel audit
