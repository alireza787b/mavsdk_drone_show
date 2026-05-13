import gzip
import http.client
import threading
from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from tools.spa_static_server import SPARequestHandler


@contextmanager
def run_spa_server(build_dir: Path):
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(SPARequestHandler, directory=str(build_dir)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def request(port: int, path: str, headers: dict | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("GET", path, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    headers_dict = {key.lower(): value for key, value in response.getheaders()}
    connection.close()
    return response.status, headers_dict, payload


def test_spa_server_serves_gzipped_static_assets_with_immutable_cache(tmp_path):
    build_dir = tmp_path / "build"
    static_dir = build_dir / "static" / "js"
    static_dir.mkdir(parents=True)
    asset_path = static_dir / "main.12345678.js"
    original = ("console.log('smart swarm');\n" * 512).encode("utf-8")
    asset_path.write_bytes(original)
    (build_dir / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")

    with run_spa_server(build_dir) as port:
        status, headers, payload = request(
            port,
            "/static/js/main.12345678.js",
            headers={"Accept-Encoding": "gzip"},
        )

    assert status == 200
    assert headers["content-encoding"] == "gzip"
    assert headers["cache-control"] == "public, max-age=31536000, immutable"
    assert headers["vary"] == "Accept-Encoding"
    assert gzip.decompress(payload) == original


def test_spa_server_falls_back_to_index_with_no_cache(tmp_path):
    build_dir = tmp_path / "build"
    build_dir.mkdir(parents=True)
    (build_dir / "index.html").write_text("<html><body>dashboard</body></html>", encoding="utf-8")

    with run_spa_server(build_dir) as port:
        status, headers, payload = request(port, "/sitl-control")

    assert status == 200
    assert headers["cache-control"] == "no-cache"
    assert b"dashboard" in payload


def test_spa_server_serves_route_prefixed_lazy_chunks_with_immutable_cache(tmp_path):
    build_dir = tmp_path / "build"
    static_dir = build_dir / "static" / "css"
    static_dir.mkdir(parents=True)
    asset_path = static_dir / "648.c4a881a1.chunk.css"
    asset_path.write_text(".fleet-ops{display:grid}", encoding="utf-8")
    (build_dir / "index.html").write_text("<html><body>dashboard</body></html>", encoding="utf-8")

    with run_spa_server(build_dir) as port:
        status, headers, payload = request(port, "/fleet-ops/static/css/648.c4a881a1.chunk.css")

    assert status == 200
    assert headers["cache-control"] == "public, max-age=31536000, immutable"
    assert payload == b".fleet-ops{display:grid}"


def test_spa_server_does_not_immutably_cache_missing_route_prefixed_chunks(tmp_path):
    build_dir = tmp_path / "build"
    (build_dir / "static" / "css").mkdir(parents=True)
    (build_dir / "index.html").write_text("<html><body>dashboard</body></html>", encoding="utf-8")

    with run_spa_server(build_dir) as port:
        status, headers, payload = request(port, "/fleet-ops/static/css/missing.chunk.css")

    assert status == 404
    assert headers["cache-control"] == "no-cache"
    assert b"Error response" in payload
