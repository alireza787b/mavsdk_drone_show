# SITL Control UX Hardening

Date: 2026-04-13
Status: Implemented and validated in the official repo before private sync.

## Why this pass happened

Operator feedback from the live client stack exposed two real issues:

- restarting one container caused the whole SITL Control page to collapse back
  into a blocking loading shell
- selected-instance logs were often empty because the useful SITL startup
  output lived in file-backed runtime logs inside the container, not in Docker
  stdout/stderr

The page was also too text-heavy for scan-first use on phone/tablet/desktop.

## What changed

- restart/remove now keep the inventory visible and show only instance-local
  pending state
- SITL Control requests now use explicit timeouts so weak mobile links do not
  leave the page hanging indefinitely
- instance log retrieval now falls back from Docker logs to file-backed
  runtime logs such as `startup_sitl.log`
- the reconcile form now prefers discovered image repository/tag selectors
  instead of manual full-ref typing
- the instance inventory now has search/filter support and a compact list
  layout for larger fleets
- the operations and image sections are now more compact and scan-first

## Validation

- backend focused tests: `11 passed`
- frontend focused tests: `9 passed`

## Remaining follow-up

- optional `stop` action
- richer image/tag provenance compare UX
- optional admin-only exec console if demand still justifies it
