"""Small inherited-FD payload transport shared by process result contracts."""
from __future__ import annotations

import os


def write_bounded_payload(fd: int, payload: bytes, *, limit: int,
                          nonblocking_atomic: bool = False) -> None:
    if fd < 3 or not payload or len(payload) > limit:
        raise ValueError("invalid descriptor or bounded payload")
    if nonblocking_atomic:
        # POSIX guarantees an all-or-nothing pipe write up to PIPE_BUF. Never
        # block a flight-control handoff on reporting transport availability.
        if len(payload) > os.fpathconf(fd, "PC_PIPE_BUF"):
            raise ValueError("payload exceeds atomic pipe write bound")
        os.set_blocking(fd, False)
        if os.write(fd, payload) != len(payload):
            raise OSError("bounded atomic write was incomplete")
        return
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("bounded payload write made no progress")
        view = view[written:]
