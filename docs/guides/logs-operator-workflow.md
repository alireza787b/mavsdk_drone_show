# Logs: operator workflow

Open **Logs** in the sidebar. Start with the tab matching your task; GCS is the
initial source. These screenshots use synthetic aircraft, not a live fleet.

[Full-resolution six-step walkthrough](../assets/log-workspace/operator-guide.png)

| Task | Tab | Next action |
|---|---|---|
| Understand a current message | Live | Select a record |
| Review/export recorded MDS events | Sessions | Choose session → Export |
| Retrieve a PX4 recorder file | Flight logs | Choose aircraft → Inspect file |

## 1. Watch current events

![Live messages and compact source controls](../assets/log-workspace/guide-01-live-1440-dark.png)

**Warnings+** is the initial severity. Search immediately; use **Filters** for
component/time window. Select a message for full details. **Freeze view** freezes
the display only; missions and logging continue. **Follow latest** resumes it.
Connection and coverage labels describe this log stream, not aircraft readiness.

## 2. Review a recorded session

![Recorded-session review](../assets/log-workspace/guide-02-sessions-1440-dark.png)

Choose **Source**, then **Sessions** and a session. Search and filters apply to
the recording before paging. Use **Next page** for more records. Time bounds are
explicitly UTC: **After** excludes its exact instant; **Through** includes it.
An expired/changed session view needs **Refresh**, not a different aircraft.

## 3. Export evidence

![Export review with frozen source](../assets/log-workspace/guide-03-export-1440-dark.png)

**Export** reviews the exact source and sessions. **Whole selected sessions**
ignores current filters; **Current filters** exports all matching records, not
just the current page. Select JSONL or ZIP; multiple sessions use ZIP. A skipped
record count means coverage is incomplete. Narrow an oversized export.

## 4. Choose a flight record

![Flight recorder inventory](../assets/log-workspace/guide-04-inventory-1440-dark.png)

In **Flight logs**, choose one aircraft by callsign/hardware ID, then **Refresh**.
Inspect the intended record; file metadata time is not guaranteed takeoff time.
**Summary** reads bounded local metrics, with missing/partial evidence labelled.
**Open file** instead reads a local `.ulg` through the same temporary parser; it
does not need an aircraft or send the file to an external provider.

## 5. Prepare, save, verify

![Ready transfer and explicit Save file control](../assets/log-workspace/guide-06-ready-save-1440-dark.png)

Select **Download** with the aircraft grounded and disarmed under its recorder
policy. Continue working anywhere in the dashboard and open **ULog transfers**
to see the aircraft read, GCS copy, verification, and any reconnection. Reloading
the dashboard recovers the same request. If the first response is lost, MDS
looks up that request and does not repeat aircraft staging.

When you see **Ready to save**, choose **Save file**. The verified copy stays on
the GCS until its transfer expires or you remove it. It can be saved with the
aircraft offline. Use your browser’s Downloads view to check final save progress
or resume an interrupted save. If the aircraft read fails or the transfer
expires, use **Retry aircraft read** after checking the connection.

**View summary** opens the bounded PX4 metrics for the verified copy when it is
ready. Review the reported coverage and recording gaps. The raw file stays
available if the parser fails. **Open file** reads a local `.ulg` through the
bounded upload parser. Viewer accounts can request a derived onboard summary.

## Unavailable aircraft and maintenance

- With no aircraft selected/connected, GCS history and **Open file** remain useful.
  An unavailable inventory means unknown, not zero files.
- Stale data remains last observed; it never grants write/erase authority.
  Retry the selected source rather than changing identity implicitly.
- **Remove copy** deletes the verified GCS copy. Recorder originals stay on the aircraft.
  **Maintenance → Erase onboard logs** is a separate admin-only action with an
  exact-aircraft confirmation. It cannot be undone here; verify empty inventory.
- Raw downloads/erase are operator maintenance, not optional assistant/MCP tools.

For installation, API limits, security policy and diagnostics see the
[logging system guide](logging-system.md). New history/recovery behavior requires
updated GCS and companion source; it does not itself refresh a pinned SITL image.
