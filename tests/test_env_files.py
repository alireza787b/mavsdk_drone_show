from src.settings.env_files import persist_env_updates, read_env_assignments


def test_env_files_read_simple_assignments(tmp_path):
    env_file = tmp_path / "local.env"
    env_file.write_text(
        "# comment\nMDS_MODE=real\nMDS_BRANCH='main'\nMDS_GCS_IP=\"10.0.0.5\"\n",
        encoding="utf-8",
    )

    assert read_env_assignments(env_file) == {
        "MDS_MODE": "real",
        "MDS_BRANCH": "main",
        "MDS_GCS_IP": "10.0.0.5",
    }


def test_env_files_persist_updates_preserves_comments_and_appends(tmp_path):
    env_file = tmp_path / "gcs.env"
    env_file.write_text(
        "# MDS GCS Configuration\nMDS_MODE=real\n\n# auth\nMDS_AUTH_ENABLED=false\n",
        encoding="utf-8",
    )

    result = persist_env_updates(
        env_file,
        {
            "MDS_MODE": "sitl",
            "MDS_AUTH_ENABLED": True,
            "MDS_API_AUTH_ENABLED": False,
        },
    )

    assert result.changed is True
    assert result.changed_keys == ("MDS_MODE", "MDS_AUTH_ENABLED", "MDS_API_AUTH_ENABLED")
    assert env_file.read_text(encoding="utf-8").splitlines() == [
        "# MDS GCS Configuration",
        "MDS_MODE=sitl",
        "",
        "# auth",
        "MDS_AUTH_ENABLED=true",
        "",
        "MDS_API_AUTH_ENABLED=false",
    ]


def test_env_files_persist_noop_does_not_rewrite(tmp_path):
    env_file = tmp_path / "gcs.env"
    env_file.write_text("MDS_MODE=real\n", encoding="utf-8")

    before = env_file.stat().st_mtime_ns
    result = persist_env_updates(env_file, {"MDS_MODE": "real"})
    after = env_file.stat().st_mtime_ns

    assert result.changed is False
    assert result.changed_keys == ()
    assert before == after
