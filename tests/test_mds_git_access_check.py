import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "mds_git_access_check.sh"


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
