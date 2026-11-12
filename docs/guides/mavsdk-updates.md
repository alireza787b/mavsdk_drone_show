# MAVSDK client/server updates

MDS uses the maintained **gRPC** wrapper, `mavsdk-grpc==4.0.5`, imported as
`mavsdk_grpc`, with **mavsdk_server v4.0.5**. This is not the new native Python
`mavsdk` v4 API. Do not replace one package with the other or restore the retired
vendored `mavsdk/` tree. See the [official migration guide](https://mavsdk.mavlink.io/v4/en/python/migration.html).

`config/mavsdk-runtime.json` is the compatibility/artifact contract. Both
requirements files must match its Python pins; the focused contract test enforces
this. `grpcio==1.75.1` and `protobuf==6.33.5` are deliberate: the 4.0.5 wheel's
declared gRPC minimum is lower than the minimum actually required by its generated
Python code. Protobuf 6.33.5 also includes the upstream
[CVE-2026-0994 fix](https://github.com/advisories/GHSA-7gcm-g887-7qv7);
the generated-code minimum 6.32.1 is not the chosen security baseline.
A successful pip resolver is not an import test.

The server digests are the published SHA256 values on the
[v4.0.5 release assets](https://github.com/mavlink/MAVSDK/releases/tag/v4.0.5).
The wrapper's [server-version pin](https://github.com/mavlink/MAVSDK-Python/blob/4.0.5/MAVSDK_SERVER_VERSION)
is v4.0.5. Never fabricate a digest or infer the installed version from a requested
tag, file name, or successful `--help` alone.

## Operator update and rollback boundary

Perform upgrades as grounded maintenance. First stop mission/controller/API
processes using MAVSDK, using the deployment's existing service workflow. The
helper refuses a changed server or incompatible Python upgrade while a
`mavsdk_server` process belongs to the selected deployment; neighboring isolated
fleets do not block its maintenance check. It does not terminate a server, revoke
a motion lease, or take over a borrowed server. A source pull alone is not an
atomic fleet upgrade.
Do not run an unattended SDK-pair migration against an operating aircraft.

Unattended companion Git sync checks the pulled source against the selected
Python environment **before** changing the native server, packages, service
templates or network sidecars. An incompatible/missing existing SDK environment
reports `SDK-MAINTENANCE`, restores the previous source commit and retains the
existing runtime. It never tries to repair a breaking SDK migration with in-place
pip. A source-only first bootstrap still lets initial setup create its environment.
`MDS_PYTHON_BIN` takes precedence over `MDS_VENV_PATH`; without either, companion
sync uses the checkout's `venv`. An invalid explicit selection never falls back
to a different interpreter.

For a breaking update, keep the known-working environment intact and create a
replacement at a stable, versioned path. Install and import-check the new source's
requirements there, while grounded and stopped. Then select it using the actual
deployment launcher: GCS supports `MDS_VENV_PATH`/`MDS_PYTHON_BIN`; stock companion
units use `venv/bin/python`, so switch that path to the staged environment only
as an explicit maintenance step. Preserve the prior source/environment/server
tuple for rollback. Do not move an environment and assume its absolute script
shebangs were rewritten. Ordinary compatible requirement updates retain the
existing updater workflow; they are not a transactional package-manager rollback.

From the intended checkout, after selecting the **staged replacement** environment
as `venv` (or substitute its exact Python path below), and retaining the old tuple:

```bash
python3 tools/mavsdk_runtime.py manifest
python3 tools/mavsdk_runtime.py idle
# Use requirements-node.txt on companions; requirements.txt on GCS/SITL.
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements-node.txt
venv/bin/python -m pip check
venv/bin/python tools/mavsdk_runtime.py python-check
bash tools/download_mavsdk_server.sh --install-dir "$PWD"
python3 tools/mavsdk_runtime.py check --install-dir "$PWD"
```

Bootstrap, SITL image preparation/startup, and repository-update helpers use the
same manifest-backed provisioner. No network "latest" resolution or fallback to
an unrelated server version occurs. An already matching pinned server is checked
without download. Before changing a binary, the provisioner downloads a unique
bounded candidate, checks its published digest and Linux ELF architecture, runs
a bounded `--help` probe (no vehicle transport), and atomically renames it into
place. A failed candidate leaves the old executable intact.

`runtime_data/mavsdk/provenance.json` records the manifest digest, Python pins,
actual binary digest, verified server version, and custom-override status. Changed
artifacts and their prior provenance are retained by digest under
`runtime_data/mavsdk/rollback/`. The rollback directory is bounded to 192 MiB;
capacity exhaustion refuses a further change and asks for reviewed archival,
not silent deletion. Do not delete these files to repair an unexplained failure.

Rollback requires the previous **source, Python environment/dependency set, and
server artifact together**, while grounded and stopped. Preserve a previous
working environment/image before updating Python packages; the server backup
does not roll back pip. Select the recorded prior binary by digest, verify its
recorded provenance, restore the matching source/environment using the normal
deployment workflow, then repeat readiness checks before enabling operations.
No automatic rollback or service restart is triggered by the provisioning tool.

Explicit `MDS_MAVSDK_VERSION` / `MDS_MAVSDK_URL` (or `--version` / `--url`) remain
custom compatibility choices. They still require a matching host ELF and bounded
CLI probe, but unknown bytes are `custom_unverified`, with no verified version.
Even a custom URL returning pinned bytes is identified as `custom_pinned_bytes`,
not a default pinned installation. Override URLs are not copied to provenance or
error logs. Do not treat custom operation as validated stock behavior.

## Reusable verification gates

Run tests/builds on the designated validation host, never an aircraft. Use an
isolated checkout and environment, retain bounded command logs, and do not alter
the running deployment's environment during validation.

1. Inspect official migration/API changes and wrapper server pin. Update the
   manifest, real upstream hashes and both requirements together. Check package
   resolver **and actual imports**, including generated protobuf/gRPC code.
2. Check wheel availability separately for Python 3.11, 3.12, 3.13 on x86_64 and
   aarch64. A wrapper wheel is insufficient if grpcio/protobuf has no compatible
   wheel. ARMv7 server assets exist, but this does not establish a supported
   Python companion platform. Do not silently fall back to a source compilation.
3. Run the focused SDK tests, native/API/ULog/PX4 tests, mission safety/startup and
   signal-cleanup tests, and bootstrap/update tests. Verify imports come from the
   selected installed `mavsdk_grpc` distribution, not a checkout or old package.
   Run API/ULog tests against the complete updated dependency set as well; verify
   the drone API lifespan still cancels and awaits ULog/command callback tasks
   on shutdown, including an exceptional application exit.
4. Verify candidate hash/ELF/`--help`, bad hash/architecture/CLI rejection,
   previous-artifact preservation, custom provenance, concurrent pipe draining,
   and correct severity (v4 normal logs use stderr).
5. In isolated SITL, prove real incoming FC telemetry on the configured
   `udpin://0.0.0.0:<port>` endpoint, identity/component IDs, fresh disarm/landing
   evidence, parameter read/review/apply/readback with baseline restoration,
   ULog inventory/download/summary, owned/borrowed server cleanup, reconnect,
   and controller startup/mission regression scenarios. Process exit or stale
   telemetry invalidates a successful-looking result envelope.
6. Use a clean candidate image when the old image cannot run the new dependency
   set. Keep its tags separate from the accepted public image. Verify the same
   workflow against the exact artifact before promotion/packaging; a source
   overlay is not image acceptance. Record source, dependency and server digests.
   This is still not real-hardware flight clearance.
7. Later, on each eligible real companion/FC combination while physically
   grounded, verify service-user imports/settings, incoming transport and MAVLink
   identity, two fresh telemetry epochs, disarm/landed uncertainty handling,
   safe reads and explicitly approved reversible parameter/ULog operations.
   Verify interruption/restart and ownership cleanup without arming. Any flight
   scenarios require a separate approved field procedure and rollback decision.

This migration preserves existing mission policy, role, gains, failsafes, leases,
and fresh-telemetry guards. The earlier v4 heartbeat discovery is not proof of
readiness. Named enums remain named contracts; do not assume numeric values are
unchanged. Concurrent stderr/stdout draining is a compatibility fix, not evidence
of better synchronized flight.

The sequential-mission regression also exercises recovery followed by a new
launch without resetting the simulator. A completed MDS LAND/RTL or show may
leave PX4 disarmed but in residual Offboard, which correctly fails the next
native armability check when its setpoint stream has ended. Postflight completion
now requests Hold once **only** with fresh connected disarmed, ON_GROUND and
OFFBOARD evidence, and verifies the result. It does not precede/gate recovery,
override manual modes, normalize uncertain flight state or bypass preflight.
An unconfirmed mode change stays diagnostic; the next launch still requires
native readiness. This is a lifecycle correction, not a flight-tuning change.

## Metadata and future capabilities

The v4 gRPC wrapper exposes `component_metadata` rather than the retired
`component_information.access_float_params` API. MDS continues live parameter
values and explicitly labels catalog/docs metadata as reference-only; it does
not invent a firmware binding or treat unavailable limits/reboot hints as known.
A vehicle-bound component-metadata adapter, event inspection and MAVLink Direct
are useful follow-on capabilities, each requiring its own typed contract and
validation. They are not implicitly enabled by this dependency update. New
watchdogs, home-setting, tuning, or other flight-control options are not changed.

For upstream details see [v4.0.0](https://github.com/mavlink/MAVSDK/releases/tag/v4.0.0),
[v4.0.5](https://github.com/mavlink/MAVSDK/releases/tag/v4.0.5), and
[API changes](https://mavsdk.mavlink.io/v4/en/cpp/api_changes.html).
