"""Bounded PX4 ULog timestamp and logging-profile evidence.

The normal summary parser deliberately loads only a small topic allowlist.
Pyulog's ``last_timestamp`` follows that filter, so it is not an overall log
clock when a vehicle uses a different logging profile. This module recovers
the timestamp envelope without retaining any topic arrays.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class UlogTimestampEnvelope:
    """Bounded timestamp/profile evidence collected without topic arrays."""

    last_data_timestamp_us: int | None
    data_message_count: int
    logged_topics: tuple[str, ...]
    complete: bool
    error: str | None = None


def scan_ulog_timestamp_envelope(
    path: Path,
    ulog: Any,
) -> UlogTimestampEnvelope:
    """Scan timestamp fields from every logged topic with bounded memory."""

    try:
        from pyulog import ULog  # type: ignore

        header_type = getattr(ULog, "_MessageHeader")
        subscription_type = getattr(ULog, "_MessageAddLogged")
        message_formats = getattr(ulog, "message_formats", {}) or {}
        if not isinstance(message_formats, Mapping):
            raise TypeError("pyulog did not expose message formats")

        subscriptions: dict[int, Any] = {}
        logged_topics: set[str] = set()
        last_data_timestamp: int | None = None
        data_message_count = 0
        complete = not bool(getattr(ulog, "file_corruption", False))

        with path.open("rb") as stream:
            file_header = stream.read(16)
            if len(file_header) != 16 or file_header[:7] != ULog.HEADER_BYTES:
                raise ValueError("invalid ULog header")
            start_timestamp = int(struct.unpack("<Q", file_header[8:16])[0])

            while True:
                raw_header = stream.read(3)
                if not raw_header:
                    break
                if len(raw_header) != 3:
                    complete = False
                    break
                message_header = header_type()
                message_header.initialize(raw_header)
                payload = stream.read(int(message_header.msg_size))
                if len(payload) != int(message_header.msg_size):
                    complete = False
                    break

                if message_header.msg_type == ULog.MSG_TYPE_ADD_LOGGED_MSG:
                    try:
                        subscription = subscription_type(
                            payload,
                            message_header,
                            message_formats,
                        )
                    except Exception:
                        complete = False
                        continue
                    subscriptions[int(subscription.msg_id)] = subscription
                    logged_topics.add(str(subscription.message_name))
                    continue

                if message_header.msg_type == ULog.MSG_TYPE_REMOVE_LOGGED_MSG:
                    if len(payload) >= 2:
                        message_id = int(struct.unpack("<H", payload[:2])[0])
                        subscriptions.pop(message_id, None)
                    else:
                        complete = False
                    continue

                if message_header.msg_type != ULog.MSG_TYPE_DATA or len(payload) < 2:
                    continue

                message_id = int(struct.unpack("<H", payload[:2])[0])
                subscription = subscriptions.get(message_id)
                if subscription is None:
                    complete = False
                    continue
                data_size = len(payload) - 2
                minimum_size = int(subscription.dtype.itemsize)
                maximum_size = int(subscription.max_data_size)
                timestamp_offset = 2 + int(subscription.timestamp_offset)
                if (
                    data_size < minimum_size
                    or data_size > maximum_size
                    or timestamp_offset + 8 > len(payload)
                ):
                    complete = False
                    continue

                timestamp = int(struct.unpack_from("<Q", payload, timestamp_offset)[0])
                data_message_count += 1
                if timestamp < start_timestamp:
                    # PX4 can flush pre-log event history after opening a file.
                    # Such records are real events but cannot extend this log's
                    # end timestamp.
                    continue
                if last_data_timestamp is None or timestamp > last_data_timestamp:
                    last_data_timestamp = timestamp

        return UlogTimestampEnvelope(
            last_data_timestamp_us=last_data_timestamp,
            data_message_count=data_message_count,
            logged_topics=tuple(sorted(logged_topics)),
            complete=complete,
        )
    except Exception as exc:
        fallback_topics = tuple(
            sorted(str(name) for name in (getattr(ulog, "message_formats", {}) or {}))
        )
        return UlogTimestampEnvelope(
            last_data_timestamp_us=None,
            data_message_count=0,
            logged_topics=fallback_topics,
            complete=False,
            error=_safe_error(exc),
        )


def derive_ulog_duration(
    ulog: Any,
    timestamp_envelope: UlogTimestampEnvelope,
) -> tuple[float | None, dict[str, Any]]:
    """Choose the strongest timestamp span and label weaker fallbacks."""

    start = _safe_int_or_none(getattr(ulog, "start_timestamp", None))
    candidates: list[tuple[int, str, bool]] = []

    if start is not None and timestamp_envelope.last_data_timestamp_us is not None:
        candidates.append(
            (
                timestamp_envelope.last_data_timestamp_us,
                "overall_data_timestamps",
                not timestamp_envelope.complete,
            )
        )

    filtered_end = _safe_int_or_none(getattr(ulog, "last_timestamp", None))
    if start is not None and filtered_end is not None and filtered_end > start:
        candidates.append((filtered_end, "requested_topic_timestamps", True))

    event_end = _latest_logged_event_timestamp(ulog)
    if start is not None and event_end is not None and event_end > start:
        candidates.append((event_end, "logged_event_timestamps", True))

    valid_candidates = [
        candidate
        for candidate in candidates
        if start is not None and candidate[0] >= start
    ]
    if start is None or not valid_candidates:
        return None, _duration_evidence(
            "unavailable",
            lower_bound=True,
            timestamp_envelope=timestamp_envelope,
        )

    end, source, lower_bound = max(
        valid_candidates,
        key=lambda candidate: candidate[0],
    )
    return round((end - start) / 1_000_000.0, 3), _duration_evidence(
        source,
        lower_bound=lower_bound,
        timestamp_envelope=timestamp_envelope,
    )


def bounded_topic_names(
    names: Sequence[str],
    *,
    limit: int = 32,
) -> tuple[list[str], int, bool]:
    unique = sorted({str(name).strip() for name in names if str(name).strip()})
    bounded = [name[:128] for name in unique[:limit]]
    return bounded, len(unique), len(unique) > limit


def ulog_observability_warnings(
    *,
    requested_topics: set[str],
    parsed_topics: set[str],
    logged_topic_count: int,
    timestamp_envelope: UlogTimestampEnvelope,
    duration_evidence: Mapping[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if logged_topic_count and not parsed_topics.intersection(requested_topics):
        warnings.append(
            "The active PX4 logging profile contains none of the requested summary metric topics; "
            "GPS, battery, land-state, command, and position metrics remain unavailable."
        )
    if timestamp_envelope.error:
        warnings.append(
            f"The bounded all-topic timestamp scan was unavailable: {timestamp_envelope.error}."
        )
    elif not timestamp_envelope.complete:
        warnings.append(
            "The all-topic timestamp scan was incomplete; the reported duration is a lower bound."
        )
    if duration_evidence.get("source") == "logged_event_timestamps":
        warnings.append(
            "Duration is derived from logged event timestamps and may understate the full log span."
        )
    elif duration_evidence.get("source") == "requested_topic_timestamps":
        warnings.append(
            "Duration is derived from requested-topic timestamps and may understate the full log span."
        )
    elif duration_evidence.get("source") == "unavailable":
        warnings.append(
            "No trustworthy timestamp span was available; duration is unknown rather than zero."
        )
    return warnings[:16]


def _duration_evidence(
    source: str,
    *,
    lower_bound: bool,
    timestamp_envelope: UlogTimestampEnvelope,
) -> dict[str, Any]:
    return {
        "source": source,
        "lower_bound": lower_bound,
        "data_messages_scanned": timestamp_envelope.data_message_count,
        "timestamp_scan_complete": timestamp_envelope.complete,
    }


def _latest_logged_event_timestamp(ulog: Any) -> int | None:
    timestamps: list[int] = []
    for message in getattr(ulog, "logged_messages", []) or []:
        timestamp = _safe_int_or_none(getattr(message, "timestamp", None))
        if timestamp is not None:
            timestamps.append(timestamp)
    tagged = getattr(ulog, "logged_messages_tagged", {}) or {}
    if isinstance(tagged, Mapping):
        for messages in tagged.values():
            for message in messages or []:
                timestamp = _safe_int_or_none(getattr(message, "timestamp", None))
                if timestamp is not None:
                    timestamps.append(timestamp)
    return max(timestamps) if timestamps else None


def _safe_int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:240]
