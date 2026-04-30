from src.gcs_auth_client import gcs_auth_headers, read_gcs_api_token


def test_gcs_auth_headers_prefers_token_file(monkeypatch, tmp_path):
    token_file = tmp_path / "gcs_api_token"
    token_file.write_text("mds_token_from_file\n", encoding="utf-8")
    monkeypatch.setenv("MDS_GCS_API_TOKEN_FILE", str(token_file))

    assert read_gcs_api_token() == "mds_token_from_file"
    assert gcs_auth_headers({"X-Test": "1"}) == {
        "X-Test": "1",
        "Authorization": "Bearer mds_token_from_file",
    }


def test_gcs_auth_headers_allows_no_token(monkeypatch):
    monkeypatch.delenv("MDS_GCS_API_TOKEN_FILE", raising=False)

    assert read_gcs_api_token() is None
    assert gcs_auth_headers() == {}
