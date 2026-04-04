# 2026-04-04 SITL Release Refresh

## Context

After the API and reusable SITL-platform work closed at `d7fb5cea`, the next
maintenance step was to re-audit the remaining SITL debt, refresh the pinned
public Docker SITL image, and update the download instructions.

The release refresh was run against the promoted `main` checkpoint, not a
mutable runtime-sync branch.

## Debt Audit Result

No hidden SITL-platform debt was found beyond the already tracked deferred
items:

- QuickScout deterministic validator/template
- advanced mixed-mode and fault-injection plans once they are stable enough for
  routine acceptance use

The other entries in `docs/TODO_deferred.md` remain broader product backlog
items, not incomplete SITL-platform migration work.

## Findings

- The previous Hetzner "clean sync" tree was an rsynced git worktree copy with a
  broken `.git` indirection path, so it was not a trustworthy long-term release
  workspace.
- The public `mavsdk-drone-show-sitl:latest` image on Hetzner was still labeled
  from the older debug checkpoint (`d7922c82`), not the promoted SITL-platform
  checkpoint (`d7fb5cea`).
- The existing packaging workflow still required a full intermediate Docker tar
  on disk before compression. That failed on the 8 GB Hetzner VPS during
  packaging with `no space left on device`.

## Changes

- Refreshed the release host from a standalone synced workspace:
  - `/root/mavsdk_drone_show_release_refresh`
- Rebuilt and retagged the SITL image on Hetzner from `main`:
  - `mavsdk-drone-show-sitl:latest`
  - `mavsdk-drone-show-sitl:v5`
  - `mavsdk-drone-show-sitl:d7fb5ce`
- Fixed `tools/package_sitl_image.sh` so compressed packaging streams
  `docker save` directly into `7z` when `--keep-tar` is not requested. This
  removes the multi-GB intermediate tar from the normal release path.
- Cleaned stale Hetzner validation/audit directories to restore safe release
  headroom before packaging.
- Packaged the refreshed release archive successfully:
  - `/root/release_artifacts/mavsdk-drone-show-sitl-image.7z`
- Uploaded the refreshed archive, checksum, and manifest to MEGA and exported a
  new public link.
- Updated `docs/guides/sitl-comprehensive.md` to the new public archive link.

## Result

- Image labels on Hetzner now report:
  - commit: `d7fb5ce`
  - version: `v5`
  - branch: `main`
- Release manifest inside the packaged artifact set reports:
  - `image_repo`: `mavsdk-drone-show-sitl`
  - `version_tag`: `v5`
  - `commit_tag`: `d7fb5ce`
- New public archive link:
  - `https://mega.nz/file/7HBx0KoR#fCMcO33bAA5ZVSc_cMt43eaqxJDwV3lKWN_4tUwz-TA`

## Operational Notes

- The upload had to use the helper's stdin-login fallback because the retained
  MEGAcmd session cache on Hetzner was not reusable.
- Raw MEGA password handling should still be considered sensitive. Rotate the
  account password after this run and prefer a reusable session string or an
  already-authenticated MEGAcmd session for future refreshes.

