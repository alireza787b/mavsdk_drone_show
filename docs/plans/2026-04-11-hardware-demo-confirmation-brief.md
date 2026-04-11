# Hardware Demo Confirmation Brief

Date: 2026-04-11
Status: Final confirmation brief before official bootstrap/workflow implementation
Scope: Final decisions on repo defaults, usernames, NetBird verification, and remaining pre-client gaps

## Verified Now

### Hetzner GCS

Hetzner is now on NetBird and healthy from this host.

Verified:

- hostname: `ubuntu-8gb-hel1-1`
- NetBird FQDN: `ubuntu-8gb-hel1-1.netbird.cloud`
- NetBird IP: `100.82.107.61`
- management: connected
- overlay peer visibility to the CM4: working

### Holybro Companion Node

The reachable hardware companion is also confirmed live over NetBird from this host.

Verified:

- hostname: `px4-cm4-01`
- FQDN: `px4-cm4-01.netbird.cloud`
- NetBird IP: `100.82.72.33`
- SSH via current admin user works from this host
- OS: Debian 13 on aarch64

So the network path required for the next real-hardware phase is ready.

## Final Answers

### 1. Should bootstrap auto-edit `src/params.py` in the customer repo and commit it?

No. I do not recommend that as part of normal bootstrap.

Reason:

- `/etc/mds/gcs.env` and `/etc/mds/local.env` are the intended runtime source of truth
- bootstraps should configure the host, not silently rewrite repo defaults
- auto-editing tracked repo defaults from installer logic is surprising, harder to audit, and especially wrong for read-only node workflows
- it creates confusion about whether the source of truth is the repo or the host

So the correct policy is:

- **do not auto-edit `src/params.py` during bootstrap**
- **do warn if repo defaults drift from the selected runtime repo/branch**
- **do clean the stale comments/defaults in official MDS so the warning itself becomes less noisy**

If customers later want their private repo defaults cosmetically aligned, that should be a separate deliberate maintenance step, not an implicit side effect of provisioning.

### 2. Does the customer need to pre-edit repo info anywhere before first bootstrap?

No, not in code.

They only need to prepare:

1. private repo exists
2. correct branch exists
3. desired code is present in that branch
4. deploy key authorization is possible

They should not need to:

- edit `src/params.py` to point at the repo
- edit old network fields in code
- keep parallel bootstrap methods

### 3. Is the hardware username required to be `droneshow`?

For the current official node runtime stack: **yes, effectively**.

The codebase still hardcodes `droneshow` in too many places for me to honestly claim arbitrary-user support today. It is not just the wrapper creating a user. Hard dependencies still exist in:

- node init common paths
- service files
- sudoers/polkit snippets
- recovery/update helpers
- LED and wifi manager service tooling
- multiple docs and automation examples

So the correct current answer is:

- the **login/admin user on the device does not need to be `droneshow`**
- but the **MDS runtime user on the device should still be `droneshow`** today

That means the Holybro CM4 being reachable as `arnaud-paris` is fine. The official bootstrap can still create and use `droneshow` as the MDS runtime/service user.

### 4. Should we make hardware runtime user fully configurable now?

Not before the client demo path unless we deliberately take that as a broader refactor.

My recommendation:

- for this closeout, standardize and enforce `droneshow` on hardware
- make the bootstrap explicitly check and explain that policy
- leave “arbitrary runtime user” as a later cleanup/refactor, because the current codebase is not yet clean enough for that claim

This is the safer professional decision.

### 5. Is GCS tied to a fixed username?

No, not in the same way.

GCS is materially more flexible:

- the installer uses `SUDO_USER` / invoking user home
- the install dir defaults under that user’s home
- dashboard startup scripts are already more user-aware

So for GCS:

- root is fine for provisioning
- the long-lived runtime does **not** need a hardcoded `droneshow` identity
- I still recommend using a normal admin user instead of treating `root` home as the long-term application home

### 6. What should the docs say about usernames?

They should say:

- hardware runtime user: `droneshow` is currently required by the official node runtime stack
- device login user: may be different
- GCS install user: can be the invoking admin user; not hardcoded to `droneshow`

That is the honest and accurate documentation state today.

## Repo / Env / Params Source Of Truth

Final doctrine:

- repo + branch at runtime come from:
  - GCS: `/etc/mds/gcs.env`
  - node: `/etc/mds/local.env`
  - SITL: exported env or pinned image
- `src/params.py` is fallback only
- bootstrap should not rewrite tracked repo defaults implicitly

What should still be cleaned in official MDS:

- stale `config_url`
- stale `swarm_url`
- misleading `offline_config` comments
- stale docs that still imply routine `params.py` editing

## NetBird / Network Doctrine

The correct abstraction is:

- local/static network
- overlay VPN
- manual advanced routing

NetBird is the current overlay implementation, not the permanent product abstraction.

The bootstrap should therefore evolve toward:

- generic network mode selection
- provider-specific implementation detail under that

For this phase:

- NetBird support stays
- local/static stays first-class
- future Tailscale/WireGuard-style support should be possible without rethinking the whole architecture

## Remaining Must-Fix Items Before Private Client Deployment

### Required

1. fix wrapper auth ordering for first-time private bootstrap
2. make existing NetBird registration reuse/rebind explicit
3. make post-enrollment node sync explicit and safe
4. clean stale `params.py` local-vs-online ambiguity
5. align docs to the real source-of-truth model
6. make node bootstrap/runtime user policy explicit: `droneshow` required today

### Strongly recommended

7. unify operator guidance into one hardware onboarding playbook
8. run official real-hardware validation on:
   - fresh Hetzner GCS path
   - reachable Holybro companion
   - candidate announce
   - accept / replace / recover
   - node sync after enrollment

## Recommendation On What We Do Next

If you confirm this brief, the next implementation phase should be:

1. official wrapper private-bootstrap fix
2. NetBird reuse/rebind handling
3. post-enrollment node-sync workflow
4. stale docs / `params.py` cleanup
5. revalidation on Hetzner + Holybro real hardware

Only after that should we create and exercise the customer-specific private repo/demo workflow.

## Final Recommendation

The project is ready to move forward, but not yet ready to skip straight into the customer demo fork.

The remaining work is focused and clear. The main architectural decisions are already correct.

The only important behavioral stance I am locking here is:

- **do not auto-edit `src/params.py` during bootstrap**
- **do standardize node runtime on `droneshow` for now**
- **do keep GCS user-flexible**
- **do keep network mode provider-neutral**
