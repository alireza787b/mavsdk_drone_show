# Resource Asset Layout

`resources/` contains repo-managed reference assets, not live fleet state.

Use these conventions:

- `resources/px4_param_profiles/`
  - approved PX4 parameter profiles for the `PX4 Parameters` dashboard page
  - typed JSON, repo-reviewed, reusable for batch apply and export
- `resources/common_params.csv`
  - legacy CSV bundle for the older `APPLY_COMMON_PARAMS` action path
  - kept only for backward operational compatibility until the action pipeline is fully retired or migrated
- `resources/config_*.json` and `resources/swarm_*.json`
  - sample or preset fleet layouts for setup/reference workflows
  - these are not the active runtime config files

Live runtime fleet state stays outside this folder:

- root `config.json` / `swarm.json`
  - active real-mode fleet configuration
- root `config_sitl.json` / `swarm_sitl.json`
  - active SITL fleet configuration
- `shapes/` and `shapes_sitl/`
  - mission geometry, processed trajectories, plots, and show data
- `runtime_data/`
  - durable runtime state such as QuickScout mission storage

Do not add new operator-facing profiles or presets in ad hoc folders. If a new repo-backed asset class is introduced, give it a named subdirectory under `resources/` and document it here.
