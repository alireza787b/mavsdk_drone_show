# 2026-04-02 SITL Release Refresh

## Release Source

- branch: `main-candidate`
- commit: `4cfbae9`
- repo: `https://github.com/alireza787b/mavsdk_drone_show.git`

## Hetzner Release Host

- host: `203.0.113.10`
- runtime repo: `/root/mavsdk_drone_show_main_candidate_runtime_https`
- release output dir: `/root/sitl_release_2026-04-02`

## Build / Package Result

Executed:

```bash
bash tools/release_sitl_image.sh \
  --base-image mavsdk-drone-show-sitl:latest \
  --image-repo mavsdk-drone-show-sitl \
  --version-tag v5 \
  --repo-url https://github.com/alireza787b/mavsdk_drone_show.git \
  --branch main-candidate \
  --package \
  --output-dir /root/sitl_release_2026-04-02
```

Resulting image tags:

- `mavsdk-drone-show-sitl:v5`
- `mavsdk-drone-show-sitl:latest`
- `mavsdk-drone-show-sitl:4cfbae9`

Packaged artifacts:

- `mavsdk-drone-show-sitl-image.7z`
- `mavsdk-drone-show-sitl-image.7z.sha256`
- `mavsdk-drone-show-sitl-image.manifest.json`

Archive size at publish time:

- `1.2G` (`mavsdk-drone-show-sitl-image.7z`)

Manifest summary:

- `image_repo`: `mavsdk-drone-show-sitl`
- `version_tag`: `v5`
- `commit_tag`: `4cfbae9`

## MEGA Publish

Remote target:

- `/Root/mavsdk-drone-show-sitl`

Published archive link:

- `https://mega.nz/file/ub5XxKpJ#9seRFZ2HObSmOMtcPFx8X7ZwZJtybYwryMmtqmfU-3o`

Helper workflow:

- `tools/publish_sitl_release_to_mega.sh`
- supports existing MEGA session reuse
- supports session-string login
- supports raw stdin credential fallback only as a last resort

## Documentation Updated

- `docs/guides/sitl-comprehensive.md`
- `docs/guides/sitl-custom-release-workflow.md`

## Important Security Note

During this publish run, the raw credential fallback path was used because no preexisting MEGA session was available. The helper itself did not write credentials into repo files or docs, but the non-session login attempt echoed credential input into the automation transcript on the host path used for this run.

Recommended action:

1. rotate the MEGA password used for this publish
2. use MEGAcmd session reuse or a session string for future AI-assisted uploads
3. avoid raw password login in future automated runs unless absolutely necessary

## Next Stable-Checkpoint Steps

1. push the final docs/helper/release-link state to `main-candidate`
2. verify the final repo + docs + artifact checkpoint
3. merge the approved checkpoint to `main`
4. create the release/tag from that merged stable state
