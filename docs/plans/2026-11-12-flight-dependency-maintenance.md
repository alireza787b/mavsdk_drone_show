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

## Maintained MAVSDK source migration

The [official migration guide](https://mavsdk.mavlink.io/v4/en/python/migration.html)
documents a package/API boundary: `mavsdk` v4 is the native binding; the maintained
gRPC wrapper is now `mavsdk-grpc`, imported as `mavsdk_grpc`. Unboundedly upgrading
the old package name is not a drop-in maintenance action.

Baseline findings:

- Both requirement files previously pinned `mavsdk==3.10.2`.
- The tracked root `mavsdk/` generated package shadows the installed distribution
  when running from the checkout. A pip package version alone does not identify
  the Python code actually loaded.
- Native-server provisioning has a `v3.15.0` fallback and an explicit/latest
  discovery path. Binary provenance, Python module origin and generated protocol
  compatibility therefore need auditing together, not separate version bumps.

The source migration now uses installed `mavsdk-grpc==4.0.5`, matching server
v4.0.5, grpcio 1.75.1 and protobuf 6.33.5. The vendored package is retired.
`config/mavsdk-runtime.json` owns the pair, architecture hashes and platform
matrix. See [the maintenance guide](../guides/mavsdk-updates.md) for exact
installation, validation and rollback boundaries.

Implementation and release gates:

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

## Dependency and image acceptance boundary

Compatible dependency updates include the FastAPI/Starlette lifecycle migration,
multipart/network/security fixes and removal of unused Flask dependencies. The
resolved isolated environment passed `pip check` and an installed-distribution
advisory audit with no known findings or skipped distributions. An advisory
result is time-bound evidence, not a guarantee of vulnerability-free software.

The old image's system Python 3.10 is outside the reviewed SDK matrix. Image
preparation now builds checksum-pinned CPython 3.12.16 under a separate versioned
prefix; it does not replace `/usr/bin/python3`. Existing PX4/Gazebo/OS-major and
aircraft tuning remain unchanged. PX4 binary/source identity is recorded, but
missing inherited submodule provenance is explicitly unavailable.

Source tests and stock-image credential scans do not prove the replacement image.
Managed-Python compilation, actual-image dependency/credential checks, mission
and recorder acceptance, packaging and distribution verification remain required
before image promotion. Preserve the known-working public image and main-branch
bootstrap until the replacement is accepted; use a fixed candidate release branch
for preparation. Hardware maintenance/flight clearance is a separate later gate.

## Source regression evidence and separate debt

The isolated updated provider passed the 569-test SDK/mission/bootstrap gate,
234 API/ULog tests and final 87 manifest/image/registry/generated-contract tests.
A broader 4,018-case discovery run initially reported 3,985 passed, 32 failed and
one skipped. Follow-up isolated failures caused by inherited supervisor settings,
stale generated artifacts and a stale capacity assertion; it also exposed missing
`HOME` handling in GCS bootstrap. That setup path now uses the existing identity
resolver, with 122 bootstrap checks passing under a supervisor without `HOME`.
An additional 34 environment/default-policy checks passed after fixture isolation.

One independently reproduced, pre-existing optional Simurgh planner failure stays
separate: the generated prompt `show Read trajectory mission workspace status now`
selects SAR argument discovery instead of the trajectory-workspace read tool.
The same failure occurs with archived baseline code. Do not add spelling/scenario
aliases or alter flight admission to make that test green. Keep its regression
visible for a separately scoped semantic-planner correction; any scoped release
gate excluding it must report that exclusion explicitly. This optional assistant
issue does not establish a defect in the operator's mission controls.
