import {
  getFriendlyMissionName,
  getMissionDisplayContext,
  getMissionStatusClass,
  isMissionEmpty,
} from './missionUtils';

describe('missionUtils', () => {
  test('treats empty mission values consistently as no mission', () => {
    expect(isMissionEmpty(null)).toBe(true);
    expect(isMissionEmpty(undefined)).toBe(true);
    expect(isMissionEmpty('')).toBe(true);
    expect(isMissionEmpty('N/A')).toBe(true);
    expect(isMissionEmpty('NONE')).toBe(true);
    expect(isMissionEmpty(0)).toBe(true);
    expect(getFriendlyMissionName(undefined)).toBe('No Mission');
    expect(getMissionStatusClass(undefined)).toBe('mission-none');
  });

  test('uses the active mission as the primary display value', () => {
    const result = getMissionDisplayContext('SWARM_TRAJECTORY', 'SMART_SWARM');

    expect(result.currentMissionName).toBe('Swarm Formation');
    expect(result.currentMissionStatusClass).toBe('mission-performance');
    expect(result.lastMissionName).toBe('Smart Swarm');
    expect(result.badgeTooltip).toBe('Current mission: Swarm Formation. Last mission: Smart Swarm.');
  });

  test('keeps historical context secondary when no active mission is loaded', () => {
    const result = getMissionDisplayContext('NONE', 'TAKE_OFF');

    expect(result.currentMissionName).toBe('No Mission');
    expect(result.currentMissionStatusClass).toBe('mission-none');
    expect(result.lastMissionName).toBe('Takeoff');
    expect(result.badgeTooltip).toBe('No active mission. Last mission: Takeoff.');
  });

  test('normalizes numeric mission values from telemetry', () => {
    const result = getMissionDisplayContext(4, 2);

    expect(result.currentMissionName).toBe('Swarm Formation');
    expect(result.lastMissionName).toBe('Smart Swarm');
    expect(result.currentMissionStatusClass).toBe('mission-performance');
  });
});
