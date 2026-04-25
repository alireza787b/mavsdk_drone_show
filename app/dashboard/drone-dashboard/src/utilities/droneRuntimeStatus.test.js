import { DRONE_RUNTIME_CLOCK_PROP } from '../constants/fieldMappings';
import { getDroneRuntimeStatus } from './droneRuntimeStatus';

describe('droneRuntimeStatus', () => {
  test('reports live telemetry when telemetry is fresh', () => {
    const nowMs = 1_700_000_000_000;
    const status = getDroneRuntimeStatus({
      timestamp: nowMs - 2_000,
      heartbeat_last_seen: nowMs - 12_000,
    }, nowMs);

    expect(status.level).toBe('online');
    expect(status.label).toBe('Live telemetry');
  });

  test('reports heartbeat-only when telemetry is delayed but heartbeat is recent', () => {
    const nowMs = 1_700_000_000_000;
    const status = getDroneRuntimeStatus({
      timestamp: nowMs - 12_000,
      heartbeat_last_seen: nowMs - 6_000,
    }, nowMs);

    expect(status.level).toBe('degraded');
    expect(status.label).toBe('Heartbeat only');
  });

  test('reports link lost when neither telemetry nor heartbeat is recent', () => {
    const nowMs = 1_700_000_000_000;
    const status = getDroneRuntimeStatus({
      timestamp: nowMs - 40_000,
      heartbeat_last_seen: nowMs - 40_000,
    }, nowMs);

    expect(status.level).toBe('offline');
    expect(status.label).toBe('Link lost');
  });

  test('reports never seen when no timing data exists yet', () => {
    const status = getDroneRuntimeStatus({}, 1_700_000_000_000);

    expect(status.level).toBe('unknown');
    expect(status.label).toBe('Never seen');
  });

  test('uses the runtime clock hint when the client clock is badly skewed', () => {
    const telemetryTimestamp = 1_700_000_000_000;
    const receivedAtMs = 1_800_000_000_000;
    const drone = {
      timestamp: telemetryTimestamp,
      heartbeat_last_seen: telemetryTimestamp - 1_000,
    };

    Object.defineProperty(drone, DRONE_RUNTIME_CLOCK_PROP, {
      value: {
        referenceTimestampMs: telemetryTimestamp,
        receivedAtMs,
      },
      enumerable: false,
    });

    const status = getDroneRuntimeStatus(drone, receivedAtMs);
    expect(status.level).toBe('online');
    expect(status.label).toBe('Live telemetry');
  });

  test('uses server now hint even when browser skew is moderate', () => {
    const telemetryTimestamp = 1_700_000_000_000;
    const receivedAtMs = 1_700_000_020_000;
    const drone = {
      timestamp: telemetryTimestamp,
      heartbeat_last_seen: telemetryTimestamp - 1_000,
    };

    Object.defineProperty(drone, DRONE_RUNTIME_CLOCK_PROP, {
      value: {
        referenceTimestampMs: telemetryTimestamp,
        referenceNowMs: telemetryTimestamp + 2_000,
        receivedAtMs,
      },
      enumerable: false,
    });

    const status = getDroneRuntimeStatus(drone, receivedAtMs);
    expect(status.level).toBe('online');
    expect(status.label).toBe('Live telemetry');
    expect(status.tooltip).not.toMatch(/Browser clock offset/);
  });

  test('still ages out to offline when time elapses after the runtime clock hint', () => {
    const telemetryTimestamp = 1_700_000_000_000;
    const receivedAtMs = 1_800_000_000_000;
    const drone = {
      timestamp: telemetryTimestamp,
      heartbeat_last_seen: telemetryTimestamp,
    };

    Object.defineProperty(drone, DRONE_RUNTIME_CLOCK_PROP, {
      value: {
        referenceTimestampMs: telemetryTimestamp,
        receivedAtMs,
      },
      enumerable: false,
    });

    const status = getDroneRuntimeStatus(drone, receivedAtMs + 40_000);
    expect(status.level).toBe('offline');
    expect(status.label).toBe('Link lost');
  });

  test('prefers update_time over request-time timestamp when telemetry is stale', () => {
    const nowMs = 1_700_000_000_000;
    const status = getDroneRuntimeStatus({
      timestamp: nowMs - 2_000,
      update_time: Math.floor((nowMs - 40_000) / 1000),
      heartbeat_last_seen: nowMs - 5_000,
    }, nowMs);

    expect(status.level).toBe('degraded');
    expect(status.label).toBe('Heartbeat only');
  });

  test('does not treat failed telemetry poll timestamp as live telemetry', () => {
    const nowMs = 1_700_000_000_000;
    const status = getDroneRuntimeStatus({
      timestamp: nowMs,
      update_time: null,
      telemetry_available: false,
      heartbeat_last_seen: null,
    }, nowMs);

    expect(status.level).toBe('unknown');
    expect(status.label).toBe('Never seen');
  });
});
