from types import SimpleNamespace
import pytest
from src.mavsdk_server_ownership import borrow_mavsdk_server, BorrowedMavsdkServer


def test_only_explicit_borrower_can_attach_to_matching_vehicle_server(monkeypatch):
    monkeypatch.setenv("MDS_BORROW_MAVSDK_SERVER", "1")
    process = SimpleNamespace(pid=42, info={"cmdline": ["/runtime/mavsdk_server", "-p", "50040", "udp://:14569"]})
    monkeypatch.setattr("src.mavsdk_server_ownership.psutil.process_iter", lambda *_: [process])
    borrowed = borrow_mavsdk_server(50040, 14569)
    assert borrowed == BorrowedMavsdkServer(42)
    borrowed.release()
    with pytest.raises(RuntimeError):
        borrow_mavsdk_server(50040, 14570)
    monkeypatch.delenv("MDS_BORROW_MAVSDK_SERVER")
    assert borrow_mavsdk_server(50040, 14569) is None


def test_action_cleanup_never_stops_borrowed_server():
    from actions import stop_mavsdk_server
    # Borrowed handles deliberately have no terminate/kill methods.
    stop_mavsdk_server(BorrowedMavsdkServer(42))


def test_motion_authority_is_exclusive_and_released(tmp_path, monkeypatch):
    from src.mavsdk_server_ownership import MotionControlLease
    monkeypatch.setattr("src.mavsdk_server_ownership.tempfile.gettempdir", lambda: str(tmp_path))
    first = MotionControlLease.acquire(50040)
    assert first is not None
    assert MotionControlLease.acquire(50040) is None
    first.release()
    first.release()
    second = MotionControlLease.acquire(50040)
    assert second is not None
    second.release()
