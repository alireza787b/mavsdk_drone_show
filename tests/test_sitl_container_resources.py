"""Docker-only limits are opt-in, quoted and checked before fleet replacement."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "multiple_sitl/container_resources.sh"
KEYS = ["MDS_SITL_DOCKER_MEMORY", "MDS_SITL_DOCKER_MEMORY_SWAP",
        "MDS_SITL_DOCKER_CPUS", "MDS_SITL_DOCKER_PIDS_LIMIT"]


def run_limits(**values):
    env = {key: value for key, value in os.environ.items() if key not in KEYS}
    env.update(values)
    script = f'''set -euo pipefail
source "{HELPER}"
sitl_configure_resource_limits
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "${{DOCKER_RESOURCE_ARGS[@]}}"
'''
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=10)


def test_unconfigured_limits_preserve_stock_docker_defaults():
    result = run_limits()
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_limits_are_separate_docker_arguments_without_shell_evaluation():
    result = run_limits(MDS_SITL_DOCKER_MEMORY="2g", MDS_SITL_DOCKER_MEMORY_SWAP="2g",
                        MDS_SITL_DOCKER_CPUS="1.5", MDS_SITL_DOCKER_PIDS_LIMIT="512")
    assert result.returncode == 0
    assert json.loads(result.stdout) == ["--cpus", "1.5", "--pids-limit", "512",
                                       "--memory", "2g", "--memory-swap", "2g"]


@pytest.mark.parametrize("key,value", [
    ("MDS_SITL_DOCKER_MEMORY", "0"), ("MDS_SITL_DOCKER_MEMORY", "2g --privileged"),
    ("MDS_SITL_DOCKER_CPUS", "0"), ("MDS_SITL_DOCKER_CPUS", "nan"),
    ("MDS_SITL_DOCKER_CPUS", "-1"), ("MDS_SITL_DOCKER_PIDS_LIMIT", "0"),
    ("MDS_SITL_DOCKER_PIDS_LIMIT", "1; true"), ("MDS_SITL_DOCKER_MEMORY_SWAP", "2g"),
])
def test_invalid_limits_fail_without_any_docker_operation(key, value):
    result = run_limits(**{key: value})
    assert result.returncode != 0
    assert "Error:" in result.stderr
    assert not result.stdout


def test_launcher_checks_limits_before_network_or_container_changes():
    source = (ROOT / "multiple_sitl/create_dockers.sh").read_text()
    main = source.split("main() {", 1)[1]
    assert main.index("sitl_configure_resource_limits") < main.index("setup_docker_network")
    assert main.index("sitl_configure_resource_limits") < main.index('create_instance "$i"')
    assert '"${DOCKER_RESOURCE_ARGS[@]}"' in source


def test_image_build_budget_is_separate_from_runtime_budget():
    env = {key: value for key, value in os.environ.items()
           if key not in KEYS and not key.startswith("MDS_SITL_BUILD_")}
    env.update(MDS_SITL_DOCKER_MEMORY="2g", MDS_SITL_BUILD_MEMORY="4g",
               MDS_SITL_BUILD_MEMORY_SWAP="4g", MDS_SITL_BUILD_CPUS="2")
    script = f'''set -euo pipefail
source "{ROOT / 'tools/docker_sitl_image_lib.sh'}"
captured=()
docker() {{ captured=("$@"); }}
docker_sitl_start_build_container owned-build base-image
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "${{captured[@]}}"
'''
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    args = json.loads(result.stdout)
    assert args[:4] == ["run", "--name", "owned-build", "-d"]
    assert args[args.index("--memory") + 1] == "4g"
    assert args[args.index("--memory-swap") + 1] == "4g"
    assert "2g" not in args
