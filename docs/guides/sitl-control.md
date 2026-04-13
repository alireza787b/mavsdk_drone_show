# SITL Control

The dashboard now includes a dedicated `System -> SITL Control` page for
temporary local SITL hosts.

Use it when you want to:

- inspect local SITL Docker images prepared for MDS
- see which `drone-N` containers are running now
- reconcile the local fleet to a target count
- restart a single SITL instance
- remove a single SITL instance
- inspect tracked reconcile/restart/remove operations
- tail recent container logs for one selected instance

## Scope

This page is intentionally a local supervisor, not a generic Docker console.

It does:

- use the canonical `multiple_sitl/create_dockers.sh` launcher
- respect the selected Docker image and basic startup overrides
- track lifecycle operations inside MDS instead of sending operators to shell
- present compact host/image/instance state in the dashboard

It does not do in V1:

- build new Docker images
- provide a browser shell or host terminal
- expose arbitrary Docker operations outside the MDS SITL scope
- replace the documented image build/release workflow

## Operator Workflow

1. Open `System -> SITL Control`.
2. Confirm Docker is available on the host.
3. Confirm the intended image is present.
4. Set `Desired instances`.
5. Optionally open `Advanced` and override:
   - start ID
   - start IP
   - subnet
   - Docker network name
   - Git sync on boot
   - requirements sync on boot
6. Click `Reconcile fleet`.
7. Watch the tracked operation until it reaches `succeeded` or `failed`.
8. Review the `Instances` section and select a container for details.
9. Use `Restart` or `Remove` only on the selected instance.

## Advanced Overrides

The page defaults to normal beginner-safe values:

- image: first detected MDS SITL image or policy default
- target count: current instance count, or `3` when empty
- start ID: `1`
- start IP: `2`
- Docker network: policy default, normally `drone-network`
- Git sync: enabled
- requirements sync: enabled

Advanced fields are folded behind `Advanced` so routine use stays simple.

## API Surface

The page uses these GCS endpoints:

- `GET /api/v1/system/sitl/policy`
- `GET /api/v1/system/sitl/host`
- `GET /api/v1/system/sitl/images`
- `GET /api/v1/system/sitl/instances`
- `GET /api/v1/system/sitl/instances/{instance_name}/logs`
- `POST /api/v1/system/sitl/reconcile`
- `POST /api/v1/system/sitl/instances/{instance_name}/restart`
- `DELETE /api/v1/system/sitl/instances/{instance_name}`
- `GET /api/v1/system/sitl/operations`
- `GET /api/v1/system/sitl/operations/{operation_id}`

These routes are designed to stay MCP- and automation-friendly:

- typed request/response models
- explicit operation tracking
- no shell scraping in the browser
- canonical launcher reuse instead of parallel SITL orchestration logic

## Notes

- Instance inventory is limited to the MDS SITL container naming pattern
  (`drone-N`) and prepared MDS SITL images.
- Restart and remove operate on one selected container at a time.
- Reconcile is the preferred way to converge the whole local fleet.
- Container log tails are best-effort and depend on what Docker captured for the
  selected container.

## Validation

This page was live-validated on a Hetzner SITL host against real Docker
containers:

- fresh reconcile to `3`
- single-instance restart
- single-instance remove
- reconcile back to `3`
- telemetry convergence back to `3/3 ready`

The implementation note for that checkpoint is:

- `docs/plans/2026-04-13-sitl-control-phase1-implementation.md`
