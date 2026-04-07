# 2026-04-07 Mission Config Actionable Alerts

## Scope

- Make Mission Config warning states actionable instead of passive text.
- Distinguish `origin still loading` from `origin actually missing` so the page does not show false operator warnings during fetch.
- Fix Mission preview origin handling so valid `0` latitude/longitude values remain exportable.

## What Changed

- Mission Config alert cards for duplicate hardware IDs, duplicate slots, role swaps, and origin review are now clickable operator actions instead of static banners.
- Origin status now has explicit states:
  - `Checking`
  - `Ready`
  - `Needed`
  - `Check failed`
- Clicking the origin warning or the warning-state origin summary chip now opens the Mission preview tools section and launches the origin workflow directly.
- Duplicate/role-swap alerts now reset the Mission Config filters to a review-friendly state and scroll the operator back to the relevant assignment wall region.
- `MissionLayout` now treats zero-valued latitude/longitude as valid coordinates instead of falling through the old falsy check.

## Validation

### Hetzner frontend

- `CI=true npm test -- --runInBand --watch=false MissionLayout.test.js MissionConfig.test.js`
- Result: `2` suites passed, `3` tests passed

- `npm run build`
- Result: `Compiled successfully`

## Notes

- Live Hetzner origin was reconfirmed during this slice and is currently present, so the previous `Origin needed` report was a frontend state/presentation issue rather than a missing backend origin record.
- This slice only standardizes Mission Config warning remediation. Broader app-wide warning/action standardization remains a future UX consistency task.
