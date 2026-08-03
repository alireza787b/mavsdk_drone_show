import os
import pwd
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "mds_git_access_check.sh"
RUNTIME_PATH_HELPER = REPO_ROOT / "tools" / "shell_runtime_paths.sh"


def _run(command, *, cwd=None, env=None):
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main-candidate"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.invalid"], cwd=repo)
    _run(["git", "config", "user.name", "MDS Test"], cwd=repo)
    (repo / "README.md").write_text("# test\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=repo)
    _run(["git", "commit", "-m", "seed"], cwd=repo)
    return repo


def test_git_access_check_accepts_reachable_branch(tmp_path):
    repo = _make_repo(tmp_path)
    result = _run([
        str(SCRIPT),
        "--repo-url",
        str(repo),
        "--branch",
        "main-candidate",
        "--mode",
        "sitl-read",
    ])

    assert "MDS git access check OK" in result.stdout
    assert "mode=sitl-read" in result.stdout


def test_git_access_check_fails_when_branch_is_missing(tmp_path):
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        [
            str(SCRIPT),
            "--repo-url",
            str(repo),
            "--branch",
            "missing-branch",
            "--mode",
            "image-prep",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode != 0
    assert "branch was not found" in result.stderr
    assert "docs/guides/custom-sitl-auth.md" in result.stderr


def test_git_access_check_rejects_credentials_embedded_in_repo_url(tmp_path):
    env = os.environ.copy()
    env.pop("MDS_GIT_AUTH_TOKEN_FILE", None)
    result = subprocess.run(
        [
            str(SCRIPT),
            "--repo-url",
            "https://user:secret@example.invalid/repo.git",
            "--branch",
            "main-candidate",
        ],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode != 0
    assert "Do not embed credentials" in result.stderr
    assert "secret" not in result.stderr


def test_runtime_path_helper_resolves_passwd_home_without_home_env():
    env = os.environ.copy()
    env.pop("HOME", None)
    env.pop("MDS_USER_HOME", None)

    result = _run(
        ["bash", "-c", f'source "{RUNTIME_PATH_HELPER}"; mds_resolve_user_home'],
        env=env,
    )

    assert result.stdout.strip() == pwd.getpwuid(os.getuid()).pw_dir


def test_ssh_access_check_uses_mds_home_when_supervisor_omits_home(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/bin/sh\n"
        "printf '0123456789abcdef0123456789abcdef01234567\\trefs/heads/main-candidate\\n'\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    ssh_key = tmp_path / "id_ed25519"
    ssh_key.write_text("test-only-key\n", encoding="utf-8")
    ssh_key.chmod(0o600)
    resolved_home = tmp_path / "runtime-home"
    resolved_home.mkdir()

    env = os.environ.copy()
    env.pop("HOME", None)
    env["MDS_USER_HOME"] = str(resolved_home)
    env["MDS_GIT_SSH_KEY_FILE"] = str(ssh_key)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = _run(
        [
            str(SCRIPT),
            "--repo-url",
            "git@github.com:example/private.git",
            "--branch",
            "main-candidate",
            "--mode",
            "sitl-read",
        ],
        env=env,
    )

    assert "auth=ssh-key-file" in result.stdout
    assert (resolved_home / ".ssh").is_dir()
