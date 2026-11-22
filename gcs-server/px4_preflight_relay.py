"""Per-peer PX4 report cache. Arrival cannot extend an existing native sample."""

import time

from src.px4_preflight_telemetry import Px4Verdict, REPORT_KEYS, current_preflight_report


def monotonic_ms():
    return time.monotonic_ns() // 1_000_000


class Px4PreflightRelay:
    def __init__(self):
        self.epoch = None
        self.retired = set()
        self.sent_ms = -1
        self.reports = {}
        self.details = {}
        self.watermarks = {}

    def update(self, state, *, earliest_send_ms, received_ms):
        epoch, sent_ms = state.get('px4_report_epoch'), state.get('px4_node_monotonic_ms')
        if not isinstance(epoch, str) or not epoch or type(sent_ms) is not int:
            self.reports.clear()
            return
        if epoch in self.retired or epoch == self.epoch and sent_ms < self.sent_ms:
            return
        if self.epoch != epoch:
            if self.epoch and epoch.split(':', 1)[0] == self.epoch.split(':', 1)[0] and sent_ms < self.sent_ms:
                return
            if self.epoch is not None:
                self.retired.add(self.epoch)
                if len(self.retired) > 256:
                    # The send clock still orders frames from retired FC
                    # generations in the same companion process.
                    self.retired.pop()
            self.epoch, self.sent_ms = epoch, -1
            self.reports.clear()
            self.details.clear()
            self.watermarks.clear()
        self.sent_ms = sent_ms
        for key in REPORT_KEYS:
            report = current_preflight_report(state, key)
            if report is None:
                self.reports.pop(key, None)
                # A repeated serialization of a cleared sample cannot restore it.
                self.details.pop(key, None)
                continue
            previous = self.watermarks.get(key)
            if previous and report.sample < previous[0]:
                continue
            if report.mode_problems is not None:
                self.details[key] = (report.revision, [item.model_dump() for item in report.mode_problems])
            if earliest_send_ms is None:
                continue
            deadline = earliest_send_ms + report.remaining_valid_ms
            if previous and previous[0] == report.sample:
                deadline = min(previous[1], deadline)
                if key not in self.reports:
                    continue
            self.watermarks[key] = (report.sample, deadline)
            if deadline <= received_ms:
                self.reports.pop(key, None)
                continue
            self.reports[key] = (deadline, Px4Verdict.model_validate(report.model_dump()).model_dump())

    def snapshot(self):
        result = {}
        for key, (deadline, verdict) in self.reports.items():
            if deadline > monotonic_ms():
                details = self.details.get(key)
                result[key] = (deadline, verdict, details[1] if details and details[0] == verdict['revision'] else None)
        return result
