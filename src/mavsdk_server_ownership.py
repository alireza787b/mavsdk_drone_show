"""Explicit borrowing for a motion action beside an existing role session.

The mission manager grants borrowing only while it owns a live leader session.
Borrowers never create, replace, or terminate the session's server. Vehicle
connection readiness remains the caller's responsibility.
"""
from dataclasses import dataclass, field
import fcntl
import os
import psutil
import tempfile


class MotionControlLease:
    """Process-lifetime exclusion between a borrowed action and follower control.

    An OS lock has no timeout or stale PID recovery policy: process death closes
    it. All participants use the same vehicle endpoint; descriptors are not
    inherited by their subprocesses.
    """

    def __init__(self, descriptor):
        self.descriptor = descriptor

    @classmethod
    def acquire(cls, grpc_port):
        path = os.path.join(tempfile.gettempdir(), f"mds-motion-{os.getuid()}-{int(grpc_port)}.lock")
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            return None
        except BaseException:
            os.close(descriptor)
            raise
        return cls(descriptor)

    def release(self):
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None

BORROW_SERVER_ENV = "MDS_BORROW_MAVSDK_SERVER"


@dataclass(frozen=True)
class BorrowedMavsdkServer:
    pid: int
    motion_lease: MotionControlLease | None = field(default=None, compare=False)

    def release(self):
        if self.motion_lease is not None:
            self.motion_lease.release()


def borrow_mavsdk_server(grpc_port: int, udp_port: int):
    if os.environ.get(BORROW_SERVER_ENV) != "1":
        return None
    for proc in psutil.process_iter(["pid", "cmdline"]):
        args = proc.info.get("cmdline") or []
        if not args or "mavsdk_server" not in os.path.basename(args[0]):
            continue
        if f"udp://:{udp_port}" not in args:
            continue
        if any(args[i:i + 2] == ["-p", str(grpc_port)] for i in range(len(args) - 1)):
            lease = MotionControlLease.acquire(grpc_port)
            if lease is None:
                raise RuntimeError("Another controller owns vehicle movement")
            return BorrowedMavsdkServer(proc.pid, lease)
    raise RuntimeError("The leader session's MAVSDK server is unavailable")
