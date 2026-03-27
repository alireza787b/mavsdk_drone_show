#!/bin/bash

docker_sitl_require_cmd() {
    command -v "$1" >/dev/null 2>&1 || {
        printf 'Error: Missing required command: %s\n' "$1" >&2
        exit 1
    }
}

docker_sitl_check_docker() {
    docker_sitl_require_cmd docker
    if ! docker info >/dev/null 2>&1; then
        printf 'Error: Docker daemon is not running or not accessible.\n' >&2
        exit 1
    fi
}

docker_sitl_check_image_exists() {
    local image_ref="$1"
    docker image inspect "$image_ref" >/dev/null 2>&1 || {
        printf 'Error: Docker image not found: %s\n' "$image_ref" >&2
        exit 1
    }
}

docker_sitl_cleanup_container() {
    local container_name="$1"
    if docker ps -a --format '{{.Names}}' | grep -q "^${container_name}$"; then
        docker rm -f "$container_name" >/dev/null 2>&1 || true
    fi
}

docker_sitl_copy_prepare_script() {
    local repo_root="$1"
    local container_name="$2"
    docker cp "$repo_root/tools/sitl_image_prepare.sh" "$container_name:/tmp/mds_sitl_image_prepare.sh"
}

docker_sitl_run_prepare_script() {
    local container_name="$1"
    local repo_url="$2"
    local branch="$3"
    local docker_exec_args=(
        docker exec
        -e "MDS_REPO_URL=$repo_url"
        -e "MDS_BRANCH=$branch"
    )

    if [[ -n "${MDS_MAVSDK_VERSION:-}" ]]; then
        docker_exec_args+=(-e "MDS_MAVSDK_VERSION=${MDS_MAVSDK_VERSION}")
    fi

    if [[ -n "${MDS_MAVSDK_URL:-}" ]]; then
        docker_exec_args+=(-e "MDS_MAVSDK_URL=${MDS_MAVSDK_URL}")
    fi

    if [[ -n "${MDS_SITL_KEEP_ARM_TOOLCHAIN:-}" ]]; then
        docker_exec_args+=(-e "MDS_SITL_KEEP_ARM_TOOLCHAIN=${MDS_SITL_KEEP_ARM_TOOLCHAIN}")
    fi

    if [[ -n "${MDS_GIT_AUTH_TOKEN:-}" ]]; then
        docker_exec_args+=(-e "MDS_GIT_AUTH_TOKEN=${MDS_GIT_AUTH_TOKEN}")
    fi

    if [[ -n "${MDS_GIT_AUTH_USERNAME:-}" ]]; then
        docker_exec_args+=(-e "MDS_GIT_AUTH_USERNAME=${MDS_GIT_AUTH_USERNAME}")
    fi

    docker_exec_args+=("$container_name" bash /tmp/mds_sitl_image_prepare.sh)
    "${docker_exec_args[@]}"
}

docker_sitl_flatten_container() {
    local container_name="$1"
    local base_image="$2"
    local target_image="$3"
    shift 3

    local change_args=()
    local env_line=""
    local workdir=""
    local user=""
    local entrypoint_json=""
    local cmd_json=""

    while IFS= read -r env_line; do
        [ -n "$env_line" ] && change_args+=(--change "ENV $env_line")
    done < <(docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$base_image")

    workdir=$(docker image inspect --format '{{.Config.WorkingDir}}' "$base_image")
    if [ -n "$workdir" ] && [ "$workdir" != "<no value>" ]; then
        change_args+=(--change "WORKDIR $workdir")
    fi

    user=$(docker image inspect --format '{{.Config.User}}' "$base_image")
    if [ -n "$user" ] && [ "$user" != "<no value>" ]; then
        change_args+=(--change "USER $user")
    fi

    entrypoint_json=$(docker image inspect --format '{{json .Config.Entrypoint}}' "$base_image")
    if [ -n "$entrypoint_json" ] && [ "$entrypoint_json" != "null" ]; then
        change_args+=(--change "ENTRYPOINT $entrypoint_json")
    fi

    cmd_json=$(docker image inspect --format '{{json .Config.Cmd}}' "$base_image")
    if [ -n "$cmd_json" ] && [ "$cmd_json" != "null" ]; then
        change_args+=(--change "CMD $cmd_json")
    fi

    if command -v python3 >/dev/null 2>&1; then
        while IFS= read -r config_change; do
            [ -n "$config_change" ] && change_args+=(--change "$config_change")
        done < <(python3 - "$base_image" <<'PY'
import json
import subprocess
import sys

image = sys.argv[1]
cfg = json.loads(subprocess.check_output(["docker", "image", "inspect", image], text=True))[0].get("Config") or {}


def dq(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


for key, value in sorted((cfg.get("Labels") or {}).items()):
    print(f"LABEL {dq(key)}={dq(value)}")

for port in sorted((cfg.get("ExposedPorts") or {}).keys()):
    print(f"EXPOSE {port}")

for volume in sorted((cfg.get("Volumes") or {}).keys()):
    print(f"VOLUME [{dq(volume)}]")

stopsignal = cfg.get("StopSignal")
if stopsignal:
    print(f"STOPSIGNAL {stopsignal}")

healthcheck = cfg.get("Healthcheck") or {}
health_test = healthcheck.get("Test") or []
if health_test:
    if health_test == ["NONE"]:
        print("HEALTHCHECK NONE")
    else:
        options = []
        for key, flag in (
            ("Interval", "--interval"),
            ("Timeout", "--timeout"),
            ("StartPeriod", "--start-period"),
            ("Retries", "--retries"),
        ):
            value = healthcheck.get(key)
            if value:
                suffix = "ns" if key != "Retries" else ""
                options.append(f"{flag}={value}{suffix}")
        option_prefix = f"{' '.join(options)} " if options else ""

        if health_test[0] == "CMD":
            print(f"HEALTHCHECK {option_prefix}CMD {json.dumps(health_test[1:])}")
        elif health_test[0] == "CMD-SHELL" and len(health_test) > 1:
            print(f"HEALTHCHECK {option_prefix}CMD-SHELL {dq(health_test[1])}")

for trigger in cfg.get("OnBuild") or []:
    print(f"ONBUILD {trigger}")
PY
)
    fi

    while (($# > 0)); do
        change_args+=(--change "$1")
        shift
    done

    docker export "$container_name" | docker import "${change_args[@]}" - "$target_image" >/dev/null
}
