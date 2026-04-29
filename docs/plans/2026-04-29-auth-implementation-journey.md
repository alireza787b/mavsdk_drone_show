# Optional Auth Implementation Journey

Date: 2026-04-29
Scope: official MDS first, then private client sync

## Approved Direction

- Default auth remains disabled.
- Private client first rollout uses dashboard login only:
  - `MDS_AUTH_ENABLED=true`
  - `MDS_API_AUTH_ENABLED=false`
- Full drone/API token enforcement is optional and staged.
- Roles are `admin`, `operator`, and `viewer`.
- UI must allow normal admin user/token management.
- SSH CLI remains the recovery path if UI auth breaks.
- No client-specific secrets or private deployment data may enter the official repo.

## Slice Log

### Slice 1: Auth Foundation

Status: completed

Goals:

- Add reusable auth config, user store, token store, password hashing, and session signing.
- Keep runtime behavior unchanged while auth is disabled.
- Add tests for hash/store/session/token basics.
- Prepare middleware/routes without breaking existing drone heartbeat/bootstrap.

Review checklist:

- No plaintext password storage.
- No token plaintext storage.
- No auth secrets in git-tracked defaults.
- Config source remains `/etc/mds/gcs.env`.
- Secret state remains `/etc/mds/auth`.
- Drone APIs remain compatible in Mode 1.

Verification:

- `python3 -m pytest tests/test_mds_auth.py -q`
- `python3 -m py_compile src/security/auth.py gcs-server/auth_runtime.py gcs-server/api_routes/auth.py tools/mds_auth_admin.py gcs-server/app_fastapi.py`

### Slice 2: GCS Bootstrap And Recovery

Status: completed

Goals:

- Add explicit `mds_gcs_init.sh` auth flags without changing the default open demo posture.
- Persist auth state in `/etc/mds/gcs.env` alongside the existing runtime source of truth.
- Create the first admin from an interactive hidden prompt or a headless password file.
- Keep the SSH CLI as the recovery path for enable/disable, password reset, token create/revoke, and session rotation.

Implemented:

- `--auth`, `--no-auth`, `--api-auth`, `--no-api-auth`
- `--auth-admin-user`, `--auth-admin-password-file`
- `--auth-session-ttl-hours`, `--auth-secure-cookies`
- Auth config keys written into GCS env:
  - `MDS_AUTH_ENABLED`
  - `MDS_API_AUTH_ENABLED`
  - `MDS_AUTH_USERS_FILE`
  - `MDS_API_TOKENS_FILE`
  - `MDS_AUTH_SESSION_SECRET_FILE`
  - `MDS_AUTH_CSRF_SECRET_FILE`
  - `MDS_AUTH_SESSION_TTL_HOURS`
  - `MDS_AUTH_SECURE_COOKIES`
  - `MDS_AUTH_CSRF_ENABLED`
  - `MDS_AUTH_ALLOWED_CIDRS`
  - `MDS_AUTH_TRUSTED_PROXY_CIDRS`

Verification:

- `bash -n tools/mds_gcs_init.sh tools/mds_gcs_init_lib/gcs_env_config.sh tools/install_gcs.sh`
- `python3 -m pytest tests/test_mds_auth.py tests/test_bootstrap_installers.py::test_configure_gcs_env_persists_private_https_token_file tests/test_bootstrap_installers.py::test_configure_gcs_env_persists_private_ssh_key_file tests/test_bootstrap_installers.py::test_configure_gcs_env_rewrites_stale_ports tests/test_bootstrap_installers.py::test_configure_gcs_env_persists_optional_auth_and_first_admin -q`

### Slice 3: Dashboard Login And Security Admin

Status: completed

Goals:

- Add a minimal login gate only when dashboard auth is enabled.
- Keep the normal dashboard open when auth is disabled or not configured.
- Surface current user, logout, users, and token management without exposing local secret values.
- Keep Runtime Admin concise and GCS-host scoped.

Implemented:

- `AuthProvider` and login gate around the dashboard shell.
- Minimal login page with setup-required SSH recovery guidance.
- Session cookie + CSRF propagation for unsafe dashboard API calls.
- Sidebar signed-in user posture and logout.
- Runtime Admin user/token management for admins.
- Runtime Admin auth guide link through the runtime-status docs payload.
- Preserved existing machine endpoints while `MDS_API_AUTH_ENABLED=false`, including drone origin bootstrap.
- Login page uses design tokens rather than hardcoded visual islands.

Verification:

- `python3 tools/audit_frontend_ui.py --strict`
- `python3 -m pytest tests/test_mds_auth.py tests/test_gcs_management_routes.py -q`
- `python3 -m py_compile src/security/auth.py gcs-server/auth_runtime.py gcs-server/api_routes/auth.py tools/mds_auth_admin.py gcs-server/api_routes/management.py gcs-server/schemas.py gcs-server/app_fastapi.py`

### Slice 4: Docs And Operator Surfaces

Status: completed

Goals:

- Explain default-open demo mode, dashboard-login mode, and full API-auth mode.
- Document bootstrap flags, env ownership, SSH recovery, UI user/token management, and Swagger behavior.
- Keep Makefile as thin wrappers, not a second config system.

Implemented:

- Added `docs/guides/gcs-auth.md`.
- Updated docs index, GCS setup, runtime config sources, headless automation, GCS API docs, and operator Makefile guide.
- Added Makefile shortcuts for auth status, enable/disable dashboard login, user creation, token creation, and token revocation.

Verification:

- `python3 tools/audit_frontend_ui.py --strict`
- `bash -n tools/mds_gcs_init.sh tools/mds_gcs_init_lib/gcs_env_config.sh tools/install_gcs.sh`

### Slice 5: Hetzner Validation

Status: completed

Goals:

- Validate the auth slice on the resource-capable Hetzner host.
- Keep local/Linode light by reusing the private deployment virtualenv and dashboard `node_modules`.
- Fix any release-blocking test/build warnings before commit.

Implemented:

- Synced the official worktree to `/tmp/mds_auth_validate_20260429` on Hetzner.
- Fixed frontend tests to expect credentialed GCS API calls.
- Fixed App tests to mock the auth gate and runtime hook without real network calls.
- Fixed auth/context hook dependency warnings so production build compiles cleanly.
- Removed newly touched client-specific test literals and corrected active runtime fallbacks to prefer `main` over historical `main-candidate`.

Verification:

- Hetzner: `python -m pytest tests/test_mds_auth.py tests/test_gcs_management_routes.py tests/test_bootstrap_installers.py::test_configure_gcs_env_persists_optional_auth_and_first_admin -q`
- Hetzner: `python -m pytest tests/test_mds_auth.py tests/test_gcs_management_routes.py tests/test_bootstrap_installers.py::test_identity_setup_local_env_persists_node_git_auth_file_paths tests/test_bootstrap_installers.py::test_configure_gcs_env_persists_optional_auth_and_first_admin tests/test_bootstrap_installers.py::test_configure_gcs_env_persists_private_https_token_file tests/test_bootstrap_installers.py::test_configure_gcs_env_persists_private_ssh_key_file -q`
- Hetzner: `CI=true npm test -- --watchAll=false --runInBand src/App.test.js src/pages/RuntimeAdminPage.test.js src/services/gcsApiService.test.js src/config/routeDocs.test.js src/components/SidebarMenu.test.js`
- Hetzner: `npm run build`
- Hetzner: `python3 tools/audit_frontend_ui.py --strict`

### Remaining Release Work

- After official push/tag, merge the official changes into the private client repo without copying private data back to public.
- Configure the private GCS with dashboard auth enabled and API auth disabled:
  - admin username: `admin`
  - admin password: supplied during bootstrap/test and never committed
- Restart private GCS in REAL mode after remote validation.
