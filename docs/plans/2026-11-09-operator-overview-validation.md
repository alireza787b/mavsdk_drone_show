# Operator Overview validation

Scope: the [approved Overview and shared-shell redesign](2026-11-09-operator-dashboard-redesign.md).
Evidence date: 2026-11-09. Status: source prerelease validated for operator review,
tag `overview-20261109-rc1`; not hardware flight clearance or a new immutable
SITL image release.

## Accepted behavior

- Board, List and Map use one current fleet model. Inspection never retargets.
- Initial All and restored explicit selections, including empty, are independent
  of filters, link loss, arrivals and navigation.
- Overview owns general Takeoff, Hold, Land and immediate native Return.
  Mission workspaces own mission launch and Managed Return.
- Each uncertain generic request retains its action/target identity. Receipt
  lookup never replays it or blocks a different recovery action.
- Missing measurements remain unknown. Aircraft conditions, command progress
  and local Seen acknowledgements are separate concepts.
- Custom CSV has its own operation path; Drone Show supports explicit targets
  and native When-ready synchronization as well as deliberate scheduled starts.

## Runtime finding and correction

The initial isolated Drone Show launch failed before arming: Python/MAVSDK
preparation took about 5.86 seconds, exceeding the legacy four-second early
start. The executor reached its gate 1.82–2.17 seconds late and correctly rejected
the launch under its unchanged one-second late-start limit.

`src/mission_timing.py` now supplies one configurable preparation lead to GCS,
node commitment and scheduling for the actual synchronized `drone_show.py`
family only: Drone Show, Custom CSV and Hover Test. The default is ten seconds.
Future execution time, wait-before-arming, PX4 checks and late rejection remain
unchanged. Hold, Land, RTL and other executors retain their existing timing.
When-ready launch obtains its synchronized time after the preparation barrier;
an explicit requested time is not silently moved.

## Evidence

- Final frontend regression: 159 suites, 1,134 tests passed, including the
  receipt-scoping integration. The narrow Overview/receipt regression also
  passed all 31 tests.
- Screenshot review found a floating documentation shortcut overlapping Alerts.
  Both now use normal header flow with a 44-pixel guide target; eight App tests
  passed and browser acceptance explicitly checks non-overlap.
- Preparation timing/runtime/environment checks: 378 tests passed.
- Existing Drone Show validator coverage plus its scheduled-fixture correction:
  20 tests passed.
- API/tool/show-workspace checks: 60 tests passed, including the 100-target
  action-readiness contract; isolated HTTP acquisition also returned 100 targets.
- Live three-aircraft SITL: Global auto-correction, Global manual-origin,
  Local scheduled and Custom CSV launches each completed with 3/3 successes.
- Targeted Land completed on one aircraft while the other two continued the
  show; a subsequent Land completed on the remaining two. The original show was
  deliberately superseded, not miscounted as a successful completion.
- The initial served-build matrix passed all 32 combinations of 1/3/20/100
  aircraft, phone/tablet/desktop widths and dark/light themes. Eight additional
  layout cases passed at 360/720/1024/1280 pixels. The 720-pixel case represents
  a narrower effective viewport, not physical-browser zoom certification.
- The final header-layout build repeated all 32 scenarios, eight extra layouts
  and four all-live screenshot scenarios successfully. Map inspection was
  exercised on the three-aircraft desktop fixture; 100-aircraft checks cover
  Board/List, inspection and explicit selection, not crowded-map readability.
- Public agent documentation now includes this operator guide. Its generated
  search index and API candidate inventory are refreshed without enabling any
  new callable tools. The existing capture-preview POST and swarm-config
  WebSocket routes are explicitly represented in the route inventory rather
  than left as stale test debt.
- Documentation/context regression: 49 tests passed. API route/candidate
  inventory: ten tests passed. Environment-reference and generated-index checks
  passed on the validation host.
- The [100-aircraft soak](../assets/operator-overview/evidence/soak.json) passed
  for 1,201 seconds and 40 interaction samples. Selection feedback p95 was
  13.1 ms; retained browser heap grew from 7,552,244 to 9,198,744 bytes, within
  the bounded-heap acceptance limit. No browser errors or command writes occurred.
  The soak exercised the unchanged fleet/selection implementation from
  `8c515cdd`; the separate final browser matrix verifies the header-flow fix.

The [32-case browser matrix](../assets/operator-overview/evidence/browser-matrix.json)
and [eight extra layouts](../assets/operator-overview/evidence/extra-layout.json)
record read-only served-build results. The
[illustrated guide](../assets/operator-overview/overview-operator-guide.png)
uses original-resolution synthetic screenshots.

The [sanitized native matrix](../assets/operator-overview/evidence/drone-show-runtime.json)
contains acceptance/execution counts. The
[startup measurements](../assets/operator-overview/evidence/post-fix-startup-metrics.json)
and [first](../assets/operator-overview/evidence/drone-show-runtime-attempt1.json)
and [second](../assets/operator-overview/evidence/drone-show-runtime-attempt2.json)
failed attempts preserve the preparation finding and correction.

The native runtime used source overlays on the cached stock image. No Docker
commit was used. Browser acceptance uses synthetic aircraft and blocks writes;
it cannot issue real flight commands. Raw command journals contain capability
material and are not public documentation assets.

## Remaining boundaries

- The immutable SITL image rebuild/export/upload remains deferred for storage
  headroom; no new pinned image or distribution checksum is claimed.
- Real aircraft must pull and verify the new source before a future test. No
  hardware command, PX4 parameter, swarm gain or formation change was made here.
- Chromium responsive/touch emulation is not physical Safari/tablet/phone
  acceptance. A representative device/operator check remains required.
- Pre-existing future-trigger forwarding in Swarm Trajectory/QuickScout needs
  its own executor audit. This change deliberately does not increase their
  preparation window or claim to fix that separate timing behavior.
- Broader mission/configuration-page polish and build-tool modernization remain
  the scoped follow-ups in the approved plan, not hidden release promises.
