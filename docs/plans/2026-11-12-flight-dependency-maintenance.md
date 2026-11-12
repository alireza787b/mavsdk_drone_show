# Flight dependency maintenance checkpoint

This checkpoint separates a bounded recorder-parser update from a flight SDK
migration. A newer version number is not by itself a validated fleet baseline.

## Applied to the Logs source release

Pin `pyulog==1.3.0` identically in the GCS and companion requirement sets. The
previous open range could leave existing installations on 1.2.3 while fresh
installations selected something newer. Validate the pinned parser against the
existing synthetic ULog/HTTP/summary tests and an actual disposable SITL file.
Bootstrap and requirements-fingerprint sync consume those same files; no second
installer-specific parser version is introduced.

The [maintainer's PyPI release](https://pypi.org/project/pyulog/1.3.0/) includes
portable Python wheels and release provenance. No raw aircraft records are sent
to the package registry or another external service.

## MAVSDK migration: required follow-up, not silently applied

The [official migration guide](https://mavsdk.mavlink.io/v4/en/python/migration.html)
documents a package/API boundary: `mavsdk` v4 is the native binding; the maintained
gRPC wrapper is now `mavsdk-grpc`, imported as `mavsdk_grpc`. Unboundedly upgrading
the old package name is not a drop-in maintenance action.

Current repository evidence:

- Both requirement files pin `mavsdk==3.10.2`.
- The tracked root `mavsdk/` generated package shadows the installed distribution
  when running from the checkout. A pip package version alone does not identify
  the Python code actually loaded.
- Native-server provisioning has a `v3.15.0` fallback and an explicit/latest
  discovery path. Binary provenance, Python module origin and generated protocol
  compatibility therefore need auditing together, not separate version bumps.

Next isolated maintenance slice:

1. Inventory actual module origins, gRPC/protobuf requirements and hash-bound
   server provenance on every supported architecture. Preserve the current known
   working baseline and rollback artifacts.
2. Select a maintained gRPC client/server pair from official releases; do not
   switch the flight stack to the different native Python API accidentally.
3. Remove the vendored shadow only after all imports, plugins and supported
   platforms are covered. Keep one authoritative version/provisioning contract
   across node/GCS requirements, bootstrap, Docker and diagnostics.
4. In an isolated environment validate discovery/reconnect, arm/disarm, takeoff,
   Offboard follow/role transitions, Hold/Land/RTL, parameter typing, ULog
   list/summary/download/erase and command-result semantics. Then rebuild and
   package the SITL image; source-overlay checks are not a pinned-image release.
5. Promote deliberately to the private deployment, verify grounded companions
   and retain rollback. Do not silently replace aircraft SDK/server binaries
   during an operator session.

Broader Python/frontend updates follow the same rule: dependency/advisory review,
isolated resolver checks, supported-platform wheels, regression gates and one
coherent installation contract. This checkpoint does not claim those complete.
