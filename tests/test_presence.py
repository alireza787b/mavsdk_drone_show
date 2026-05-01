def test_presence_snapshot_separates_live_recent_stale_and_offline():
    from presence import PresenceThresholds, build_presence_snapshot

    thresholds = PresenceThresholds(
        live_sec=20,
        recent_loss_sec=30,
        stale_sec=60,
        long_offline_sec=300,
    )
    now = 1_700_000_000.0

    assert build_presence_snapshot(
        hw_id="1",
        heartbeat={"timestamp": int((now - 10) * 1000)},
        now=now,
        thresholds=thresholds,
    )["state"] == "live"
    assert build_presence_snapshot(
        hw_id="1",
        heartbeat={"timestamp": int((now - 25) * 1000)},
        now=now,
        thresholds=thresholds,
    )["state"] == "recently_lost"
    assert build_presence_snapshot(
        hw_id="1",
        heartbeat={"timestamp": int((now - 45) * 1000)},
        now=now,
        thresholds=thresholds,
    )["state"] == "stale"
    offline = build_presence_snapshot(
        hw_id="1",
        heartbeat={"timestamp": int((now - 301) * 1000)},
        now=now,
        thresholds=thresholds,
    )
    assert offline["state"] == "offline"
    assert offline["long_offline"] is True


def test_presence_snapshot_uses_recent_telemetry_as_fresh_source():
    from presence import PresenceThresholds, build_presence_snapshot

    now = 1_700_000_000.0
    snapshot = build_presence_snapshot(
        hw_id="1",
        heartbeat={"timestamp": int((now - 200) * 1000)},
        telemetry={"telemetry_available": True},
        telemetry_success_time=now - 2,
        now=now,
        thresholds=PresenceThresholds(20, 30, 60, 300),
    )

    assert snapshot["state"] == "live"
    assert snapshot["fresh"] is True
    assert snapshot["source"] == "telemetry"
