# SDK 4 and operator-maintenance release acceptance

This record distinguishes source, a rebuilt simulator artifact and later
grounded hardware maintenance. It is not a real-aircraft flight clearance.

## Runtime identity

- Baked public source: `0bc368cb247f55333ff246a83bd19bf783369bdb`.
- Image ID: `sha256:e4add93667d86796a32820f9a8b390fdb6e9095d3ae0ea57e59ddf3416ec5343`.
- Image Python: CPython 3.12.16, installed separately from the OS interpreter.
- Flight SDK: installed `mavsdk-grpc==4.0.5`, matching native server v4.0.5,
  `grpcio==1.75.1`, `protobuf==6.33.5`; recorder parser `pyulog==1.3.0`.
- PX4 source remains `3a868390`; missing inherited submodule gitlinks remain
  explicitly unavailable, not verified. No firmware tuning or admission policy
  change is part of this dependency release.

Verified publication and final artifact acceptance are recorded below. Later
host validation/docs and companion provisioning updates are distinguished from
the pinned flight-runtime identity; real-aircraft verification remains separate.

## Proven fixes

The embedded companion API now explicitly uses standard asyncio. In a
three-aircraft SDK-candidate rehearsal, a recovery controller hung before exec
inside gRPC's child-fork handler after Uvicorn selected a process-wide uvloop
policy. The correction preserves passed evidence FDs, process groups and the
existing native admission contract; it does not enable experimental gRPC fork
support. The focused API/setup/postflight batch passed 261 tests, and a real
active-gRPC regression completed 30 subprocess launches with FD/session checks.
The subsequent three-aircraft mixed-mode rehearsal completed landing/disarm on
all aircraft without diagnostic intervention.

The integrated validator also no longer requests an unsupported airborne start
of the ground-only Swarm Trajectory mission. It checks explicit native rejection,
zero dispatch/ACK/execution and unchanged live-follow roles, then exercises the
supported leader Hold/Precision Move workflow. Missing evidence is not zero.
Terminal rejections fail promptly with their actual preparation reason.

Completed recovery normalizes residual Offboard only after fresh connected,
disarmed, ON_GROUND evidence and verifies Hold before a later launch. Uncertain
or airborne state and manual modes are not normalized. Unattended breaking SDK
updates refuse incompatible environments before server/package/service mutation;
source-only updates are not an atomic aircraft migration.

## Operator workspace evidence

The [Logs workspace checkpoint](2026-11-12-logs-workspace-modernization.md)
records its backend, actual-browser and recorder evidence. Mission Config treats
unseen heartbeat placeholders as unknown, not slot mismatches. Picker fields no
longer stretch radio/checkbox controls or clip aircraft/source labels.

[PX4 Parameters](../guides/px4-parameter-operator.md) adds List / Groups and
Show all without changing apply targets or native write authority. Both layouts
remain virtualized, including phones. The final 27-test frontend batch and six
actual-built viewport/theme cases passed. At 1,440 / 900 / 390 pixels, text
bounds, keyboard inspection, failure/stale states and frozen apply targets were
checked; the 2,049-row fixture kept at most 26 / 25 / 12 mounted rows. Final
screenshots use synthetic aircraft and native viewport captures. Earlier clipped
phone screenshots were rejected, not accepted as successful evidence.

## Artifact gates

The final image passed `pip check`; its actual 82-distribution installed graph
had zero known advisory findings and zero skipped distributions at the recorded
audit time. Final filesystem/metadata credential gates reported no findings.
These checks do not establish OS/native-library security certification.

The exact baked image is tested without Git, dependency or host-startup overlays.
Private deployments reuse that image with a separately verified read-only Git
overlay, not a second customer-baked distribution image. Configuration and
mission assets remain deployment-owned.

| Gate | Accepted evidence |
|---|---|
| Exact baked image, two aircraft | Configuration; Drone Show global auto/manual, scheduled local and custom CSV; action/override controls; live Smart Swarm; ground-start Swarm Trajectory; QuickScout; parameter write/readback with restoration; ULog retrieval/parse/cleanup |
| Live formation changes | Ground/airborne capture, height choices, Body translation/yaw, offset changes, Geographic/Body switching and 4.5-second leader outage/recovery without saved-role promotion |
| Recovery and relaunch | Show override/landing, three ready native probe epochs, then coordinated takeoff without resetting the aircraft |
| Coordinated cancellation | Cancellation before release and after an arming report, with final grounded/disarmed cleanup |
| Same image, three-aircraft read-only customization | Pair with third-aircraft standby, saved Body triangle, three-aircraft capture/translation/yaw/Managed Return, landing and original pair-default restoration |

The Swarm Trajectory gate proves execution/cleanup, not precision tracking: its
recorded tolerances are 18 m horizontal / 8 m vertical. The dedicated live
formation/capture gates use 0.8 m / 0.6 m tolerances. Simulator errors do not
predict field GNSS accuracy, communication quality or suspended-load safety.

The original failed scenario attempt and successful affected-stage rerun are
both retained; the accepted matrix is composite evidence, not a relabelled
successful exit for the failed wrapper.

The v6 archive was uploaded into a new MEGA version folder, downloaded again,
checked with SHA-256 and `7z t`, and streamed into `docker load`. The loaded
image ID matched the identity above and its SDK provider check passed. The
previous accepted remote archive remains available for rollback.

- Archive size: 1,368,083,067 bytes.
- SHA-256: `ed66ea06ca31db6ae1e15ea7e46b4f3e0997de1aaf9ddd9018e76daf61ec3c0c`.
- [Verified public archive](https://mega.nz/file/eHBAGSAI#QJvpeEXvbvifpAhTMDs5rKPhRMu2bKzAbW1dgIbmHVk).

The later companion-only setup update pins Smart Wi-Fi Manager v2.1.14. Its
published static binary passed ten isolated browser-login/CSRF/machine-token/
loopback-proxy HTTP cases against fake files, without real Wi-Fi changes.
The MDS bootstrap/runtime-settings/reconcile batch passed 156 tests, including
source-tag versus installed-dashboard drift and failed-repair handling. Login
credentials stay with the sidecar; no remote-write bypass is enabled. These
companion provisioning changes and host validation/docs follow-ups do not
replace the pinned simulator's flight-runtime baseline.

A sequential harness attempt first tried to start a Drone Show after the live
formation test had landed away from the show's assigned launch slots. The
existing geometry check correctly rejected that setup (12.25 m deviation versus
the 7.5 m threshold); that failed attempt is retained. The isolated relaunch
regression therefore starts from a fresh correctly placed baseline. There is
no simulator reset between its show recovery and subsequent coordinated takeoff.
Neither placement admission nor native readiness is relaxed to pass the test.

The host-only Smart Swarm validator was subsequently aligned with the normal
native Start review (`92710efb`, 40 focused tests passed). Previously it sent a
raw Start immediately after a Takeoff receipt and discarded a 409's detail.
The updated tool waits read-only for the reviewed cluster's native admission,
keeps the layout fixed, retains structured rejections and never replays a POST.
This host-tool/documentation follow-up does not change the image's aircraft
runtime; its baked source remains the explicit `0bc368cb` identity above.

## Rollout and remaining boundaries

Use the [SDK maintenance procedure](../guides/mavsdk-updates.md): retain the
previous source/environment/server tuple, stage a supported environment, stop
only the grounded deployment, activate the matching tuple and verify as its
actual service user. Validate current transport, transmitted MAVLink identity,
two fresh telemetry epochs and explicit readback. A successful process envelope
or service-active flag is insufficient. Hardware maintenance must not arm an
aircraft or overwrite flight parameters merely to prove connectivity.

The optional Simurgh semantic-planner regression documented in the
[dependency checkpoint](2026-11-12-flight-dependency-maintenance.md) remains
separately deferred and excluded from this operator-runtime release scope.
It must not be hidden by new language aliases or relaxed flight guards.

Aircraft actuator faults, repair/inspection, independent flight readiness and
network/RTK field conditions remain separate from software/image acceptance.
