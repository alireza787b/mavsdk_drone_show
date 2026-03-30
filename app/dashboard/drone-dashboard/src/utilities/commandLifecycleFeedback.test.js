import { submitCommandWithLifecycleFeedback } from './commandLifecycleFeedback';
import { getCommandStatus, sendDroneCommand } from '../services/droneApiService';
import { toast } from 'react-toastify';

jest.mock('../services/droneApiService', () => ({
  sendDroneCommand: jest.fn(),
  getCommandStatus: jest.fn(),
}));

jest.mock('react-toastify', () => ({
  toast: {
    info: jest.fn(),
    success: jest.fn(),
    warn: jest.fn(),
    error: jest.fn(),
  },
}));

const flushMicrotasks = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

const advanceLifecyclePoll = async (ms = 1500) => {
  jest.advanceTimersByTime(ms);
  await flushMicrotasks();
  await flushMicrotasks();
};

describe('commandLifecycleFeedback', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.clearAllTimers();
    jest.useRealTimers();
  });

  it('emits progress toasts when a command moves from active execution into final completion', async () => {
    sendDroneCommand.mockResolvedValue({
      success: true,
      command_id: 'cmd-123',
      mission_name: 'SWARM_TRAJECTORY',
      submitted_count: 3,
      target_drones: ['1', '2', '3'],
      ack_summary: {
        accepted: 3,
        offline: 0,
        rejected: 0,
        errors: 0,
      },
      tracking_phase: 'pending_execution',
    });

    getCommandStatus
      .mockResolvedValueOnce({
        phase: 'in_progress',
        progress: {
          stage: 'executing',
          message: 'Execution is active on 3 drone(s).',
        },
        executions: {
          expected: 3,
          succeeded: 0,
          failed: 0,
        },
        acks: {
          expected: 3,
          offline: 0,
          rejected: 0,
          errors: 0,
        },
      })
      .mockResolvedValueOnce({
        phase: 'in_progress',
        progress: {
          stage: 'finishing',
          message: '2/3 accepted drone(s) have reported completion. Waiting for 1 remaining drone(s).',
        },
        executions: {
          expected: 3,
          succeeded: 2,
          failed: 0,
        },
        acks: {
          expected: 3,
          offline: 0,
          rejected: 0,
          errors: 0,
        },
      })
      .mockResolvedValueOnce({
        phase: 'terminal',
        outcome: 'completed',
        progress: {
          stage: 'completed',
          message: 'Completed successfully on 3/3 accepted drone(s).',
        },
        executions: {
          expected: 3,
          succeeded: 3,
          failed: 0,
        },
        acks: {
          expected: 3,
          offline: 0,
          rejected: 0,
          errors: 0,
        },
      });

    const response = await submitCommandWithLifecycleFeedback(
      {
        missionType: 4,
        uiMeta: { operatorLabel: 'Swarm Trajectory' },
      },
      { trackTimeoutMs: 10000 },
    );

    expect(response.success).toBe(true);

    await flushMicrotasks();

    expect(toast.success.mock.calls.map(([message]) => message)).toContain(
      'Swarm Trajectory accepted. 3/3 targeted drones accepted. Monitoring outcome in background.',
    );
    expect(toast.info.mock.calls.map(([message]) => message)).toContain(
      'Swarm Trajectory started. Execution is active on 3 drone(s).',
    );

    await advanceLifecyclePoll(1500);

    expect(toast.info.mock.calls.map(([message]) => message)).toContain(
      'Swarm Trajectory is still completing. 2/3 accepted drone(s) have reported completion. Waiting for 1 remaining drone(s).',
    );

    await advanceLifecyclePoll(1500);

    expect(toast.success.mock.calls.map(([message]) => message)).toContain(
      'Swarm Trajectory completed successfully (3/3 succeeded).',
    );
  });
});
