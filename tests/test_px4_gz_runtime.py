"""Prepared, noninteractive launch preserves installed model/world semantics."""
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def resolve(tmp_path, target, models=("gz_x500", "gz_x500_depth"), worlds=("windy", "moving_platform")):
    build = tmp_path / "build/px4_sitl_default"
    airframes = build / "etc/init.d-posix/airframes"
    airframes.mkdir(parents=True)
    (build / "bin").mkdir()
    (build / "rootfs").mkdir()
    (build / "rootfs/gz_env.sh").touch()
    (build / "bin/px4").touch()
    (build / "bin/px4").chmod(0o700)
    for index, model in enumerate(models):
        (airframes / f"{4001+index}_{model}").touch()
    world_dir = tmp_path / "Tools/simulation/gz/worlds"
    world_dir.mkdir(parents=True)
    for world in worlds:
        (world_dir / f"{world}.sdf").touch()
    script = f'''set -euo pipefail
source "{ROOT / 'multiple_sitl/px4_gz_runtime.sh'}"
SIMULATION_ENV_VARS=(HEADLESS=1 GZ_PARTITION=owned-lab)
configure_px4_gz_runtime "$1" "$2"
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$SIMULATION_WORKING_DIR" "${{SIMULATION_COMMAND[@]}}" "${{SIMULATION_ENV_VARS[@]}}"
'''
    return subprocess.run(["bash", "-c", script, "owned-test", str(tmp_path), target],
                          capture_output=True, text=True, timeout=10)


@pytest.mark.parametrize("target,model,world", [
    ("gz_x500", "gz_x500", None),
    ("gz_x500_depth", "gz_x500_depth", None),
    ("gz_x500_windy", "gz_x500", "windy"),
    ("gz_x500_depth_moving_platform", "gz_x500_depth", "moving_platform"),
])
def test_launches_installed_model_and_world_without_shell_or_build(tmp_path, target, model, world):
    result = resolve(tmp_path, target)
    assert result.returncode == 0, result.stderr
    args = json.loads(result.stdout)
    assert args[:3] == [str(tmp_path / "build/px4_sitl_default/rootfs"),
                       str(tmp_path / "build/px4_sitl_default/bin/px4"), "-d"]
    assert f"PX4_SIM_MODEL={model}" in args
    assert "HEADLESS=1" in args and "GZ_PARTITION=owned-lab" in args
    assert ([arg for arg in args if arg.startswith("PX4_GZ_WORLD=")] ==
            ([f"PX4_GZ_WORLD={world}"] if world else []))


@pytest.mark.parametrize("target", ["gz_unknown", "gz_x500_unknown_world", "gz_x500_../../escape", "--help"])
def test_unknown_or_unsafe_target_is_not_silently_substituted(tmp_path, target):
    result = resolve(tmp_path, target)
    assert result.returncode != 0 and not result.stdout


def test_image_startup_uses_resolved_working_directory():
    source = (ROOT / "multiple_sitl/startup_sitl.sh").read_text()
    assert 'configure_px4_gz_runtime "$PX4_DIR" "$PX4_GZ_TARGET"' in source
    assert 'cd "$SIMULATION_WORKING_DIR"' in source
    assert 'SIMULATION_COMMAND=(make px4_sitl' not in source


def test_missing_prepared_runtime_fails_before_launch(tmp_path):
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; configure_px4_gz_runtime "$2" gz_x500',
         "owned-test", str(ROOT / "multiple_sitl/px4_gz_runtime.sh"), str(tmp_path)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    assert "rebuild the SITL image" in result.stderr
