## 2026-04-07 Mission Config Card Compact Indicators

### Goal
- Reduce Mission Config card verbosity without hiding critical operator information.
- Keep the default card glanceable on mobile and desktop.
- Preserve access to slot reconciliation, runtime transport/link diagnostics, git details, and extra fields through one consistent tap-to-open pattern.

### Implemented
- Replaced the always-visible summary strip and large slot block with compact indicator buttons for:
  - Slot
  - Link
  - Git
  - Additional fields when present
- Moved detailed slot reconciliation into an on-demand inspector panel that still supports accepting heartbeat or auto-detected slot values.
- Surfaced runtime mode as a header chip and kept heartbeat state as the primary live-status badge.
- Routed git review into the existing `DroneGitStatus` detail component through the same inspector pattern.

### Validation
- Hetzner Jest: `src/components/DroneConfigCard.test.js` passed.
- Hetzner production build: passed.
