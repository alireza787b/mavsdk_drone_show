# Swarm Design validation checkpoint — 24 October 2026

## Candidate, not production

Branch: `feature/swarm-design-workspace-20261024`.
Implementation: `a1596899`; 3D interaction correction: `0cdae1be`.
The real-aircraft server and aircraft were not updated or commanded in this phase.
Unrelated local architecture notes were preserved.

## Operator behavior

- One linked draft drives Top, Side, 3D, Links, the roster and spacing fields.
- Independent clusters have separate relative origins, not invented shared positions.
- Editing is local. Apply changes the GCS plan; Publish separately saves it in Git.
- Live Apply reports effective configuration acknowledgements, not physical arrival.
- Unreachable affected aircraft require explicit confirmation of delayed adoption.
- Hold, takeover and return are not resumed by applying a design.
- The interface uses flat work areas and a compact inspector rather than nested cards.

## Verified on Hetzner

- 83 focused frontend tests passed (7 suites).
- 20 targeted backend/validation tests passed; the preceding broader contract/session
  regression run passed 43 tests.
- Desktop/mobile browser checks: no application errors or API writes. Mobile settled
  layout fits a 390px viewport with no horizontal overflow.
- Synthetic 50-aircraft roster/relationship-view smoke test passed. These were browser
  fixtures only; the actual client fleet remains SCOUT and NET-LEADER.
- Real browser checks discovered two 3D defects missed by mocked interactions:
  unsupported alpha-hex grid color and a drag attachment reset on React updates.
  Both were corrected. The rebuilt real mouse test moved East from 0 to
  0.920493m with North/Above unchanged; Undo restored 6/0/0. The grid is visible;
  browser errors and API writes were empty. Evidence:
  `swarm-design-3d-drag-browser.log` and `swarm-design-3d-drag.png`.
- Optimized production build completed successfully on Hetzner after both fixes.

## Two-aircraft SITL evidence

Executed `tools/validate_swarm_design_apply.py` against isolated GCS port 5038.
Both simulated nodes ran `a1596899`. No real API was used.

1. Both aircraft completed Takeoff and accepted Start Swarm.
2. Initial +6m North formation settled: max horizontal error 0.18m, altitude error 0.20m.
3. Applied an additional +2m East offset during following.
4. Both nodes acknowledged the effective new revision; formation settled to max
   horizontal error 0.10m and altitude error 0.15m.
5. Hold completed on both with typed held-state evidence.
6. Applied another formation while held: 12 observation samples confirmed inactive
   swarm, native Hold and no resumed following.
7. Land completed; both disarmed; original formation restored. Final result: passed.

These are simulation results, not guarantees of real-aircraft tracking or separation.

Evidence directory on the validation host:
`/root/mds-action-hold-20261024.PdRKCW/evidence/`.
Key files: `design-apply/summary.json`, `swarm-design-live-apply.log`,
`swarm-design-tests-final.log`, `swarm-design-backend-final.log`,
`swarm-design-browser-final.log`, `swarm-design-browser-50.log` and screenshots.
Both simulated aircraft logs were archived under `design-apply/drone-1` and `drone-2`.
The two test containers were stopped and removed; the isolated GCS and its temporary
firewall rule were stopped/removed. Production services were left unchanged.

## Remaining release gates

- Merge/sync the candidate into the official and client release branches deliberately;
  deploy GCS before aircraft so the optional effective-revision report is understood.
- Rebuild the distributable SITL image: Hetzner has only approximately 1.4GB free,
  insufficient for a clean image build/export. No replacement artifact was published.
- Grounded hardware version/configuration verification before a subsequent field test.

No PX4 parameters, controller gains, flight limits or Simurgh behavior changed.

## Production UI review deployment

At the user's subsequent request, the validated frontend and matching GCS API
were deployed to the existing production service for visual review. The client
checkout is on local review branch `review/swarm-design-20261024`, commit
`596f94900`; official/client release branches and the aircraft update channel
were not promoted. The retained deployment baseline is `2e1951d66`.

Production verification confirmed exactly SCOUT and NET-LEADER, unchanged fleet,
formation and GCS environment file hashes, no active commands, working revision
and design-status APIs, and actual authenticated Top/3D rendering with zero
browser errors, server errors or attempted writes. Aircraft were offline.

Rollback build and deployment evidence are under
`/root/mds-swarm-design-review-20261024/`. Old fingerprinted static assets were
retained for already-open browser tabs. The temporary read-only verification
credential was revoked after checking.

This is a temporary review deployment, not aircraft/field release approval.
The existing boot Git-sync policy still follows client `main`; rebooting or
running code sync before release integration can revert the review backend.
Do not treat this review branch as the long-term deployment policy. Complete
official/client release integration after UI feedback before a reboot or field test.
