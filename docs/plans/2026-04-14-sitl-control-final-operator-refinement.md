# SITL Control Final Operator Refinement

Date: 2026-04-14

## Scope

Final SITL Control operator-facing refinement before wider tester handoff.

## Shipped

- kept `Ops` closed by default with explicit toggle only
- kept all instance rows collapsed by default
- changed instance selection to click-open / click-close inline detail
- replaced the awkward custom-create disclosure with a cleaner adjacent
  `Custom` panel
- added confirmation dialogs for:
  - reconcile
  - add next
  - add custom
  - restart
  - remove
  - batch restart/remove
  - save image
- added filtered-scope batch actions for visible instances
- added in-dashboard image save workflow backed by
  `tools/release_sitl_image.sh`
- added minimal host resource facts/warnings
- added quieter interaction state and removed implicit panel open behavior

## API / Backend

- added `POST /api/v1/system/sitl/instances/actions`
- added `POST /api/v1/system/sitl/images/release`
- added typed request models for batch instance actions and image release
- kept operation tracking as the single long-running progress mechanism

## Validation

- focused backend tests passed
- focused frontend tests passed
- privacy scan remained clean before client sync

## Notes

- image save uses the canonical reproducible MDS release script, not
  `docker commit`
- shell/exec remains intentionally deferred
