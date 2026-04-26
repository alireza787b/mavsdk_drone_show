# Operator Makefile

The root `Makefile` is a thin command index for common operator, maintainer,
and CI actions. It is not a second configuration system.

Authoritative behavior remains in the underlying scripts:

- `app/linux_dashboard_start.sh` owns GCS startup, mode selection, and restart
  behavior.
- `tools/mds_gcs_init.sh` and `tools/install_gcs.sh` own GCS bootstrap.
- `tools/mds_node_init.sh` and `tools/install_companion.sh` own companion-node
  bootstrap.
- `tools/update_repo_ssh.sh` owns node-side git sync and post-sync runtime
  reconcile.

Use `make` when you want a memorable, repeatable entrypoint. Use the scripts
directly when you need the complete option surface.

## Quick Commands

```bash
make help
make status
make gcs-sitl
make gcs-real
make gcs-prod-sitl
make gcs-prod-real
```

Extra startup flags pass through with `START_FLAGS`:

```bash
make gcs-prod-real START_FLAGS="--skip-deps"
make gcs-sitl START_FLAGS="--rebuild"
```

## Fleet And SITL Operations

The API-backed targets default to `http://localhost:5030`. Override `GCS_API`
when operating against a remote GCS.

```bash
make fleet-git-status
make fleet-sync
make sitl-status
make sitl-reconcile SITL_COUNT=4
make sitl-stop
```

`make fleet-sync` calls the same GCS-managed sync operation used by the
dashboard. It asks eligible drones to run the node-side `UPDATE_CODE` path,
which pulls the configured repo/branch and reconciles changed runtime services.

## Bootstrap And Repair

```bash
make install-gcs ARGS="--help"
make install-companion ARGS="-d 1 -y --mavlink-auto --gcs-ip 100.82.207.49"
make node-init ARGS="-d 1 -y"
make node-resume
make git-access-check
```

The `ARGS` variable is passed directly to the underlying script. Keep secrets in
the documented env/token/key files; do not place private tokens directly in a
shell history or Makefile command.

## Validation

```bash
make lint-shell
make test-python PYTEST_ARGS="-q"
make test-frontend NPM_TEST_ARGS="-- --watchAll=false --runInBand"
make build-frontend
```

Run heavy frontend builds, SITL reconciliation, and container/image work on a
proper GCS/build host such as Hetzner, not on constrained diagnostic machines.

## Design Rule

New `make` targets should wrap an existing canonical script or API operation.
Do not add business logic, config defaults, or secret handling to the Makefile.
