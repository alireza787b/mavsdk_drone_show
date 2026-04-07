## 2026-04-07 Smart Swarm Airborne Gate and Quick Takeoff

### Decision
- Treat Smart Swarm as an airborne-mode mission in the operator UI.
- If the scoped targets include grounded drones with live telemetry, block Smart Swarm dispatch.
- Offer a quick recovery action directly in the readiness card to launch only those grounded drones using the shared Action takeoff altitude.

### Implemented
- Added reusable Smart Swarm launch-readiness analysis in the dashboard utility layer.
- Lifted the Take Off altitude into `CommandSender` so Mission Trigger and Actions share one value.
- Added a Smart Swarm readiness blocker, airborne-count fact, and quick-takeoff CTA in Mission Details.
- Kept the quick-takeoff command on the standard command pipeline with confirmation modal and lifecycle tracking instead of a special-case side channel.

### Validation
- Covered with targeted Jest tests for the readiness utility and Mission Details Smart Swarm gating flow.
