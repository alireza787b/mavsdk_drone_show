import json
import socketserver
import subprocess
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "tools" / "mds_node_announce.sh"


def write_identity_file(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "node_uuid": "node-abc",
                "hw_id": 12,
                "hostname": "mds-drone-012",
                "role_hint": "spare",
                "repo_url": "https://github.com/example/customer-mds.git",
                "branch": "main-candidate",
                "bootstrap_version": "4.5.0",
                "bootstrap_status": "completed",
                "network_mode": "netbird",
                "primary_control_ip": "100.64.0.12",
                "mavlink_routing_mode": "mavlink_anywhere_managed",
                "mavlink_input_type": "uart",
                "mavlink_input_device": "/dev/ttyAMA0",
            }
        ),
        encoding="utf-8",
    )


def write_local_env(path: Path, *, gcs_api_url: str | None = None, gcs_ip: str | None = None) -> None:
    lines = ["MDS_HW_ID=12"]
    if gcs_api_url:
        lines.append(f"MDS_GCS_API_BASE_URL={gcs_api_url}")
    if gcs_ip:
        lines.append(f"MDS_GCS_IP={gcs_ip}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class AnnounceRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        self.server.calls.append({"path": self.path, "body": json.loads(body)})
        payload = {
            "status": "ok",
            "message": "Candidate recorded",
            "candidate": {
                "candidate_id": "node-abc",
                "registration_state": "pending_operator_review",
            },
        }
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):  # pragma: no cover - test server noise
        return


class AnnounceTestServer(socketserver.TCPServer):
    allow_reuse_address = True


def run_server():
    server = AnnounceTestServer(("127.0.0.1", 0), AnnounceRequestHandler)
    server.calls = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def run_script(*args):
    return subprocess.run(
        ["bash", str(SCRIPT_PATH), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_node_announce_dry_run_writes_report_and_derives_payload(tmp_path):
    identity_file = tmp_path / "node_identity.json"
    report_file = tmp_path / "announce_report.json"
    write_identity_file(identity_file)

    result = run_script(
        "--identity-file",
        str(identity_file),
        "--gcs-api-url",
        "http://127.0.0.1:5000",
        "--dry-run",
        "--report-json",
        str(report_file),
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(report_file.read_text(encoding="utf-8"))
    assert report["status"] == "dry_run"
    assert report["gcs_api_url"] == "http://127.0.0.1:5000"
    assert report["endpoint"].endswith("/api/v1/fleet/candidates/announce")
    assert report["payload"]["node_uuid"] == "node-abc"
    assert report["payload"]["hw_id"] == 12
    assert "timestamp" in report["payload"]


def test_node_announce_posts_to_gcs_and_records_response(tmp_path):
    identity_file = tmp_path / "node_identity.json"
    report_file = tmp_path / "announce_report.json"
    write_identity_file(identity_file)
    server, thread = run_server()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        result = run_script(
            "--identity-file",
            str(identity_file),
            "--gcs-api-url",
            base_url,
            "--report-json",
            str(report_file),
        )
        assert result.returncode == 0, result.stderr
        assert len(server.calls) == 1
        assert server.calls[0]["path"] == "/api/v1/fleet/candidates/announce"
        assert server.calls[0]["body"]["hw_id"] == 12

        report = json.loads(report_file.read_text(encoding="utf-8"))
        assert report["status"] == "ok"
        assert report["candidate_id"] == "node-abc"
        assert report["registration_state"] == "pending_operator_review"
        assert report["message"] == "Candidate recorded"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_node_announce_uses_local_env_api_url_when_not_passed(tmp_path):
    identity_file = tmp_path / "node_identity.json"
    local_env_file = tmp_path / "local.env"
    report_file = tmp_path / "announce_report.json"
    write_identity_file(identity_file)
    write_local_env(local_env_file, gcs_api_url="http://127.0.0.1:5999/api/v1")

    result = run_script(
        "--identity-file",
        str(identity_file),
        "--local-env",
        str(local_env_file),
        "--dry-run",
        "--report-json",
        str(report_file),
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(report_file.read_text(encoding="utf-8"))
    assert report["status"] == "dry_run"
    assert report["gcs_api_url"] == "http://127.0.0.1:5999"
