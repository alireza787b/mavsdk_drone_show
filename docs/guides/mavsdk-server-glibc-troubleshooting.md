# mavsdk_server GLIBC / Binary Mismatch Troubleshooting

Operators occasionally hit dynamic-linker errors when starting a standalone
`mavsdk_server` binary on older Linux hosts. This guide records the symptoms,
root cause, and safe recovery paths used with MAVSDK Drone Show (MDS).

**Related issue:** [alireza787b/mavsdk_drone_show#21](https://github.com/alireza787b/mavsdk_drone_show/issues/21)

## Symptoms

```text
./mavsdk_server: /lib/x86_64-linux-gnu/libc.so.6: version `GLIBC_2.34' not found
./mavsdk_server: /lib/x86_64-linux-gnu/libc.so.6: version `GLIBC_2.33' not found
./mavsdk_server: /lib/x86_64-linux-gnu/libc.so.6: version `GLIBC_2.32' not found
```

Related start-up failures (different root causes, same operator impact):

- `MAVSDK server did not start listening on port … within timeout`
- `mavsdk_server executable not found` during SITL / companion bring-up

Confirm which case you have before changing system libraries.

## Root cause

Prebuilt `mavsdk_server` binaries are linked against a minimum GNU C Library
(glibc) version. If the host libc is older than that baseline (classic example:
Ubuntu 20.04 with a binary built on a newer distro), the dynamic loader refuses
to start the process **before** gRPC comes up.

This is **not** an MDS Python bug and is usually **not** fixed by recompiling
MDS. It is a host / binary pairing problem.

On many Ubuntu companion or desktop installs you may not need a repo-local
`./mavsdk_server` at all — the `mavsdk` Python package already ships a platform
binary under its site-packages tree. Prefer that path when it matches your OS.

## Preferred fixes (safe order)

### 1. Use the binary shipped with the `mavsdk` Python package

When MDS runs inside the project venv / companion env:

```bash
python3 - <<'PY'
import pathlib
import mavsdk
print(pathlib.Path(mavsdk.__file__).resolve().parent / "bin" / "mavsdk_server")
PY
```

Check that file exists and is executable, then check its dynamic deps:

```bash
SERVER="$(python3 - <<'PY'
import pathlib, mavsdk
print(pathlib.Path(mavsdk.__file__).resolve().parent / "bin" / "mavsdk_server")
PY
)"
ls -l "$SERVER"
file "$SERVER"
ldd "$SERVER" | head
```

Point tooling at that path instead of an ad-hoc download when the wheel matches
your architecture and libc.

### 2. Install an official MAVSDK Linux binary that matches the host

If you intentionally need a standalone server:

1. Identify host glibc: `ldd --version`
2. Download the **official** MAVSDK release asset intended for your OS/arch from
   the MAVSDK project releases (not a random third-party mirror).
3. Install to a normal location, for example:

```bash
sudo install -m 0755 mavsdk_server /usr/local/bin/mavsdk_server
mavsdk_server --help || true
```

Avoid dropping a newer-than-host binary into the MDS repo root and expecting it
to run on Ubuntu 20.04-class images.

### 3. Move the workload to a newer base OS or container

Practical options:

- Ubuntu 22.04 / 24.04 (or Debian bookworm+) companions and CI images
- MDS Docker / SITL images that already pin a known-good `mavsdk_server`

For SITL packaging notes (missing server inside an image, auto-download on
startup), see [px4-sitl-preflight-gcs-issue.md](../debug/px4-sitl-preflight-gcs-issue.md).

### 4. Do **not** force-upgrade glibc in place on field companions

Replacing system libc out-of-band is a common way to brick a Pi / NUC image.
Prefer a newer OS image or a binary built for the libc you already have.

## Distinguish “bad binary” from “server never listened”

| Observation | Likely cause | Next step |
|-------------|--------------|-----------|
| Immediate `GLIBC_2.xx not found` | Binary newer than host libc | Sections 1–3 above |
| Process starts, port never opens | Firewall, wrong gRPC port, crash loop, permissions | Check process logs; confirm port args; see init troubleshooting |
| `executable not found` in SITL | Image/repo missing server artifact | SITL startup / image build docs linked above |

## Cross-checks after a fix

```bash
# If using a resolved path:
"$SERVER" --version 2>/dev/null || true
ldd "$SERVER" | rg -i 'not found|glibc' || echo "no missing glibc symbols reported by ldd"
```

Then re-run the MDS action or SITL path that previously failed.

## Related docs

- [MDS Init Troubleshooting](./mds-init-troubleshooting.md) — bootstrap and service bring-up
- [Python Version Compatibility](./python-compatibility.md) — supported CPython lines for companions
- [PX4 SITL preflight / mavsdk_server packaging notes](../debug/px4-sitl-preflight-gcs-issue.md)
- Upstream discussion: [issue #21](https://github.com/alireza787b/mavsdk_drone_show/issues/21)

## Safety

This document only covers **host toolchain / binary selection**. It does not
change geofence, arming, altitude limits, or offboard setpoints. Keep flight
safety checks fail-closed when debugging connectivity.
