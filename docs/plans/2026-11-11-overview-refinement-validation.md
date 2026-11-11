# Overview refinement · validation record

## Changed

- Available is the default heartbeat-based view and the first-use target set.
  The GCS publishes a 10-second stale cue and canonical 60-second retention
  window, both configurable. This does not change flight/command admission.
- Saved target sets, including empty ones, retain their exact identities.
  Filtering, inspection, group display and reconnects never retarget a command.
  The selected count opens the complete selected set, including hidden aircraft.
- Compact state glyphs replace decorative airframe silhouettes. Cards include
  callsign, hardware/slot IDs, named flight mode, measured GNSS/satellites,
  battery, altitude/datum, mission, heartbeat age and fresh reported Wi-Fi percent.
  Unknown data stays unknown; heartbeat presence is not proof of current FC data.
- Never-observed roster entries no longer create loss-of-link alarms. Losing
  an observed aircraft still does, independently of the current display filter.
- Optional cluster grouping appears for multiple multi-aircraft formations.
  Display grouping and explicit group target selection remain separate controls.
- Bulk and single-aircraft More use the same flat, responsive native side panel.
  Targets are frozen when opened. Move stays in its dedicated current-airborne
  flow; primary controls are not duplicated in More.
- New general-command reviews explicitly acknowledge unavailable targets or
  create a reduced-target review. They do not promise deferred delivery/retries.
  Uncertain receipts remain immutable, lookup-only, and cannot be retargeted.
  REAL motor tests retain independent physical acknowledgments.

## Evidence

All tests, production builds and browser checks ran on the designated remote
validation host, not the editing workstation.

- Full frontend regression: **163 suites / 1,225 tests passed**.
- Final changed-model/card/review/Overview regression: **77 tests passed** after
  the last compact-label and never-observed-roster changes.
- Display-policy, canonical presence, core routes and environment registry:
  **54 tests passed**. The generated environment reference is refreshed.
- Documentation index and OpenAPI candidate generators: **15 tests passed**.
  Refreshed indexes do not enable new Simurgh/MCP tools or change their policy.
- Optimized production builds completed. No new dependency was required.
- [Final browser matrix](../assets/operator-overview/evidence/refinement-20261111.json):
  **14 scenarios passed**, using dark/light themes at 390, 768, 820, 1024 and
  1440 pixels, plus one- and 100-aircraft desktop cases. The 100-aircraft cases
  check Board/List and optional cluster grouping without altering selection.
- Desktop/phone interactions verify named modes, stale/offline transitions,
  hidden selected targets, exact-aircraft More, replacement rather than stacked
  dialogs, unavailable acknowledgment and reduced-target review. No browser
  errors, horizontal page/panel overflow or command writes occurred.
- After deployment, two further desktop/phone scenarios passed against the
  actually served bundle with synthetic API fixtures. A separate authenticated
  read-only API smoke confirmed REAL mode, no restart pending and the published
  display policy. Its short-lived credential was revoked and rejection verified.

The [updated illustrated guide](../assets/operator-overview/overview-operator-guide.png)
uses original-resolution synthetic aircraft screenshots. Send it as a file to
avoid messaging-app photo compression.

## Boundaries

### Silhouette-centered follow-up

The initial text-led card layout above was superseded by an aircraft-centered
layout: battery/altitude left, GNSS/link age right, concise state/mode below.
Normal voltage, idle-mission prose and repeated Details wording move out of the
card. The schematic is a front-profile illustration, not measured heading or
rotor/motor status. Distinct fixed badges show initialization, link freshness or
loss, ground readiness and severity-prioritized condition counts. Clicking a
condition badge opens the existing identity-scoped inspector; it does not clear
or acknowledge a condition. Lost evidence takes priority over an old boot/ready
report, and never implies landing or disarm.

- Seven focused frontend suites / **149 tests passed** for the final follow-up.
- [Fourteen browser cases](../assets/operator-overview/evidence/aircraft-cards-20261111.json)
  revalidated dark/light desktop/tablet/phone layouts, 1–100 cards, aligned
  readouts, selection and scoped actions against the final built source.
- [Two state-gallery cases](../assets/operator-overview/evidence/aircraft-annunciators-20261111.json)
  verified readiness, initialization, stale/link-lost evidence and alert-badge
  clicks into the full reasons. Seven gallery aircraft are synthetic examples,
  not changes to the configured fleet.
- [Two deployed-bundle cases](../assets/operator-overview/evidence/deployed-aircraft-cards-20261111.json)
  passed for two-aircraft desktop/phone fixtures against the actually served
  page. Native read-only API smoke retained REAL mode and the existing fleet;
  its temporary credential was revoked. No command writes or browser errors.

The earlier full regression numbers remain evidence for the preceding scope;
they are not presented as a repeated full-suite run for this visual follow-up.

### Unchanged operational scope

This is a GCS presentation/command-review refinement, not a new aircraft
controller or flight release. No PX4 parameter, swarm gain, formation, network
profile or aircraft command changed. No hardware or flight clearance is claimed.
The existing immutable SITL-image rebuild remains a separate deferred item;
these checks do not claim to update that distribution artifact.

Chromium responsive emulation does not replace physical Safari/touch-device or
field-operator acceptance. Dense map-marker decluttering and broader mission
page polish remain separate follow-ups. The independently preserved flight
incident evidence/identity investigation is not resolved by these UI changes.
