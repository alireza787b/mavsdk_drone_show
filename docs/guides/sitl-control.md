# SITL Control

The dashboard now includes a dedicated `System -> SITL Control` page for
temporary local SITL hosts.

Use it when you want to:

- inspect local SITL Docker images prepared for MDS
- see which `drone-N` containers are running now
- reconcile the local fleet to a target count
- add one new SITL container without pruning the rest of the fleet
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
- present compact image/instance state in the dashboard, while keeping
  secondary sections folded behind explicit operator intent
- use auto-populated image repository/tag selectors for normal operation, with
  a folded manual image-ref override for advanced cases
- expose the same lifecycle through a headless API/CLI path for validators,
  AI agents, and future MCP tools

It does not do in V1:

- build new Docker images
- provide a browser shell or host terminal
- expose arbitrary Docker operations outside the MDS SITL scope
- replace the documented image build/release workflow

## Operator Workflow

1. Open `System -> SITL Control`.
2. Confirm Docker is available on the host.
3. Confirm the intended image repository and tag are present.
4. Set `Desired instances`.
5. Optionally open `Advanced` and override:
   - full image ref
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

For ad hoc fleet growth tests, use `Add next`:

- it creates exactly one new `drone-N`
- it does not prune the rest of the fleet
- the default ID/IP is the next free slot
- `Add one with custom ID/IP` is available for sparse or non-sequential test
  layouts such as `drone-10`

## Advanced Overrides

The page defaults to normal beginner-safe values:

- image repo/tag: first detected MDS SITL image/tag or policy default
- target count: current instance count, or `3` when empty
- start ID: `1`
- start IP: `2`
- Docker network: policy default, normally `drone-network`
- Git sync: enabled
- requirements sync: enabled

Advanced fields are folded behind `Advanced` so routine use stays simple.

## Reconcile Semantics

`Reconcile fleet` is a fresh-range operation:

- requested `drone-N` containers inside the selected range are recreated by the
  canonical launcher
- extra `drone-N` containers outside the requested range are removed afterward
- the result should be treated as the new clean local SITL baseline

## API Surface

The page uses these GCS endpoints:

- `GET /api/v1/system/sitl/policy`
- `GET /api/v1/system/sitl/host`
- `GET /api/v1/system/sitl/images`
- `GET /api/v1/system/sitl/instances`
- `GET /api/v1/system/sitl/instances/{instance_name}/logs`
- `POST /api/v1/system/sitl/instances`
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

## Headless Automation

When GCS is already running, prefer the typed SITL Control API/CLI over raw
`create_dockers.sh` calls:

```bash
python3 tools/sitl_control_client.py policy \
  --base-url http://127.0.0.1:5000
```

```bash
python3 tools/sitl_control_client.py reconcile \
  --base-url http://127.0.0.1:5000 \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3 \
  --mode auto
```

`--mode auto` is the recommended default:

- use the SITL Control API when the live GCS exposes it and Docker is reachable
- fall back to the canonical shell launcher only when the API is unavailable

Use `--mode shell` only for explicit cold-start or legacy-host workflows.

## Notes

- Instance inventory is limited to the MDS SITL container naming pattern
  (`drone-N`) and prepared MDS SITL images.
- Restart and remove operate on one selected container at a time.
- `Add next` and `Add one` create a single new container without pruning the
  existing fleet.
- Reconcile is the preferred way to converge the whole local fleet.
- Container log tails first use Docker logs, then fall back to the container's
  file-backed SITL runtime logs such as `startup_sitl.log` when Docker output
  is empty.
- Restart/remove now keep the page inventory visible and show only instance-
  local pending state instead of dropping the whole page into a blocking
  loading shell.
- Images and operations are intentionally secondary panels; the primary working
  surface is the searchable instance inventory plus the selected-container
  detail pane.

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
