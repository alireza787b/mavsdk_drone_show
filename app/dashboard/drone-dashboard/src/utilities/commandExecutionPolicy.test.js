import {
  getActionExecutionPolicy,
  getMissionExecutionPolicy,
  getMissionScheduleDoctrine,
  isSchedulableActionKey,
  isStrictSyncActionKey,
  isStrictSyncMissionType,
} from './commandExecutionPolicy';
import { DRONE_MISSION_TYPES } from '../constants/droneConstants';

describe('commandExecutionPolicy', () => {
  test('marks strict synchronized mission types explicitly', () => {
    expect(isStrictSyncMissionType(DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV)).toBe(true);
    expect(isStrictSyncMissionType(DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW)).toBe(true);
    expect(isStrictSyncMissionType(DRONE_MISSION_TYPES.SWARM_TRAJECTORY)).toBe(true);
    expect(isStrictSyncMissionType(DRONE_MISSION_TYPES.SMART_SWARM)).toBe(false);
  });

  test('returns strict sync mission doctrine only for synchronized mission types', () => {
    expect(getMissionScheduleDoctrine(DRONE_MISSION_TYPES.SWARM_TRAJECTORY)).toEqual(
      expect.objectContaining({
        label: 'Strict synchronized launch',
      })
    );
    expect(getMissionScheduleDoctrine(DRONE_MISSION_TYPES.SMART_SWARM)).toBeNull();
  });

  test('describes scheduled strict-sync missions as fail-closed on late delivery', () => {
    expect(
      getMissionExecutionPolicy(DRONE_MISSION_TYPES.SWARM_TRAJECTORY, { isImmediate: false })
    ).toMatch(/queue for the shared trigger/i);
    expect(
      getMissionExecutionPolicy(DRONE_MISSION_TYPES.SWARM_TRAJECTORY, { isImmediate: false })
    ).toMatch(/abort instead of joining late/i);
  });

  test('describes immediate launch actions and non-schedulable maintenance actions consistently', () => {
    expect(isSchedulableActionKey('TAKE_OFF')).toBe(true);
    expect(isStrictSyncActionKey('HOVER_TEST')).toBe(true);
    expect(isSchedulableActionKey('UPDATE_CODE')).toBe(false);
    expect(isSchedulableActionKey('PRECISION_MOVE')).toBe(false);
    expect(
      getActionExecutionPolicy({ actionKey: 'TAKE_OFF', isImmediate: true })
    ).toMatch(/retries PX4 armability briefly/i);
    expect(
      getActionExecutionPolicy({ actionKey: 'HOVER_TEST', isImmediate: false })
    ).toMatch(/queue for the shared trigger/i);
    expect(
      getActionExecutionPolicy({ actionKey: 'HOVER_TEST', isImmediate: false })
    ).toMatch(/abort instead of joining late/i);
    expect(
      getActionExecutionPolicy({ actionKey: 'UPDATE_CODE', isImmediate: false })
    ).toBe('Immediate only. This action is not queued behind a future trigger.');
    expect(
      getActionExecutionPolicy({ actionKey: 'PRECISION_MOVE', isImmediate: false })
    ).toMatch(/local offboard reposition/i);
  });
});
