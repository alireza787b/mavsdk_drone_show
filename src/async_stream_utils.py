"""Bounded lifecycle helpers for short-lived MAVSDK telemetry streams.

MAVSDK streams are asynchronous iterators and may stop producing samples
without ending.  A timeout check inside ``async for`` therefore is not a real
wall-clock bound.  Action code uses this module as the single contract for
waiting on a sample under a monotonic deadline and for closing the iterator on
every exit path.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable


ASYNC_STREAM_CLOSE_TIMEOUT_SEC = 0.5


def monotonic_deadline(timeout_sec: float) -> float:
    """Return a monotonic deadline for a positive, finite timeout."""

    timeout = float(timeout_sec)
    if timeout <= 0.0 or timeout != timeout or abs(timeout) == float("inf"):
        raise ValueError("stream timeout must be a positive finite number")
    return time.monotonic() + timeout


async def next_stream_sample(
    stream: Any,
    *,
    deadline: float,
    description: str,
) -> Any:
    """Return the next sample before *deadline* or raise ``TimeoutError``.

    Both a silent stream and a stream that ends before producing the required
    evidence are failures.  Callers retain one stable timeout/error contract
    instead of relying on SDK-specific iterator behavior.
    """

    remaining = deadline - time.monotonic()
    if remaining <= 0.0:
        raise TimeoutError(f"Timed out waiting for {description}")
    try:
        return await asyncio.wait_for(anext(stream), timeout=remaining)
    except StopAsyncIteration as exc:
        raise TimeoutError(
            f"Telemetry stream ended while waiting for {description}"
        ) from exc
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"Timed out waiting for {description}") from exc


async def close_async_stream(stream: Any) -> None:
    """Best-effort, bounded close for an asynchronous iterator."""

    close = getattr(stream, "aclose", None)
    if not callable(close):
        return
    try:
        result = close()
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=ASYNC_STREAM_CLOSE_TIMEOUT_SEC)
    except Exception:
        # Ordinary teardown failure is cleanup evidence only. It must not
        # replace the action result. asyncio.CancelledError is deliberately not
        # caught so cooperative task cancellation still propagates.
        return


@asynccontextmanager
async def managed_async_stream(
    stream_factory: Callable[[], Any],
) -> AsyncIterator[Any]:
    """Open one stream and close it on success, timeout, failure, or cancel."""

    stream = stream_factory()
    try:
        yield stream
    finally:
        await close_async_stream(stream)


__all__ = [
    "ASYNC_STREAM_CLOSE_TIMEOUT_SEC",
    "close_async_stream",
    "managed_async_stream",
    "monotonic_deadline",
    "next_stream_sample",
]
