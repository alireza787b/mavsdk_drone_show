"""Durable GCS-side fleet candidate registry for enrollment and replacement workflows."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from functions.file_utils import load_json, save_json
from mds_logging import get_logger
from presence import resolve_presence_thresholds
from schemas import (
    FleetCandidateAcceptRequest,
    FleetCandidateAnnounceRequest,
    FleetCandidateRecoverRequest,
    FleetCandidateRecord,
    FleetCandidateReplaceRequest,
    FleetCandidateState,
)

logger = get_logger("fleet_candidates")

_registry_instance: "FleetCandidateRegistry | None" = None
_registry_lock = threading.Lock()
_RESOLVED_STATES = {
    FleetCandidateState.ACCEPTED.value,
    FleetCandidateState.REJECTED.value,
    FleetCandidateState.IGNORED.value,
    FleetCandidateState.SUPERSEDED.value,
}


def get_fleet_candidate_registry() -> "FleetCandidateRegistry":
    global _registry_instance
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = FleetCandidateRegistry()
    return _registry_instance


class FleetCandidateError(RuntimeError):
    """Base class for fleet candidate service failures."""


class FleetCandidateNotFoundError(FleetCandidateError):
    """Raised when a requested candidate does not exist."""


class FleetCandidateConflictError(FleetCandidateError):
    """Raised when a requested candidate mutation conflicts with current fleet state."""


class FleetCandidateValidationError(FleetCandidateError):
    """Raised when a candidate mutation is invalid."""


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return str(value).strip() or None


def _normalize_ip(value: Any) -> Optional[str]:
    normalized = _normalize_string(value)
    if normalized is None:
        return None
    if normalized.lower() in {"unknown", "n/a", "none"}:
        return None
    return normalized


def _normalize_timestamp_ms(value: Any, fallback_ms: Optional[int] = None) -> int:
    if value is None:
        return fallback_ms or _now_ms()
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback_ms or _now_ms()
    if numeric < 10_000_000_000:
        numeric *= 1000.0
    return int(numeric)


def _normalize_hw_id_int(value: Any) -> int:
    try:
        normalized = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise FleetCandidateValidationError("Candidate hw_id must be a positive integer for enrollment") from exc
    if normalized <= 0:
        raise FleetCandidateValidationError("Candidate hw_id must be a positive integer for enrollment")
    return normalized


def _active_candidate_sort_key(candidate: FleetCandidateRecord) -> tuple[int, int, int, str]:
    state_rank = {
        FleetCandidateState.CONFLICT.value: 0,
        FleetCandidateState.PENDING_OPERATOR_REVIEW.value: 1,
        FleetCandidateState.ACCEPTED.value: 2,
        FleetCandidateState.REJECTED.value: 3,
        FleetCandidateState.IGNORED.value: 4,
        FleetCandidateState.SUPERSEDED.value: 5,
    }
    try:
        hw_rank = int(candidate.hw_id or 0)
    except (TypeError, ValueError):
        hw_rank = 0
    return (
        state_rank.get(candidate.registration_state.value, 99),
        -int(candidate.last_seen or 0),
        hw_rank,
        candidate.candidate_id,
    )


class FleetCandidateRegistry:
    """Small durable registry for nodes awaiting enrollment, replacement, or review."""

    def __init__(self, state_path: str | None = None, events_path: str | None = None):
        default_root = Path(__file__).resolve().parents[1] / "runtime_data"
        self.state_path = Path(state_path or default_root / "fleet_candidates.json")
        self.events_path = Path(events_path or default_root / "fleet_candidate_events.jsonl")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._candidates: dict[str, dict[str, Any]] = {}
        if not self.state_path.exists():
            save_json(
                {
                    "version": 1,
                    "updated_at": _now_ms(),
                    "candidates": [],
                },
                str(self.state_path),
            )
        self._load_state()

    def _load_state(self) -> None:
        payload = load_json(str(self.state_path))
        raw_candidates = payload.get("candidates", []) if isinstance(payload, dict) else []
        loaded: dict[str, dict[str, Any]] = {}
        for raw_candidate in raw_candidates:
            if not isinstance(raw_candidate, dict):
                continue
            candidate_id = _normalize_string(raw_candidate.get("candidate_id"))
            if not candidate_id:
                continue
            try:
                record = FleetCandidateRecord.model_validate(raw_candidate)
            except Exception as exc:  # pragma: no cover - defensive against stale malformed state
                logger.warning("Skipping invalid fleet candidate %s: %s", candidate_id, exc)
                continue
            loaded[candidate_id] = record.model_dump(mode="json")
        self._candidates = loaded

    def _persist_state_locked(self) -> None:
        ordered = [self._candidates[key] for key in sorted(self._candidates)]
        save_json(
            {
                "version": 1,
                "updated_at": _now_ms(),
                "candidates": ordered,
            },
            str(self.state_path),
        )

    def _append_event_locked(self, event_type: str, candidate_id: str, payload: dict[str, Any]) -> None:
        event = {
            "timestamp": _now_ms(),
            "event_type": event_type,
            "candidate_id": candidate_id,
            "payload": payload,
        }
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True))
            stream.write("\n")

    def _find_candidate_key_locked(self, *, node_uuid: Optional[str], hw_id: Optional[str]) -> Optional[str]:
        if node_uuid:
            for candidate_id, raw in self._candidates.items():
                if _normalize_string(raw.get("node_uuid")) == node_uuid:
                    return candidate_id
        if hw_id:
            for candidate_id, raw in self._candidates.items():
                if _normalize_string(raw.get("hw_id")) == hw_id:
                    return candidate_id
        return None

    def _build_candidate_locked(
        self,
        *,
        candidate_id: str,
        hw_id: Optional[str],
        node_uuid: Optional[str],
        first_seen: int,
    ) -> dict[str, Any]:
        return FleetCandidateRecord(
            candidate_id=candidate_id,
            node_uuid=node_uuid,
            hw_id=hw_id,
            first_seen=first_seen,
            last_seen=first_seen,
            registration_state=FleetCandidateState.PENDING_OPERATOR_REVIEW,
        ).model_dump(mode="json")

    def _configured_maps(self, config_entries: list[dict[str, Any]]) -> tuple[set[str], dict[str, str]]:
        configured_hw_ids: set[str] = set()
        configured_ips: dict[str, str] = {}
        for entry in config_entries:
            hw_id = _normalize_string(entry.get("hw_id"))
            ip = _normalize_ip(entry.get("ip"))
            if hw_id:
                configured_hw_ids.add(hw_id)
            if hw_id and ip:
                configured_ips[ip] = hw_id
        return configured_hw_ids, configured_ips

    def _refresh_candidate_state_locked(
        self,
        raw_record: dict[str, Any],
        *,
        config_entries: list[dict[str, Any]],
        now_ms: Optional[int] = None,
    ) -> FleetCandidateRecord:
        now_ms = now_ms or _now_ms()
        record = dict(raw_record)
        state = _normalize_string(record.get("registration_state")) or FleetCandidateState.PENDING_OPERATOR_REVIEW.value
        configured_hw_ids, configured_ips = self._configured_maps(config_entries)
        conflict_reasons: list[str] = []

        hw_id = _normalize_string(record.get("hw_id"))
        if not hw_id and not _normalize_string(record.get("node_uuid")):
            conflict_reasons.append("missing_identity")

        if state not in _RESOLVED_STATES:
            if hw_id and hw_id in configured_hw_ids:
                conflict_reasons.append("hw_id_already_in_fleet")

            for ip in record.get("ip_addresses") or []:
                normalized_ip = _normalize_ip(ip)
                if not normalized_ip:
                    continue
                owner = configured_ips.get(normalized_ip)
                if owner and owner != hw_id:
                    conflict_reasons.append("ip_already_in_fleet")
                    break

            if hw_id:
                duplicate_candidates = [
                    candidate_id
                    for candidate_id, other in self._candidates.items()
                    if candidate_id != record["candidate_id"]
                    and _normalize_string(other.get("hw_id")) == hw_id
                    and _normalize_string(other.get("registration_state")) not in _RESOLVED_STATES
                ]
                if duplicate_candidates:
                    conflict_reasons.append("duplicate_candidate_hw_id")

            state = (
                FleetCandidateState.CONFLICT.value
                if conflict_reasons
                else FleetCandidateState.PENDING_OPERATOR_REVIEW.value
            )

        last_heartbeat = record.get("last_heartbeat")
        heartbeat_age_sec = None
        heartbeat_status = "unknown"
        thresholds = resolve_presence_thresholds()
        if last_heartbeat:
            heartbeat_age_sec = max(0, int((now_ms - int(last_heartbeat)) / 1000))
            if heartbeat_age_sec <= thresholds.live_sec:
                heartbeat_status = "online"
            elif heartbeat_age_sec <= thresholds.stale_sec:
                heartbeat_status = "stale"
            else:
                heartbeat_status = "offline"

        record["registration_state"] = state
        record["conflict_reasons"] = sorted(set(conflict_reasons))
        record["heartbeat_age_sec"] = heartbeat_age_sec
        record["heartbeat_status"] = heartbeat_status
        record["ip_addresses"] = sorted({_normalize_ip(ip) for ip in record.get("ip_addresses") or [] if _normalize_ip(ip)})
        return FleetCandidateRecord.model_validate(record)

    def list_candidates(self, *, load_config, include_inactive: bool = False) -> list[FleetCandidateRecord]:
        with self._lock:
            config_entries = load_config()
            now_ms = _now_ms()
            results: list[FleetCandidateRecord] = []
            for candidate_id in sorted(self._candidates):
                raw_record = self._candidates[candidate_id]
                record = self._refresh_candidate_state_locked(raw_record, config_entries=config_entries, now_ms=now_ms)
                self._candidates[candidate_id] = record.model_dump(mode="json")
                if include_inactive or record.registration_state.value not in _RESOLVED_STATES:
                    results.append(record)
            self._persist_state_locked()
            return sorted(results, key=_active_candidate_sort_key)

    def get_candidate(self, candidate_id: str, *, load_config) -> FleetCandidateRecord:
        normalized_candidate_id = _normalize_string(candidate_id)
        with self._lock:
            raw_record = self._candidates.get(normalized_candidate_id or "")
            if raw_record is None:
                raise FleetCandidateNotFoundError(f"Candidate {candidate_id} not found")
            record = self._refresh_candidate_state_locked(raw_record, config_entries=load_config(), now_ms=_now_ms())
            self._candidates[record.candidate_id] = record.model_dump(mode="json")
            self._persist_state_locked()
            return record

    def observe_heartbeat(self, heartbeat: dict[str, Any], *, load_config) -> Optional[FleetCandidateRecord]:
        hw_id = _normalize_string(heartbeat.get("hw_id"))
        if not hw_id:
            return None

        timestamp_ms = _normalize_timestamp_ms(heartbeat.get("timestamp"))
        heartbeat_ip = _normalize_ip(heartbeat.get("ip"))

        with self._lock:
            config_entries = load_config()
            configured_hw_ids, _configured_ips = self._configured_maps(config_entries)
            candidate_key = self._find_candidate_key_locked(node_uuid=None, hw_id=hw_id)
            is_new_candidate = False

            if candidate_key is None:
                if hw_id in configured_hw_ids:
                    return None
                candidate_key = f"hw-{hw_id}"
                self._candidates[candidate_key] = self._build_candidate_locked(
                    candidate_id=candidate_key,
                    hw_id=hw_id,
                    node_uuid=None,
                    first_seen=timestamp_ms,
                )
                is_new_candidate = True

            record = dict(self._candidates[candidate_key])
            previous_state = _normalize_string(record.get("registration_state")) or FleetCandidateState.PENDING_OPERATOR_REVIEW.value
            record["hw_id"] = hw_id
            record["last_seen"] = timestamp_ms
            record["last_heartbeat"] = timestamp_ms

            reported_pos_id = _normalize_string(heartbeat.get("pos_id"))
            detected_pos_id = _normalize_string(heartbeat.get("detected_pos_id"))
            if reported_pos_id:
                record["reported_pos_id"] = reported_pos_id
            if detected_pos_id:
                record["detected_pos_id"] = detected_pos_id
            if heartbeat_ip:
                ip_addresses = list(record.get("ip_addresses") or [])
                if heartbeat_ip not in ip_addresses:
                    ip_addresses.append(heartbeat_ip)
                record["ip_addresses"] = ip_addresses
                record["primary_control_ip"] = heartbeat_ip

            refreshed = self._refresh_candidate_state_locked(record, config_entries=config_entries, now_ms=_now_ms())
            self._candidates[candidate_key] = refreshed.model_dump(mode="json")
            self._persist_state_locked()

            if is_new_candidate:
                self._append_event_locked("candidate.first_seen", candidate_key, refreshed.model_dump(mode="json"))
            elif refreshed.registration_state.value != previous_state:
                self._append_event_locked(
                    "candidate.state_changed",
                    candidate_key,
                    {
                        "previous_state": previous_state,
                        "new_state": refreshed.registration_state.value,
                        "conflict_reasons": refreshed.conflict_reasons,
                    },
                )
            return refreshed

    def announce_candidate(self, request: FleetCandidateAnnounceRequest, *, load_config) -> FleetCandidateRecord:
        timestamp_ms = _normalize_timestamp_ms(request.timestamp)
        hw_id = _normalize_string(request.hw_id)
        node_uuid = _normalize_string(request.node_uuid)
        hostname = _normalize_string(request.hostname)
        candidate_key_seed = node_uuid or (f"hw-{hw_id}" if hw_id else None) or f"candidate-{uuid.uuid4().hex[:8]}"

        with self._lock:
            config_entries = load_config()
            candidate_key = self._find_candidate_key_locked(node_uuid=node_uuid, hw_id=hw_id) or candidate_key_seed
            record = dict(
                self._candidates.get(candidate_key)
                or self._build_candidate_locked(
                    candidate_id=candidate_key,
                    hw_id=hw_id,
                    node_uuid=node_uuid,
                    first_seen=timestamp_ms,
                )
            )
            previous_state = _normalize_string(record.get("registration_state")) or FleetCandidateState.PENDING_OPERATOR_REVIEW.value

            record.update(
                {
                    "node_uuid": node_uuid or record.get("node_uuid"),
                    "hw_id": hw_id or record.get("hw_id"),
                    "hostname": hostname or record.get("hostname"),
                    "role_hint": _normalize_string(request.role_hint) or record.get("role_hint"),
                    "repo_url": _normalize_string(request.repo_url) or record.get("repo_url"),
                    "branch": _normalize_string(request.branch) or record.get("branch"),
                    "commit": _normalize_string(request.commit) or record.get("commit"),
                    "bootstrap_version": _normalize_string(request.bootstrap_version) or record.get("bootstrap_version"),
                    "bootstrap_status": _normalize_string(request.bootstrap_status) or record.get("bootstrap_status"),
                    "network_mode": _normalize_string(request.network_mode) or record.get("network_mode"),
                    "primary_control_ip": _normalize_ip(request.primary_control_ip) or record.get("primary_control_ip"),
                    "mavlink_routing_mode": _normalize_string(request.mavlink_routing_mode) or record.get("mavlink_routing_mode"),
                    "mavlink_input_type": _normalize_string(request.mavlink_input_type) or record.get("mavlink_input_type"),
                    "mavlink_input_device": _normalize_string(request.mavlink_input_device) or record.get("mavlink_input_device"),
                    "last_seen": timestamp_ms,
                    "last_announce": timestamp_ms,
                }
            )
            if record.get("primary_control_ip"):
                ip_addresses = list(record.get("ip_addresses") or [])
                if record["primary_control_ip"] not in ip_addresses:
                    ip_addresses.append(record["primary_control_ip"])
                record["ip_addresses"] = ip_addresses

            refreshed = self._refresh_candidate_state_locked(record, config_entries=config_entries, now_ms=_now_ms())
            self._candidates[candidate_key] = refreshed.model_dump(mode="json")
            self._persist_state_locked()
            self._append_event_locked("candidate.announced", candidate_key, refreshed.model_dump(mode="json"))
            if refreshed.registration_state.value != previous_state:
                self._append_event_locked(
                    "candidate.state_changed",
                    candidate_key,
                    {
                        "previous_state": previous_state,
                        "new_state": refreshed.registration_state.value,
                        "conflict_reasons": refreshed.conflict_reasons,
                    },
                )
            return refreshed

    def _require_candidate_locked(self, candidate_id: str) -> dict[str, Any]:
        normalized_candidate_id = _normalize_string(candidate_id)
        raw_record = self._candidates.get(normalized_candidate_id or "")
        if raw_record is None:
            raise FleetCandidateNotFoundError(f"Candidate {candidate_id} not found")
        return dict(raw_record)

    def accept_candidate(
        self,
        candidate_id: str,
        request: FleetCandidateAcceptRequest,
        *,
        load_config,
        save_config,
        validate_and_process_config,
    ) -> tuple[FleetCandidateRecord, list[str]]:
        with self._lock:
            record = self._require_candidate_locked(candidate_id)
            candidate_hw_id = _normalize_hw_id_int(record.get("hw_id"))
            config_entries = list(load_config())

            if any(_normalize_string(entry.get("hw_id")) == str(candidate_hw_id) for entry in config_entries):
                raise FleetCandidateConflictError(f"hw_id {candidate_hw_id} is already enrolled in fleet config")

            candidate_ip = _normalize_ip(request.ip) or _normalize_ip(record.get("primary_control_ip"))
            if not candidate_ip:
                raise FleetCandidateValidationError("Accepted candidate requires a control-plane IP")

            new_entry = {
                "hw_id": candidate_hw_id,
                "pos_id": int(request.pos_id),
                "ip": candidate_ip,
                "mavlink_port": int(request.mavlink_port),
                "serial_port": request.serial_port,
                "baudrate": int(request.baudrate),
            }
            if request.color:
                new_entry["color"] = request.color
            if request.notes:
                new_entry["notes"] = request.notes

            report = validate_and_process_config([*config_entries, new_entry])
            summary = report.get("summary", {})
            if int(summary.get("duplicate_hw_ids_count", 0) or 0) > 0:
                raise FleetCandidateConflictError("Candidate acceptance would create duplicate hw_id entries")
            if int(summary.get("duplicates_count", 0) or 0) > 0:
                raise FleetCandidateConflictError("Candidate acceptance would create duplicate pos_id assignments")

            save_config(report["updated_config"])

            record["registration_state"] = FleetCandidateState.ACCEPTED.value
            record["resolution"] = "accepted_as_new"
            record["replacement_target_hw_id"] = None
            record["replacement_target_pos_id"] = str(request.pos_id)
            record["primary_control_ip"] = candidate_ip
            record["conflict_reasons"] = []
            if request.notes:
                record["notes"] = request.notes

            refreshed = self._refresh_candidate_state_locked(record, config_entries=report["updated_config"], now_ms=_now_ms())
            self._candidates[refreshed.candidate_id] = refreshed.model_dump(mode="json")
            self._persist_state_locked()
            self._append_event_locked("candidate.accepted", refreshed.candidate_id, refreshed.model_dump(mode="json"))

            warnings = []
            missing_trajectories = summary.get("missing_trajectories_count", 0) or 0
            role_swaps = summary.get("role_swaps_count", 0) or 0
            if missing_trajectories:
                warnings.append(f"{missing_trajectories} trajectory file warning(s) remain after acceptance")
            if role_swaps:
                warnings.append(f"{role_swaps} role-swap warning(s) remain after acceptance")

            return refreshed, warnings

    def replace_candidate(
        self,
        candidate_id: str,
        request: FleetCandidateReplaceRequest,
        *,
        load_config,
        save_config,
        load_swarm,
        save_swarm,
        validate_and_process_config,
    ) -> tuple[FleetCandidateRecord, list[str]]:
        with self._lock:
            record = self._require_candidate_locked(candidate_id)
            candidate_hw_id = _normalize_hw_id_int(record.get("hw_id"))
            config_entries = list(load_config())
            target_hw_id = int(request.target_hw_id)

            if candidate_hw_id == target_hw_id:
                raise FleetCandidateValidationError("Replacement candidate already uses the target hw_id")

            target_index = next(
                (idx for idx, entry in enumerate(config_entries) if _normalize_string(entry.get("hw_id")) == str(target_hw_id)),
                None,
            )
            if target_index is None:
                raise FleetCandidateNotFoundError(f"Fleet member hw_id {target_hw_id} not found")
            if any(
                idx != target_index and _normalize_string(entry.get("hw_id")) == str(candidate_hw_id)
                for idx, entry in enumerate(config_entries)
            ):
                raise FleetCandidateConflictError(f"Candidate hw_id {candidate_hw_id} already exists in fleet config")

            target_entry = dict(config_entries[target_index])
            updated_entry = dict(target_entry)
            updated_entry["hw_id"] = candidate_hw_id
            updated_entry["ip"] = _normalize_ip(request.ip) or _normalize_ip(record.get("primary_control_ip")) or target_entry.get("ip")
            if request.mavlink_port is not None:
                updated_entry["mavlink_port"] = int(request.mavlink_port)
            if request.serial_port is not None:
                updated_entry["serial_port"] = request.serial_port
            if request.baudrate is not None:
                updated_entry["baudrate"] = int(request.baudrate)
            if request.notes is not None:
                updated_entry["notes"] = request.notes

            proposed_config = list(config_entries)
            proposed_config[target_index] = updated_entry
            report = validate_and_process_config(proposed_config)
            summary = report.get("summary", {})
            if int(summary.get("duplicate_hw_ids_count", 0) or 0) > 0:
                raise FleetCandidateConflictError("Replacement would create duplicate hw_id entries")
            if int(summary.get("duplicates_count", 0) or 0) > 0:
                raise FleetCandidateConflictError("Replacement would create duplicate pos_id assignments")

            old_hw_id_str = str(target_hw_id)
            new_hw_id_str = str(candidate_hw_id)
            swarm_entries = list(load_swarm())
            if any(_normalize_string(entry.get("hw_id")) == new_hw_id_str for entry in swarm_entries):
                raise FleetCandidateConflictError(
                    f"Candidate hw_id {candidate_hw_id} already exists in swarm assignments"
                )
            updated_swarm: list[dict[str, Any]] = []
            for assignment in swarm_entries:
                updated_assignment = dict(assignment)
                if _normalize_string(updated_assignment.get("hw_id")) == old_hw_id_str:
                    updated_assignment["hw_id"] = candidate_hw_id
                if _normalize_string(updated_assignment.get("follow")) == old_hw_id_str:
                    updated_assignment["follow"] = candidate_hw_id
                updated_swarm.append(updated_assignment)

            save_config(report["updated_config"])
            save_swarm(updated_swarm)

            record["registration_state"] = FleetCandidateState.ACCEPTED.value
            record["resolution"] = "replaced_existing"
            record["replacement_target_hw_id"] = old_hw_id_str
            record["replacement_target_pos_id"] = _normalize_string(target_entry.get("pos_id"))
            record["primary_control_ip"] = _normalize_ip(updated_entry.get("ip")) or record.get("primary_control_ip")
            record["conflict_reasons"] = []
            if request.notes:
                record["notes"] = request.notes

            refreshed = self._refresh_candidate_state_locked(record, config_entries=report["updated_config"], now_ms=_now_ms())
            self._candidates[refreshed.candidate_id] = refreshed.model_dump(mode="json")
            self._persist_state_locked()
            self._append_event_locked("candidate.replaced", refreshed.candidate_id, refreshed.model_dump(mode="json"))

            warnings = []
            if not swarm_entries:
                warnings.append("No swarm assignments existed to rewrite for the replacement")
            missing_trajectories = summary.get("missing_trajectories_count", 0) or 0
            if missing_trajectories:
                warnings.append(f"{missing_trajectories} trajectory file warning(s) remain after replacement")

            return refreshed, warnings

    def recover_candidate(
        self,
        candidate_id: str,
        request: FleetCandidateRecoverRequest,
        *,
        load_config,
        save_config,
        validate_and_process_config,
    ) -> tuple[FleetCandidateRecord, list[str]]:
        with self._lock:
            record = self._require_candidate_locked(candidate_id)
            candidate_hw_id = _normalize_hw_id_int(record.get("hw_id"))
            config_entries = list(load_config())

            target_index = next(
                (idx for idx, entry in enumerate(config_entries) if _normalize_string(entry.get("hw_id")) == str(candidate_hw_id)),
                None,
            )
            if target_index is None:
                raise FleetCandidateNotFoundError(
                    f"Fleet member hw_id {candidate_hw_id} not found for recovery"
                )

            target_entry = dict(config_entries[target_index])
            updated_entry = dict(target_entry)
            resolved_ip = _normalize_ip(request.ip) or _normalize_ip(record.get("primary_control_ip"))
            if resolved_ip:
                updated_entry["ip"] = resolved_ip
            if request.mavlink_port is not None:
                updated_entry["mavlink_port"] = int(request.mavlink_port)
            if request.serial_port is not None:
                updated_entry["serial_port"] = request.serial_port
            if request.baudrate is not None:
                updated_entry["baudrate"] = int(request.baudrate)
            if request.notes is not None:
                updated_entry["notes"] = request.notes

            proposed_config = list(config_entries)
            proposed_config[target_index] = updated_entry
            report = validate_and_process_config(proposed_config)
            summary = report.get("summary", {})
            if int(summary.get("duplicate_hw_ids_count", 0) or 0) > 0:
                raise FleetCandidateConflictError("Recovery would create duplicate hw_id entries")
            if int(summary.get("duplicates_count", 0) or 0) > 0:
                raise FleetCandidateConflictError("Recovery would create duplicate pos_id assignments")

            save_config(report["updated_config"])

            record["registration_state"] = FleetCandidateState.ACCEPTED.value
            record["resolution"] = "recovered_existing"
            record["replacement_target_hw_id"] = str(candidate_hw_id)
            record["replacement_target_pos_id"] = _normalize_string(target_entry.get("pos_id"))
            record["primary_control_ip"] = _normalize_ip(updated_entry.get("ip")) or record.get("primary_control_ip")
            record["conflict_reasons"] = []
            if request.notes:
                record["notes"] = request.notes

            refreshed = self._refresh_candidate_state_locked(
                record,
                config_entries=report["updated_config"],
                now_ms=_now_ms(),
            )
            self._candidates[refreshed.candidate_id] = refreshed.model_dump(mode="json")
            self._persist_state_locked()
            self._append_event_locked("candidate.recovered", refreshed.candidate_id, refreshed.model_dump(mode="json"))

            warnings = []
            missing_trajectories = summary.get("missing_trajectories_count", 0) or 0
            role_swaps = summary.get("role_swaps_count", 0) or 0
            if missing_trajectories:
                warnings.append(f"{missing_trajectories} trajectory file warning(s) remain after recovery")
            if role_swaps:
                warnings.append(f"{role_swaps} role-swap warning(s) remain after recovery")

            return refreshed, warnings

    def update_candidate_state(
        self,
        candidate_id: str,
        *,
        new_state: FleetCandidateState,
        load_config,
        reason: Optional[str] = None,
    ) -> FleetCandidateRecord:
        with self._lock:
            record = self._require_candidate_locked(candidate_id)
            record["registration_state"] = new_state.value
            record["conflict_reasons"] = []
            if reason:
                record["notes"] = reason
            refreshed = self._refresh_candidate_state_locked(record, config_entries=load_config(), now_ms=_now_ms())
            self._candidates[refreshed.candidate_id] = refreshed.model_dump(mode="json")
            self._persist_state_locked()
            self._append_event_locked(
                f"candidate.{new_state.value}",
                refreshed.candidate_id,
                {"notes": refreshed.notes, "registration_state": refreshed.registration_state.value},
            )
            return refreshed
