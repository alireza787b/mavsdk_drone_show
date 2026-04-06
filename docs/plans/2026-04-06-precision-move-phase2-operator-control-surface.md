## 2026-04-06 Precision Move Phase 2: Operator Control Surface

### Scope

Refine the Precision Move operator dialog after the first live browser pass so the surface behaves more like an action console and less like a verbose configuration modal.

### What changed

- kept `Precision Move` as one action surface and added two explicit operator behaviors inside it:
  - `Planned Move`: compose a staged vector and then dispatch
  - `Live Jog`: each control press sends one immediate discrete Precision Move step
- kept the shared target selector as the single source of truth and retained the `Edit scope` return path
- folded custom/manual/tuning surfaces by default so the initial dialog stays compact
- made the main control pad do the primary work:
  - forward/back/left/right
  - altitude up/down
  - visible yaw left/right
  - center `Hold`
- removed the duplicate footer `Dispatch Hold` path and kept one primary abort path on the control surface
- renamed frame choices to operator-facing terms:
  - `Aircraft-relative`
  - `Map-relative`
- reduced review verbosity and only show tuning in the planned-move summary when the operator overrides it
- split live terminal-state styling so failure/timeout/interruption no longer read like clean completion

### Validation

- Hetzner focused React tests:
  - `src/components/PrecisionMoveDialog.test.js`
  - `src/components/CommandSender.test.js`
  - `src/services/gcsApiService.test.js`
  - result: `3` suites passed, `36` tests passed
- Hetzner production dashboard build: refreshed build artifact created successfully

### Operational decision

Do not split `Live Jog` into a separate action yet. It uses the same typed Precision Move contract, runtime policy, command tracking, and future MCP/API semantics. Keeping it inside the same operator surface is cleaner than creating two overlapping actions.

### Deferred

- true continuous RC-style/manual-control streaming remains deferred as a separate feature
- broader DroneSetup / runner pipeline audit remains deferred until Precision Move settles further under operator and SITL use
