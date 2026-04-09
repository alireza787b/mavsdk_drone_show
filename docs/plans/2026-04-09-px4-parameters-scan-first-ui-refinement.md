# 2026-04-09 PX4 Parameters Scan-First UI Refinement

## Goal

Address the remaining operator-facing PX4 Parameters UX issues before wider
tester handoff:

- mobile and desktop scan views still felt too dense
- parameter descriptions were visible too early in the list
- desktop-mode-on-phone still felt awkward
- the detail/edit surface needed to feel like one consistent dialog flow

## Decisions

- Keep the page scan-first. Descriptive text belongs in the parameter dialog,
  not in the list/table surface.
- Use one edit/inspection interaction across widths: row/card selection opens
  the dialog. The list is for scanning, the dialog is for reading and editing.
- Keep compact cards minimal:
  - parameter name
  - group/category identity
  - current value
  - type / restart / docs facts
- Simplify desktop table columns to the same scanning model:
  - name
  - current
  - type
  - unit
  - group
  - restart
- Keep lightweight motion only:
  - dialog fade/rise
  - existing loading pulse
  - card enter animation

## Implementation

- Removed always-visible description text from compact cards.
- Removed the desktop `Summary` column from the main table.
- Added cleaner group/category identity handling for compact cards.
- Kept metadata-heavy content in the dialog only.
- Reframed inspector sections into:
  - `Description`
  - `Current metadata`
  - `Declared enum values` when present
- Kept compact/touch widths on the dialog workflow and kept wide desktop
  row-click behavior aligned to that same dialog.
- Added a backdrop fade so the open/close interaction feels deliberate.

## Validation

- Hetzner focused frontend suite:
  - `CI=true npm test -- --runInBand --watch=false src/pages/Px4ParametersPage.test.js`
  - `11 passed`
- Hetzner production build:
  - `npm run build`
  - passed
- Live browser stack refreshed from clean sync tree:
  - frontend `HTTP 200`
  - backend health `ok`
  - active commands `0`
  - fleet telemetry `3/3` ready

## Result

The PX4 Parameters page is now closer to the intended operator model:

- scan first
- inspect second
- edit in one clear place

Remaining broader UX feedback, if any, should be taken from the next browser
test round on this cleaner baseline instead of from the older dense layout.
