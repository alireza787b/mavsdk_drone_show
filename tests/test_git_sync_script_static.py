from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "update_repo_ssh.sh"


def test_git_sync_uses_scoped_flock_locking():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "flock -w" in source
    assert "GIT_SYNC_LOCK_MODE=\"flock\"" in source


def test_git_sync_does_not_use_git_gc_as_field_repair():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "git gc --prune" not in source
    assert "clean_reclone_repository" in source


def test_git_sync_does_not_delete_git_lock_files_broadly():
    source = SCRIPT.read_text(encoding="utf-8")
    cleanup_function = source.split("cleanup_git_locks() {", 1)[1].split("check_git_integrity() {", 1)[0]

    assert "rm -f \"$lock_file\"" not in cleanup_function
    assert "leaving in place" in cleanup_function
