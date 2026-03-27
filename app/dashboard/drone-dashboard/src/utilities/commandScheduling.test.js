import {
  buildCommandSchedule,
  CLOCK_OFFSET_WARNING_THRESHOLD_MS,
  COMMAND_SCHEDULE_MODES,
  formatClockOffsetLabel,
  formatDateTimeLocalInput,
  getFleetReferenceClock,
} from './commandScheduling';
import { attachDroneRuntimeClock } from '../constants/fieldMappings';

describe('commandScheduling', () => {
  test('builds immediate schedules explicitly', () => {
    const schedule = buildCommandSchedule({
      scheduleMode: COMMAND_SCHEDULE_MODES.NOW,
      referenceNowMs: 1_700_000_000_000,
    });

    expect(schedule.triggerTimeSec).toBe(0);
    expect(schedule.isImmediate).toBe(true);
    expect(schedule.summary).toBe('Immediate on acceptance');
  });

  test('builds delayed schedules against the provided reference clock', () => {
    const schedule = buildCommandSchedule({
      scheduleMode: COMMAND_SCHEDULE_MODES.DELAY,
      timeDelay: 30,
      referenceNowMs: 1_700_000_000_000,
    });

    expect(schedule.triggerTimeSec).toBe(1_700_000_030);
    expect(schedule.isImmediate).toBe(false);
    expect(schedule.summary).toMatch(/Executes in 30s/);
    expect(schedule.summary).toMatch(/UTC/);
  });

  test('rejects absolute times that are already past the reference clock', () => {
    const schedule = buildCommandSchedule({
      scheduleMode: COMMAND_SCHEDULE_MODES.ABSOLUTE,
      selectedDateTime: '2023-11-14T22:12:59',
      referenceNowMs: 1_700_000_000_000,
    });

    expect(schedule.error).toMatch(/already passed/i);
  });

  test('uses attached runtime clock metadata to derive a fleet reference clock', () => {
    const drone = attachDroneRuntimeClock(
      {
        timestamp: 1_700_000_000,
      },
      {
        receivedAtMs: 1_700_000_001_000,
        serverNowMs: 1_700_000_001_500,
      },
    );

    const referenceClock = getFleetReferenceClock([drone], 1_700_000_003_000);

    expect(referenceClock.isServerAligned).toBe(true);
    expect(referenceClock.referenceNowMs).toBe(1_700_000_003_500);
  });

  test('formats datetime-local values with seconds', () => {
    expect(formatDateTimeLocalInput('2026-03-27T08:20:25Z')).toMatch(/T\d{2}:\d{2}:\d{2}$/);
  });

  test('suppresses minor clock-offset labels and shows material ones', () => {
    expect(formatClockOffsetLabel(CLOCK_OFFSET_WARNING_THRESHOLD_MS - 1000)).toBeNull();
    expect(formatClockOffsetLabel(CLOCK_OFFSET_WARNING_THRESHOLD_MS + 1000)).toMatch(/Browser clock/);
  });
});
