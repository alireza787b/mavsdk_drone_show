"""Transport-free image/auth and managed interpreter regression gates."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load_tool("audit_sitl_image")
runtime = load_tool("python_runtime")


def test_runtime_manifest_is_official_versioned_and_checksum_pinned():
    manifest = runtime.load_manifest()
    assert manifest["version"] == "3.12.16"
    assert manifest["source_sha256"] == "b5796915dc45ff745cfb4e990a7e7c93d6f546328a102ce31448d69ebc37575c"
    assert manifest["prefix"] == "/opt/mds-python/3.12.16"


@pytest.mark.parametrize("version", [[3, 10, 12], [3, 14, 0]])
def test_probe_rejects_unsupported_minor(monkeypatch, version):
    monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps({"version": version})))
    with pytest.raises(ValueError, match="SDK-supported"):
        runtime.probe("python3")


def test_select_preserves_supported_venv_base_despite_old_bootstrap(monkeypatch, tmp_path):
    base = str(tmp_path / "managed-python")
    seen = []

    def probe(executable, modules=None):
        seen.append(str(executable))
        return {"version": [3, 12, 16], "base_executable": base}

    monkeypatch.setattr(runtime, "probe", probe)
    monkeypatch.setattr(runtime.sys, "executable", "/usr/bin/python3.10")
    assert runtime.select_python(tmp_path / "venv") == base
    assert seen == [str(tmp_path / "venv/bin/python"), base]


def test_select_falls_back_from_broken_venv_to_managed_interpreter(monkeypatch, tmp_path):
    def probe(executable, modules=None):
        if str(executable).startswith(str(tmp_path)):
            raise OSError("broken")
        return {"version": [3, 12, 16], "base_executable": str(executable)}

    monkeypatch.setattr(runtime, "probe", probe)
    assert runtime.select_python(tmp_path / "venv") == "/opt/mds-python/3.12.16/bin/python3.12"


def test_state_uses_venv_patch_version_not_bootstrap_python(monkeypatch, tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example==1\n")
    monkeypatch.setattr(runtime, "probe", lambda *a, **k: {"version": [3, 12, 16]})
    assert runtime.requirements_state(tmp_path, requirements) == hashlib.sha256(requirements.read_bytes()).hexdigest() + "|python=3.12.16"


def test_check_venv_rejects_unsupported_before_import_health(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    monkeypatch.setattr(runtime, "probe", lambda *a, **k: (_ for _ in ()).throw(ValueError("3.10")))
    assert runtime.check_venv(tmp_path, ["requests"])[0] is False


@pytest.mark.parametrize("name,kind", [("../escape", "file"), ("/escape", "file"), ("source/link", "symlink")])
def test_python_source_extraction_rejects_unsafe_members(tmp_path, name, kind):
    archive = tmp_path / "bad.tar.xz"
    with tarfile.open(archive, "w:xz") as handle:
        member = tarfile.TarInfo(name)
        if kind == "symlink":
            member.type, member.linkname = tarfile.SYMTYPE, "/escape"
        handle.addfile(member)
    with pytest.raises(ValueError, match="path/link"):
        runtime.extract_source(archive, tmp_path / "output")


def test_python_source_checksum_mismatch_rejected(monkeypatch, tmp_path):
    class Response(io.BytesIO):
        def geturl(self):
            return "https://www.python.org/source"

    monkeypatch.setattr(runtime.urllib.request, "urlopen", lambda *a, **k: Response(b"bad archive"))
    with pytest.raises(ValueError, match="SHA256"):
        runtime.download_source("https://www.python.org/source", tmp_path / "source", "0" * 64)


@pytest.mark.parametrize("script", ["tools/sitl_image_prepare.sh", "multiple_sitl/startup_sitl.sh"])
def test_token_auth_never_constructs_credential_url_or_shell_token(script):
    source = (ROOT / script).read_text()
    assert "GIT_AUTH_TOKEN_VALUE" not in source
    assert "https://%s:%s@" not in source
    assert "credential.helper=" in source
    assert "http.extraHeader=" in source
    assert "remote set-url" in source


def test_askpass_reads_file_and_refuses_other_origins(tmp_path):
    token = "ghp_" + "CanarySecret123" * 3
    secret = tmp_path / "token"
    secret.write_text(token + "\n")
    env = {**os.environ, "MDS_GIT_AUTH_TOKEN_FILE": str(secret)}
    helper = ROOT / "tools/git_token_askpass.sh"
    good = subprocess.run([str(helper), "Password for 'https://x-access-token@github.com': "], env=env, capture_output=True, text=True)
    assert good.returncode == 0 and good.stdout == token
    wrong = subprocess.run([str(helper), "Password for 'https://github.com.evil.invalid': "], env=env, capture_output=True, text=True)
    assert wrong.returncode != 0 and token not in wrong.stdout + wrong.stderr


def git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_git_config_canary_rejected_without_content_leak(tmp_path, capsys):
    repo = git_repo(tmp_path)
    token = "ghp_" + "CanarySecret123" * 3
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", f"https://user:{token}@github.com/example/repo.git"], check=True)
    assert audit.git_findings(repo)
    subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin", "https://github.com/example/repo.git"], check=True)
    assert audit.git_findings(repo) == []
    assert token not in capsys.readouterr().out


def test_secret_scan_canaries_and_cleanup(tmp_path):
    secret = tmp_path / "run/secrets/mds_git_auth_token"
    secret.parent.mkdir(parents=True)
    secret.write_text("ghp_" + "CanarySecret123" * 3)
    key = tmp_path / "private-key"
    key.write_text("-----BEGIN " + "OPENSSH PRIVATE KEY-----\nexample\n")
    findings, coverage = audit.filesystem_findings(tmp_path)
    assert {row["kind"] for row in findings} >= {"github-token", "private-key", "staged-secret-path"}
    assert coverage["text_files"] == 2
    assert "CanarySecret" not in json.dumps(findings)
    secret.unlink()
    key.unlink()
    assert audit.filesystem_findings(tmp_path)[0] == []


def test_scan_streams_past_first_chunk_and_fails_closed_on_budget(tmp_path):
    (tmp_path / "long.log").write_text("padding" * 10000 + "github_pat_" + "CanarySecret123" * 3)
    assert audit.filesystem_findings(tmp_path)[0][0]["kind"] == "github-token"
    with pytest.raises(ValueError, match="time budget"):
        audit.filesystem_findings(tmp_path, seconds=-1)


def test_public_fixture_exception_does_not_allow_a_replaced_key(tmp_path):
    key = tmp_path / "future/backports/test/ssl_key.pem"
    key.parent.mkdir(parents=True)
    key.write_text("-----BEGIN " + "PRIVATE KEY-----\nreplaced\n")
    assert audit.filesystem_findings(tmp_path)[0][0]["kind"] == "private-key"


def test_final_image_gate_follows_secret_cleanup():
    source = (ROOT / "tools/docker_sitl_image_lib.sh").read_text().split('if [[ "$exec_status" -eq 0 ]]', 1)[1]
    assert source.index('docker_sitl_cleanup_git_secrets "$container_name"') < source.index("audit_sitl_image.py") < source.index("return 0")


def test_image_prepares_build_only_px4_targets_after_dependency_installation(tmp_path):
    source = (ROOT / "tools/sitl_image_prepare.sh").read_text()
    main = source.rsplit('main() {', 1)[1]
    assert main.index("ensure_python_env") < main.index("prepare_px4_build")
    assert main.index("prepare_px4_build") < main.index("capture_px4_provenance")
    build = tmp_path / "px4/build/px4_sitl_default"
    (build / "bin").mkdir(parents=True)
    (build / "CMakeCache.txt").touch()
    (build / "bin/px4").write_text("fixture")
    (build / "bin/px4").chmod(0o700)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    output = tmp_path / "arguments.json"
    cmake = bindir / "cmake"
    cmake.write_text(f'#!{sys.executable}\nimport json,sys\nopen({str(output)!r},"w").write(json.dumps(sys.argv[1:]))\n')
    cmake.chmod(0o700)
    definitions = source.rsplit('\nmain "$@"', 1)[0]
    env = {**os.environ, "MDS_PX4_DIR": str(tmp_path / "px4"), "PATH": str(bindir) + os.pathsep + os.environ["PATH"]}
    result = subprocess.run(["bash", "-c", definitions + "\nprepare_px4_build"], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text()) == ["--build", str(build), "--target", "px4", "px4_gz_plugins", "--parallel", "2"]


def test_image_config_rejects_secrets_but_not_file_settings():
    assert audit.config_findings({"Env": ["MDS_GIT_AUTH_TOKEN_FILE=/run/secrets/read-token"]}) == []
    assert audit.config_findings({"Env": ["MDS_GIT_AUTH_TOKEN=canary"]})
    assert audit.config_findings({"Labels": {"url": "https://user:canary@github.com/example/repo"}})


def test_image_secret_gate_failure_blocks_flatten_workflow(tmp_path):
    log = tmp_path / "commands.log"
    script = f'''
source "{ROOT / 'tools/docker_sitl_image_lib.sh'}"
docker_sitl_cleanup_git_secrets() {{ printf 'cleanup\\n' >> "{log}"; }}
docker() {{
  if [[ "$*" == *audit_sitl_image.py* ]]; then
    printf 'audit\\n' >> "{log}"
    return 1
  fi
  return 0
}}
docker_sitl_run_prepare_script owned-test https://github.com/example/repo.git main
'''
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 1
    assert log.read_text() == "cleanup\naudit\n"


def test_flatten_handles_missing_optional_config_and_keeps_metadata(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "import.json"
    # Mirrors the actual stock base: no Entrypoint key. Other metadata must
    # survive the optional-field fix rather than being discarded wholesale.
    config = {"Env": ["LANG=C.UTF-8"], "WorkingDir": "/runtime", "Cmd": ["bash"],
              "Labels": {"example": "kept"}, "ExposedPorts": {"7070/tcp": {}},
              "Healthcheck": {"Test": ["CMD", "true"]}}
    fake = bindir / "docker"
    fake.write_text(f'''#!{sys.executable}
import json,re,subprocess,sys
args=sys.argv[1:]
cfg={config!r}
if args[:2]==['image','inspect']:
    if '--format' not in args: print(json.dumps([{{'Config':cfg}}]))
    else:
        fmt=args[args.index('--format')+1]
        if '.Config.' in fmt: raise SystemExit('unsafe missing-key lookup')
        key=re.search(r'index \\.Config "([^"]+)"',fmt).group(1)
        value=cfg.get(key)
        if 'range' in fmt: print('\\n'.join(value or []))
        elif 'json' in fmt: print(json.dumps(value))
        else: print(value or '')
elif args[0]=='exec':
    raise SystemExit(subprocess.call([{sys.executable!r},{str(ROOT / 'tools/audit_sitl_image.py')!r},'config'],stdin=sys.stdin))
elif args[0]=='export': sys.stdout.write('tar-fixture')
elif args[0]=='import':
    sys.stdin.read()
    open({str(log)!r},'w').write(json.dumps(args))
else: raise SystemExit('unexpected Docker operation')
''')
    fake.chmod(0o700)
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"]}
    result = subprocess.run(["bash", "-c", f'set -euo pipefail; source "{ROOT / "tools/docker_sitl_image_lib.sh"}"; docker_sitl_flatten_container owned base candidate'], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    changes = json.loads(log.read_text())
    assert "ENV LANG=C.UTF-8" in changes and "WORKDIR /runtime" in changes
    assert 'LABEL "example"="kept"' in changes and "EXPOSE 7070/tcp" in changes
    assert 'HEALTHCHECK CMD ["true"]' in changes
    assert not any(change.startswith("ENTRYPOINT ") for change in changes)


def test_image_clone_keeps_token_out_of_origin_arguments_and_logs(tmp_path):
    real_git = shutil.which("git")
    origin = tmp_path / "origin"
    subprocess.run([real_git, "init", "-q", "-b", "main", str(origin)], check=True)
    (origin / "tools").mkdir()
    shutil.copy(ROOT / "tools/audit_sitl_image.py", origin / "tools")
    subprocess.run([real_git, "-C", str(origin), "add", "."], check=True)
    subprocess.run([real_git, "-C", str(origin), "-c", "user.name=Compatibility Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
    token = "ghp_" + "CanarySecret123" * 3
    secret = tmp_path / "token"
    secret.write_text(token)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argument_log, proof = tmp_path / "argv.jsonl", tmp_path / "proof"
    transport = bindir / "git"
    transport.write_text(f'''#!{sys.executable}
import hashlib,json,os,pathlib,subprocess,sys
args=sys.argv[1:]
with open({str(argument_log)!r},'a') as log: log.write(json.dumps(args)+'\\n')
if 'clone' in args:
    token=subprocess.check_output([os.environ['GIT_ASKPASS'], "Password for 'https://x-access-token@github.com': "])
    pathlib.Path({str(proof)!r}).write_text(hashlib.sha256(token).hexdigest())
    args[args.index('--branch')+2]={str(origin)!r}
raise SystemExit(subprocess.call([{real_git!r},*args]))
''')
    transport.chmod(0o700)
    source = (ROOT / "tools/sitl_image_prepare.sh").read_text().rsplit('\nmain "$@"', 1)[0]
    clone = tmp_path / "checkout"
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
           "MDS_BASE_DIR": str(clone), "MDS_PX4_DIR": str(tmp_path / "px4"),
           "MDS_REPO_URL": "https://github.com/example/repo.git", "MDS_BRANCH": "main",
           "MDS_GIT_AUTH_TOKEN_FILE": str(secret)}
    script = source + f'\nSCRIPT_DIR="{ROOT / "tools"}"\nload_git_auth_token\nfresh_clone_mds_repo\n'
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    remote = subprocess.check_output([real_git, "-C", str(clone), "remote", "get-url", "origin"], text=True).strip()
    assert remote == env["MDS_REPO_URL"]
    assert proof.read_text() == hashlib.sha256(token.encode()).hexdigest()
    assert token not in argument_log.read_text() + result.stdout + result.stderr + (clone / ".git/config").read_text()


def test_changed_major_libraries_round_trip(tmp_path):
    from git import Repo
    from lxml import etree
    from PIL import Image

    repo = Repo.init(tmp_path / "git")
    (Path(repo.working_tree_dir) / "value").write_text("one\n")
    repo.index.add(["value"])
    repo.index.commit("local compatibility test")
    assert repo.head.commit.message == "local compatibility test"
    assert etree.fromstring(b"<root><child>value</child></root>").findtext("child") == "value"
    image = Image.new("RGB", (12, 8), "navy")
    image.save(tmp_path / "preview.png")
    with Image.open(tmp_path / "preview.png") as loaded:
        assert loaded.size == (12, 8) and loaded.getpixel((0, 0)) == (0, 0, 128)
