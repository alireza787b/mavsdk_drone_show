# Explicit recipients and selected Smart Swarm Start

## Accepted behavior

Overview card bodies inspect. Their separate blue checkboxes edit the same To
state as the shared chooser, without dispatch. Display filters and green
readiness indicators remain independent. A reviewed action freezes its scope.

Smart Swarm owns its own To snapshot. One cluster starts fully selected without
another setup step. With multiple clusters, a deliberate formation choice
initializes that cluster only. Polling, reconnects, new aircraft and disappearing
members never widen a custom selection. Empty/missing targets remain explicit.

Takeoff, Start and individual Other actions use To. Hold all and Return all
explicitly recover the whole displayed cluster; Return all opens Managed Return.
Deselecting an aircraft changes future commands, not running participation.
Flight controls precede the bounded status roster; large summaries stay compact.

## Native contract

Selected Start infers the saved upstream chain as read-only references, not
extra recipients. Existing native airborne, freshness and recovery checks apply.
Active reference follow links must match the saved plan. References are checked
before dispatch and again at the required-role barrier, with monotonic validity;
after engagement, the aircraft-local link/recovery policy remains authoritative.
No role promotion, navigation thresholds, offsets or control gains change.

Empty reference lists are omitted on the wire for older full-cluster nodes.
Reference-based Start requires advertised companion support. Uncertain submissions
retain their original identity and recover by lookup, not automatic replay.
Operate uses latest journal ownership per aircraft, so an old leader session
cannot hide a newer follower retry. Fresh disarm cannot leave an aircraft stuck
in historical Unconfirmed status; missing telemetry cannot establish disarm.

## Validation evidence

- 200 backend tests cover contract partitioning, admission, source follow-link
  mismatch, callback capability, barrier expiry and submission behavior.
- 173 UI tests cover shared card selection, frozen reviews, empty/missing
  choices, single/100-aircraft defaults, cluster changes and follower retry.
- 16 documentation/OpenAPI candidate generator checks pass. Generated candidates
  remain non-callable; no Simurgh flight capability or policy is enabled.
- Served-build Smart Swarm: 32 intercepted-browser cases, across single,
  three, 100 and four-cluster/100-aircraft fixtures; 390/768/900/1440 widths,
  dark/light. The fixture records exact target-only submission; no real commands.
- Three-aircraft PX4/Gazebo rehearsal: full Start, selected follower Hold/retry,
  unchanged unselected leader/follower command identities and fresh reports,
  grounded-reference rejection in native review, final Land/disarm cleanup.

The native rehearsal used a recorded source-sync overlay on the accepted SDK4
image. It validates source behavior, not a newly baked/published image. Public
image rebuild/packaging remains a separate resource-gated release task; the
previous pinned image is not relabeled as this feature. Real companions need
the compatible source update before reference-based Start. Hardware repair,
propulsion acceptance and real-flight clearance are not established by SITL.

## Operator guide

Use the [illustrated field workflow](../guides/smart-swarm-field-workflow.md).
The normal sequence is unchanged: Takeoff → stable hover → Start Swarm → verify
Following. Use To only for an intentional subset or retry. Hold all and Return
all remain the cluster-wide recovery controls. Screenshots use synthetic aircraft.
