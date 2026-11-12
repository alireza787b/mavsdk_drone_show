"""SDK upgrades are explicit reviewed pairs, not independent latest downloads."""
import asyncio
import hashlib
import importlib.util
import io
import json
import logging
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from src import mavsdk_runtime as runtime
from src.mavsdk_server_logging import drain_mavsdk_output, native_log_level


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mds_mavsdk_provision", ROOT / "tools/mavsdk_runtime.py")
provisioner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provisioner)


def elf(machine=62, elf_class=2):
    result = bytearray(20)
    result[:4] = b"\x7fELF"
    result[4:6] = bytes([elf_class, 1])
    result[18:20] = machine.to_bytes(2, "little")
    return bytes(result) + b"candidate-content"


@pytest.fixture
def provision_env(monkeypatch):
    manifest = runtime.load_manifest()
    manifest["server"]["assets"]["x86_64"]["sha256"] = hashlib.sha256(elf()).hexdigest()
    monkeypatch.setattr(provisioner, "load_manifest", lambda: manifest)
    monkeypatch.setattr(provisioner, "platform_asset", lambda _manifest: ("x86_64", manifest["server"]["assets"]["x86_64"]))
    monkeypatch.setattr(provisioner, "require_idle", lambda *_: None)
    monkeypatch.setattr(provisioner, "download", lambda _url, target: target.write_bytes(elf()))
    monkeypatch.setattr(provisioner, "verify_help", lambda _path: None)
    return manifest


def test_manifest_is_consistent_with_both_requirement_sets():
    contract = runtime.load_manifest()
    python = contract["python"]
    assert python["distribution"] == "mavsdk-grpc"
    assert python["import"] == "mavsdk_grpc"
    assert contract["server"]["version"] == f"v{python['version']}"
    for filename in ("requirements.txt", "requirements-node.txt"):
        lines = (ROOT / filename).read_text().splitlines()
        for name, version in ((python["distribution"], python["version"]), ("grpcio", python["grpcio"]), ("protobuf", python["protobuf"])):
            assert f"{name}=={version}" in lines
        assert not any(line.startswith("mavsdk==") for line in lines)
    assert not (ROOT / "mavsdk").exists(), "Retired vendored package must not shadow the selected client"


def test_published_asset_digests_and_architectures_are_explicit():
    assets = runtime.load_manifest()["server"]["assets"]
    assert set(assets) == {"x86_64", "aarch64", "armv7l"}
    for asset in assets.values():
        assert len(bytes.fromhex(asset["sha256"])) == 32
        assert "musl" in asset["name"]
        assert asset["elf_machine"] in {62, 183, 40}


def test_armv7_server_asset_does_not_imply_python_platform_eligibility(monkeypatch):
    monkeypatch.setattr(runtime.platform, "machine", lambda: "armv7l")
    with pytest.raises(ValueError, match="server asset alone"):
        runtime.verify_python_platform()


def test_idle_guard_binds_deployment_not_neighboring_fleets(tmp_path):
    deployment = tmp_path / "deployment"
    neighbor = tmp_path / "neighbor"
    process_root = tmp_path / "proc"
    for directory in (deployment, neighbor, process_root):
        directory.mkdir()
    own_binary, other_binary = deployment / "mavsdk_server", neighbor / "mavsdk_server"
    own_binary.write_bytes(b"ours")
    other_binary.write_bytes(b"theirs")
    for pid, executable, cwd in ((101, own_binary, deployment), (102, other_binary, neighbor),
                                  (103, other_binary, deployment)):
        process = process_root / str(pid)
        process.mkdir()
        (process / "exe").symlink_to(executable)
        (process / "cwd").symlink_to(cwd)
    assert sorted(runtime.active_server_pids(deployment, proc_root=process_root)) == [101, 103]


@pytest.mark.parametrize("args,expected", [
    (["udpin://0.0.0.0:14540"], True), (["udp://:14540"], True),
    (["udpin://127.0.0.1:14540"], False), (["udpout://127.0.0.1:14540"], False),
    (["udpin://0.0.0.0:14541"], False),
])
def test_udp_listener_borrowing_requires_exact_endpoint(args, expected):
    assert runtime.matches_udp_listener(args, 14540) is expected


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_invalid_listener_port_rejected(port):
    with pytest.raises(ValueError):
        runtime.udp_listen_url(port)


def test_atomic_activation_preserves_previous_artifact_and_provenance(tmp_path, provision_env):
    destination = tmp_path / "mavsdk_server"
    destination.write_bytes(b"known-working-server")
    old_digest = runtime.sha256_file(destination)
    state = tmp_path / "runtime_data/mavsdk"
    state.mkdir(parents=True)
    (state / "provenance.json").write_text('{"old": true}')
    result = provisioner.provision(destination)
    assert destination.read_bytes() == elf()
    assert result["compatibility"] == "pinned"
    assert result["verified_server_version"] == "v4.0.5"
    assert (state / "rollback" / f"mavsdk_server-{old_digest}").read_bytes() == b"known-working-server"
    assert json.loads((state / "rollback" / f"mavsdk_server-{old_digest}.json").read_text()) == {"old": True}
    assert json.loads((state / "provenance.json").read_text()) == result


@pytest.mark.parametrize("failure", ["download", "hash", "architecture", "help", "active", "capacity", "provenance"])
def test_candidate_failure_never_replaces_known_working_server(tmp_path, provision_env, monkeypatch, failure):
    destination = tmp_path / "mavsdk_server"
    destination.write_bytes(b"known-working-server")
    if failure == "download":
        monkeypatch.setattr(provisioner, "download", lambda *_: (_ for _ in ()).throw(OSError("unavailable")))
    elif failure in {"hash", "architecture"}:
        data = elf(machine=183) if failure == "architecture" else b"wrong-digest"
        monkeypatch.setattr(provisioner, "download", lambda _url, path: path.write_bytes(data))
        if failure == "architecture":
            provision_env["server"]["assets"]["x86_64"]["sha256"] = hashlib.sha256(data).hexdigest()
    elif failure == "help":
        monkeypatch.setattr(provisioner, "verify_help", lambda *_: (_ for _ in ()).throw(ValueError("probe failure")))
    elif failure == "active":
        monkeypatch.setattr(provisioner, "require_idle", lambda *_: (_ for _ in ()).throw(ValueError("active controller")))
    elif failure == "capacity":
        monkeypatch.setattr(provisioner, "MAX_BACKUPS_BYTES", 1)
    elif failure == "provenance":
        monkeypatch.setattr(provisioner, "write_json", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises((ValueError, OSError)):
        provisioner.provision(destination)
    assert destination.read_bytes() == b"known-working-server"
    assert not list(tmp_path.glob(".mavsdk-candidate-*"))


def test_custom_override_is_not_reported_as_pinned_version(tmp_path, provision_env, monkeypatch):
    monkeypatch.setattr(provisioner, "download", lambda _url, path: path.write_bytes(elf() + b"custom"))
    result = provisioner.provision(tmp_path / "mavsdk_server", version="v3.15.0", url="https://example.invalid/custom?secret=private")
    assert result["compatibility"] == "custom_unverified"
    assert result["verified_server_version"] is None
    assert result["requested_version"] == "v3.15.0"
    assert "secret" not in json.dumps(result)
    assert "example.invalid" not in json.dumps(result)


def test_explicit_custom_pinned_bytes_are_labelled_custom(tmp_path, provision_env):
    result = provisioner.provision(tmp_path / "mavsdk_server", url="https://example.invalid/custom")
    assert result["compatibility"] == "custom_pinned_bytes"
    assert result["custom_override"] is True


def test_pinned_existing_binary_does_not_download_or_require_controller_stop(tmp_path, provision_env, monkeypatch):
    destination = tmp_path / "mavsdk_server"
    destination.write_bytes(elf())
    monkeypatch.setattr(provisioner, "download", lambda *_: pytest.fail("unexpected download"))
    monkeypatch.setattr(provisioner, "require_idle", lambda *_: pytest.fail("unchanged artifact must not need idle controller"))
    assert provisioner.provision(destination)["compatibility"] == "pinned"


def test_latest_is_rejected_without_touching_installation(tmp_path):
    result = subprocess.run(["bash", str(ROOT / "tools/download_mavsdk_server.sh"), "--latest", "--install-dir", str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "reviewed Python/server pair" in result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("limit", ["size", "time"])
def test_download_transfer_budget_is_bounded_between_socket_reads(tmp_path, monkeypatch, limit):
    monkeypatch.setattr(provisioner.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(b"candidate"))
    if limit == "size":
        monkeypatch.setattr(provisioner, "MAX_DOWNLOAD_BYTES", 3)
    else:
        clock = iter([0.0, 0.0, 121.0])
        monkeypatch.setattr(provisioner.time, "monotonic", lambda: next(clock))
    with pytest.raises(ValueError, match="bounded size/time"):
        provisioner.download("https://example.invalid/server", tmp_path / "candidate")


def test_symlink_destination_is_not_followed_or_replaced(tmp_path, provision_env):
    owned_elsewhere = tmp_path / "working-elsewhere"
    owned_elsewhere.write_bytes(b"working")
    destination = tmp_path / "mavsdk_server"
    destination.symlink_to(owned_elsewhere)
    with pytest.raises(ValueError, match="symlink"):
        provisioner.provision(destination)
    assert destination.is_symlink()
    assert owned_elsewhere.read_bytes() == b"working"


@pytest.mark.parametrize("line,level", [
    ("[12:00:00|Info ] MAVSDK v4.0.5", logging.INFO),
    ("[12:00:00|Warn ] dropping slow subscriber update", logging.WARNING),
    ("[12:00:00|Error] Connection refused", logging.ERROR),
    ("[12:00:00|Debug] normal traffic", logging.DEBUG),
    ("unstructured diagnostic on stderr", logging.DEBUG),
    ("error while loading shared libraries: missing.so", logging.ERROR),
])
def test_log_level_comes_from_native_severity_not_stderr(line, level):
    assert native_log_level(line) == level


@pytest.mark.asyncio
async def test_both_pipes_are_drained_concurrently_without_stderr_deadlock(caplog):
    process = subprocess.Popen([sys.executable, "-c",
        "import sys; sys.stderr.write('[00:00:00|Info ] ' + 'x'*200000 + '\\n'); sys.stderr.flush(); "
        "sys.stdout.write('[00:00:01|Warn ] stdout warning\\n'); sys.stdout.flush()"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with caplog.at_level(logging.DEBUG, logger="mds-sdk-test"):
            await asyncio.wait_for(drain_mavsdk_output(process, logging.getLogger("mds-sdk-test")), timeout=8)
        assert process.wait(timeout=1) == 0
        assert sorted(record.levelno for record in caplog.records if record.name == "mds-sdk-test") == [logging.INFO, logging.WARNING]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)
        process.stdout.close()
        process.stderr.close()


def test_probe_only_uses_bounded_help(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(runtime.subprocess, "run", lambda args, **kwargs: seen.append((args, kwargs)) or SimpleNamespace(returncode=0))
    runtime.verify_help(tmp_path / "server")
    args, options = seen[0]
    assert args == [str(tmp_path / "server"), "--help"]
    assert options["timeout"] == 5
    assert options["stdin"] == subprocess.DEVNULL


def test_python_dependency_contract_checks_actual_generated_import(monkeypatch):
    expected = {"mavsdk-grpc": "4.0.5", "grpcio": "1.75.1", "protobuf": "6.33.5"}
    monkeypatch.setattr(runtime.importlib.metadata, "version", expected.__getitem__)
    monkeypatch.setattr(runtime.importlib.metadata, "distribution", lambda _name: SimpleNamespace(locate_file=lambda name: Path("/venv") / name))
    monkeypatch.setattr(runtime.importlib, "import_module", lambda name: SimpleNamespace(__file__=f"/venv/{name}/__init__.py"))
    assert runtime.verify_python()["versions"] == expected
    expected["grpcio"] = "1.71.0"
    with pytest.raises(ValueError, match="do not match"):
        runtime.verify_python()


def test_shadowed_sdk_namespace_is_rejected_even_if_metadata_matches(monkeypatch):
    expected = {"mavsdk-grpc": "4.0.5", "grpcio": "1.75.1", "protobuf": "6.33.5"}
    monkeypatch.setattr(runtime.importlib.metadata, "version", expected.__getitem__)
    monkeypatch.setattr(runtime.importlib.metadata, "distribution", lambda _name: SimpleNamespace(locate_file=lambda name: Path("/venv") / name))
    monkeypatch.setattr(runtime.importlib, "import_module", lambda _name: SimpleNamespace(__file__="/checkout/mavsdk_grpc/__init__.py"))
    with pytest.raises(ValueError, match="shadowed"):
        runtime.verify_python()


def test_all_product_sdk_entrypoints_import_the_real_installed_namespace():
    modules = ["actions", "drone_show", "smart_swarm", "swarm_trajectory_mission",
               "quickscout_mission", "src.drone_api_server", "src.drone",
               "src.ulog_service", "src.px4_params.service", "drone_show_src.utils",
               "functions.global_to_local"]
    # Fresh interpreter avoids any other unit test's SDK mocks. Preserve the
    # selected test environment's read-only dependency search paths.
    script = (
        "import sys,json,importlib;sys.path[:]=json.loads(sys.argv[1]);"
        "from src.mavsdk_runtime import verify_python;"
        "result=verify_python();assert '/mavsdk_grpc/' in result['module_file'];"
        "[importlib.import_module(name) for name in json.loads(sys.argv[2])]"
    )
    result = subprocess.run([sys.executable, "-c", script, json.dumps(sys.path), json.dumps(modules)],
                            capture_output=True, text=True, timeout=30, cwd=ROOT)
    assert result.returncode == 0, result.stderr
