# Fleet Sync And Secrets

This guide is the source of truth for how configuration and credentials should
flow through an MDS fleet.

Use it when you need a clean answer to questions like:

- what should change once for the whole fleet?
- what must stay local on each node?
- how should a new drone inherit fleet defaults?
- how should private repo auth scale to many drones?
- which changes belong in git, env files, or secret files?

It complements:

- [Runtime Config Sources](runtime-config-sources.md)
- [Custom Repo Workflow](custom-repo-workflow.md)
- [Custom SITL Auth Guide](custom-sitl-auth.md)
- [Headless Automation Guide](headless-automation.md)
- [Git Sync System](../features/git-sync.md)

## 1. The Three-State Model

Do not treat all configuration the same.

MDS has three different kinds of state:

### A. Fleet desired state

This is the configuration that should propagate across the fleet.

Examples:

- `config.json` / `config_sitl.json`
- `swarm.json` / `swarm_sitl.json`
- `deployment/defaults.env`
- repo-owned connectivity profiles such as Smart Wi-Fi Manager bundles
- future repo-owned fleet default MAVLink Anywhere profiles

This state is git-tracked.

### B. Applied host runtime state

This is the configuration that a specific host actually runs with.

Examples:

- `/etc/mds/gcs.env`
- `/etc/mds/local.env`
- `/etc/mds/node_identity.json`
- service enablement / rendered systemd configuration

This state is rendered locally from desired state plus host facts and install
choices.

### C. Local secrets

This is credential material that should not be treated as ordinary fleet config.

Examples:

- `MDS_GIT_AUTH_TOKEN_FILE`
- `MDS_GIT_SSH_KEY_FILE`
- write-capable GCS deploy key
- private Wi-Fi password files
- other customer secrets

This state stays local or comes from a separate secure distribution path.

## 2. What Changes Once Versus Per Node

### Change once for the fleet

Use git-tracked desired state for:

- fleet membership intent
- swarm topology
- default repo/branch/channel intent
- default GCS endpoint intent
- default connectivity policy
- default tool/profile references for the fleet

### Change per node

Use host-local runtime or identity for:

- hardware ID / durable identity
- actual node IP facts
- board-specific serial path overrides
- special hardware exceptions
- local secret file paths

### Do not mix them

Bad pattern:

- storing customer-specific repo URL, branch, GCS IP, or node identity in
  `src/params.py`

Good pattern:

- desired state in git
- applied runtime in `/etc/mds/*.env`
- secrets in local secret files

## 3. Current Auth Model

### Public official repo

- GCS, drones, and SITL can use plain HTTPS.
- No secret is required for read-only access.

### Private customer repo

Use the split below:

- GCS:
  - write-capable credential only on the GCS
- drones / real hardware nodes:
  - read-only credential only
- disposable SITL:
  - read-only credential only

Recommended current practical model:

- GCS:
  - SSH write credential or GitHub App-backed automation credential when the GCS
    must publish repo changes
- drones / private SITL:
  - read-only deploy key via `MDS_GIT_SSH_KEY_FILE`, or read-only token file via
    `MDS_GIT_AUTH_TOKEN_FILE`

Do not:

- reuse the GCS write key on every node
- embed raw credentials into repo URLs
- store raw secrets in git

### Recommended private-repo credential matrix

| Runtime | Access | Recommended credential | Notes |
|---------|--------|------------------------|-------|
| Drone / companion node | Read-only | Repository deploy key, read-only | Best current fit for one repo per fleet; private key stays on that node or provisioned image. |
| Private SITL / validation host | Read-only | Token file or read-only deploy key | Use disposable credentials for temporary CI/SITL hosts. |
| GCS publishing host | Write, only if publish-from-GCS is enabled | Separate write-capable deploy key or GitHub App | Do not copy this credential to drones. |
| Multi-repo / enterprise automation | Fine-grained read/write | GitHub App | Preferred long-term model when token lifecycle and repo scoping matter. |

GitHub deploy-key facts to preserve in reviews:

- a deploy key is an SSH key attached to one repository, not a user account;
- deploy keys are read-only by default, but can be granted write access when
  added to a repository;
- a deploy key cannot be reused across multiple repositories;
- write-capable deploy keys can push to the repository and must be treated like
  production write credentials;
- new GitHub organizations may disallow repository deploy-key creation by
  policy, and enterprise policy can prevent org owners from overriding it;
- GitHub recommends GitHub Apps for finer-grained access and lifecycle control.

Primary references:

- GitHub Docs: [Managing deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys)
- GitHub Docs: [Restricting deploy keys in your organization](https://docs.github.com/en/enterprise-cloud@latest/organizations/managing-organization-settings/restricting-deploy-keys-in-your-organization)
- GitHub Changelog: [Repository deploy keys are controlled by enterprise and organization policy](https://github.blog/changelog/2024-10-23-repository-deploy-keys-are-controlled-by-enterprise-and-organization-policy-ga/)

If adding deploy keys is blocked in a customer repository, ask the repository or
organization owner to check **Organization Settings -> Member privileges ->
Deploy keys** and any enterprise repository-management policy. If policy should
stay locked down, use a GitHub App or approved machine-user flow instead of
trying to bypass the restriction.

## 4. How A Fleet Change Should Propagate

### Ordinary config change

Example:

- change fleet topology
- change swarm defaults
- change default branch/channel
- change Wi-Fi profile intent
- change future MAVLink profile intent

Flow:

1. operator or automation updates git-tracked desired state
2. GCS commits/pushes if the runtime is write-capable
3. nodes pull the configured branch
4. nodes apply the updated desired state
5. dashboard and logs report the applied state

This should not require reconnecting to every node manually.

### New node bootstrap

Flow:

1. bootstrap node identity and local secret(s)
2. point the node at the fleet repo/branch
3. render `/etc/mds/local.env`
4. start services
5. announce/enroll with the GCS
6. inherit current fleet desired state

### Secret rotation

This is different from ordinary config rollout.

Flow:

1. replace the secret contents at the same local path when possible
2. rerun the relevant sync/start path
3. verify health and repo access

This is a controlled secret event, not a normal config save.

## 5. What The GCS Should And Should Not Do

### The GCS should

- own fleet desired state
- own write-capable git operations when enabled
- expose health / sync status / rollout visibility
- serve as the operational control point
- surface node-local sidecar posture without becoming the direct owner of each
  sidecar config file or secret

### The GCS should not

- be treated as the source from which drones directly “read” secrets
- silently copy raw repo tokens into the repo
- require per-node shell edits for ordinary fleet config changes

## 6. Smart Wi-Fi Manager And MAVLink Anywhere

These tools follow the same pattern:

- fleet default profile intent should be repo-owned
- host-specific override should stay local
- secrets should stay separate

### Smart Wi-Fi Manager

Target model:

- repo owns fleet default connectivity profile intent
- nodes apply that profile unless they have a justified local override
- Fleet Ops can import a repo-owned profile into
  `deployment/connectivity/smart-wifi-manager/profile.json`
- node sync/reconcile rolls that profile out to managed real nodes
- Fleet Ops and node runtime status compare hashes without exposing profile
  secrets

### MAVLink Anywhere

Target model:

- repo owns fleet default routing/profile intent
- nodes may override input source details when hardware requires it
- local serial device path and board-specific differences remain host-local

### Operator visibility

The GCS should make node-local runtime posture visible without pretending those
tools are centrally edited there.

Current expectation:

- fleet git status shows whether node-local git auth is healthy
- fleet git status shows compact node-local `mavlink-anywhere` and Smart Wi-Fi
  posture
- fleet git status shows the latest node-local post-sync runtime summary so an
  operator can see whether service updates, coordinator restart scheduling, and
  sidecar reconcile steps actually applied
- fleet git status now also exposes whether systemd unit reload succeeded,
  whether unit changes were rolled back safely, and which unit actions are
  deferred until the next invocation / restart / boot
- node git-sync reports recovery action, retained backup path, and disk free
  space posture so operators can distinguish normal sync drift from recovered
  repository corruption
- sidecar status uses the same normalized vocabulary for Smart Wi-Fi Manager
  and MAVLink Anywhere: `tool`, `mode`, `service_state`, installed ref,
  desired/applied/local hashes, `drift_state`, compact `profile_summary`, and
  `last_apply_result`
- direct dashboard links appear only when the node-side listen address is
  actually reachable from the operator network
- loopback-only dashboards are shown as local-only instead of rendering broken
  links

## 7. Current Support Versus Planned Support

### Supported now

- repo/branch defaults through `deployment/defaults.env`
- host-local runtime env in `/etc/mds/gcs.env` and `/etc/mds/local.env`
- read-only node/private SITL auth through `MDS_GIT_AUTH_TOKEN_FILE`
- write-capable GCS git flow
- optional connectivity-backend foundation in runtime/bootstrap code
- Fleet Ops Smart Wi-Fi profile import/status using secret-safe hashes
- node sync/reconcile applies repo-owned Smart Wi-Fi profiles to managed real nodes
  with merge as the default import behavior, preserving field-added local SSIDs
  unless an operator explicitly uses replace/reset semantics
- node git-sync uses a scoped lock, avoids broad deletion of Git lock files,
  avoids normal `git gc` field repair, and can recover corrupted worktrees by
  retaining a timestamped backup and recloning cleanly

### Planned next

- richer fleet-default versus node-override UI
- future repo-owned MAVLink Anywhere default profile support
- encrypted fleet Wi-Fi secret material instead of plaintext private profiles
- long-term GitHub App support for better large-fleet credential management

Do not assume planned support is already operator-ready unless the relevant
guide says it is live.

## 8. AI / MCP / Automation Rules

If you are writing automation or using an AI agent:

- prefer `--report-json` and `--announce-report-json`
- do not scrape colored shell output if structured JSON is available
- treat `/etc/mds/gcs.env` and `/etc/mds/local.env` as the canonical rendered
  runtime files
- preserve secret file paths when rotating credentials
- do not overwrite host-local secrets just because desired state changed
- do not use `src/params.py` as the operational customization point

## 9. Service User Reality

Current runtime examples and deployed scripts use the `droneshow` service user
on nodes.

That is the current supported operational truth. Human field operators may SSH
with a human/admin account, but MDS files and services are owned by the service
account.

Normal access pattern:

```bash
ssh <human-user>@<node-ip>
sudo -u droneshow -H bash -lc 'cd ~/mavsdk_drone_show && git status --short --branch'
```

Do not set or share a password for `droneshow` as a normal operator workflow.
Keep it as a locked or key-only service account. If direct service-user SSH is
required for a controlled deployment, add a named authorized key and document
who owns it; do not create a common fleet password.

Service-user parameterization is part of the broader runtime cleanup program,
but operators and automation should still treat `droneshow` as the active node
runtime user today unless the deployment explicitly says otherwise.

## 10. Quick Decision Table

| If you need to change... | Put it here |
|--------------------------|-------------|
| fleet topology / swarm defaults | `config*.json`, `swarm*.json` |
| default repo / branch / fleet channel | `deployment/defaults.env` |
| actual host runtime selection | `/etc/mds/gcs.env`, `/etc/mds/local.env` |
| node identity | `/etc/mds/node_identity.json`, `MDS_HW_ID` |
| private repo read credential | local secret file + `MDS_GIT_SSH_KEY_FILE` or `MDS_GIT_AUTH_TOKEN_FILE` |
| GCS write credential | local secret file / SSH key on the GCS only |
| fleet default Wi-Fi profile | `deployment/connectivity/smart-wifi-manager/profile.json` in the fleet repo |
| board-specific MAVLink input path | host-local runtime override |

## 11. Bottom Line

The scalable model is:

- fleet desired state in git
- node runtime rendered locally
- secrets handled separately
- fleet defaults with explicit node overrides
- normal config rollout separated from secret rotation

If a workflow requires SSHing into every node for ordinary fleet config changes,
the design is not finished yet and should be tightened before calling it the
steady-state model.
