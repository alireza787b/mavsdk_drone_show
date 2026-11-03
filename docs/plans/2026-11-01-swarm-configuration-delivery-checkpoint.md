# Formation delivery and moving handover checkpoint

Continuation: the [November 3 validation report](2026-11-03-formation-delivery-validation.md)
records accepted two-aircraft configuration-delivery rehearsals and the deferred
image rebuild. The moving-handover work below remains required; transport
acceptance is not acceptance of that separate capability. The original slice's
pre-validation status below is historical.

## Accepted design

Use recoverable latest-state delivery for formation configuration, independent
of the direct leader-motion stream. Moving handover is a separate tracked
operation: continuous following, with a pilot or an existing mission owning the
new leader. Do not invent automatic leader cruising or claim network atomicity.

## Implemented source slice

- Authenticated `/ws/swarm-config`: initial/current full revisioned snapshots,
  bounded latest-only queues, 15-second idle heartbeat, slow-client send deadline.
- Canonical atomic formation saves notify watchers before optional Git work;
  one reader per GCS worker also catches external replacements every second.
- Node subscription reuses a session, validates revisions, coalesces snapshots,
  reconnects with bounded jitter and reconciles conditionally through HTTP.
  Healthy HTTP interval is 30 seconds; disconnected fallback retains 2 seconds
  plus request time. No control task waits on network delivery.
- Startup snapshot/admission, local recovery overrides and existing applied
  acknowledgements remain intact. A response begun before a newer push cannot
  overwrite that push. Empty/invalid snapshots never clear the active plan.
- New follower reference fields install before follower tasks start. Premature
  desired-assignment publication was removed. Existing transition-to-leader
  behavior still requests Hold: continuous handover is NOT implemented here.
- PATCH accepts revision/receipt metadata without persisting it in assignments.
  Legacy PATCH remains compatible; comprehensive active-transaction guards are
  part of the handover slice, not proof supplied by this compatibility addition.

## Required continuation — do not mark the whole plan complete

1. Add a typed, durable formation-change operation to existing command tracking,
   rather than putting handover directives in a coalescing config stream.
2. Separate desired/pending topology from effective assignments during the
   operation. Active PUT/PATCH must use the same operation/ownership/conflict
   checks; external file updates must not bypass active handover authority.
3. Stage all affected aircraft with fresh revision/authority acknowledgements.
   Unsupported nodes or unidentified successor movement owners reject before
   control changes. Preparation expires after 10 seconds without movement.
4. Implement an explicit successor motion-owner transfer. The existing
   `transition_to_leader_mode` cannot simply lose its Hold call: follower motion
   ownership and Offboard cleanup must be positively handed over to the intended
   pilot/mission, with native mode evidence. This ownership adapter is not yet
   available for continuous moving handover.
5. Activate the new root, then descendants parent-first. Install each complete
   leader/offset/frame reference serially; preserve controller continuity and
   current speed/acceleration/jerk limits. A new parent must be confirmed before
   its children switch. Reconcile partial progress, never blindly roll it back
   or resume after a GCS restart. RTL/Land/Stop/pilot override always win.
6. Add one compact operator handover review/status integrated with existing
   Apply and observed installation. Preserve separate repository publishing.
7. Run two- and three-node PX4 SITL with offset/frame changes, moving ownership
   transfers, lost acknowledgements, network partitions, restart and takeover.
   Source tests alone do not satisfy this acceptance gate.

## Validation / deployment boundary

All tests run on the remote validation host; none run on the resource-limited
editing VPS. Transport, conditional reads, invalid snapshots, save failures,
legacy fallback, reconnect, stale replies, effective references and existing
swarm-control regression tests have automated coverage. Live PX4 SITL and a new
pinned image are still required. No production service or aircraft has been
updated by this slice. Do not merge it into an automatically deployed main branch
or advertise continuous handover as available before acceptance.

Validation so far: 271 tests passed on Python 3.12 on the remote host; the
existing stock SITL image imported the new transport modules successfully under
Python 3.10.12 / aiohttp 3.13.2 in a network-disabled disposable container. This
was an import/compatibility check, not a flight or control-loop simulation.

The earlier native armability/SDK missing-telemetry issue is independent and
remains open. Do not loosen checks, substitute stale telemetry or use a reboot
as evidence that it is fixed. Keep normal fixed-leader flight clearance separate
from configuration transport and handover acceptance.

Runtime filesystem changes will require the documented clean SITL image release
workflow after acceptance. No new dependencies, security switch, mission type,
motion gains or PX4 parameters are introduced by this source slice.
