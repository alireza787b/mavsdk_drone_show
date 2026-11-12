#!/bin/bash
# Match the installed PX4/Gazebo target metadata, then run the prepared binary
# in daemon mode. No source edits, runtime compilation or interactive PXH loop.
configure_px4_gz_runtime() {
    local px4_dir="$1" target="$2"
    local build="$px4_dir/build/px4_sitl_default"
    local airframes="$build/etc/init.d-posix/airframes"
    local worlds="$px4_dir/Tools/simulation/gz/worlds"
    local selected='' selected_world='' file model world
    if [[ ! "$target" =~ ^gz_[A-Za-z0-9_-]+$ ]]; then
        printf 'Unsupported Gazebo target name.\n' >&2
        return 1
    fi
    if [[ ! -x "$build/bin/px4" || ! -d "$build/rootfs" || ! -f "$build/rootfs/gz_env.sh" ]]; then
        printf 'Prepared PX4/Gazebo runtime is missing; rebuild the SITL image.\n' >&2
        return 1
    fi
    for file in "$airframes"/*_gz_*; do
        [[ -f "$file" ]] || continue
        model="${file##*/}"
        model="${model#*_}"
        # Airframe post scripts are not independent simulator models.
        [[ "$model" != *.post ]] || continue
        if [[ "$target" == "$model" ]]; then
            selected="$model"
            selected_world=''
            break
        elif [[ "$target" == "${model}_"* ]]; then
            world="${target#"${model}_"}"
            if [[ -f "$worlds/$world.sdf" && ${#model} -gt ${#selected} ]]; then
                selected="$model"
                selected_world="$world"
            fi
        fi
    done
    if [[ -z "$selected" ]]; then
        printf 'Gazebo target is not present in this image: %s\n' "$target" >&2
        return 1
    fi
    SIMULATION_ENV_VARS+=("PX4_SIM_MODEL=$selected" "GZ_IP=127.0.0.1")
    [[ -z "$selected_world" ]] || SIMULATION_ENV_VARS+=("PX4_GZ_WORLD=$selected_world")
    SIMULATION_COMMAND=("$build/bin/px4" -d)
    SIMULATION_WORKING_DIR="$build/rootfs"
}
