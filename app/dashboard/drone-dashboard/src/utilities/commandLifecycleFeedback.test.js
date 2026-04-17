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

  it('keeps the initial submission toast provisional when acknowledgments are still arriving', async () => {
    sendDroneCommand.mockResolvedValue({
      success: true,
      command_id: 'cmd-partial-acks',
      mission_name: 'TAKE_OFF',
      submitted_count: 5,
      target_drones: ['1', '2', '3', '4', '5'],
      ack_summary: {
        accepted: 3,
        offline: 0,
        rejected: 0,
        errors: 0,
      },
      tracking_phase: 'awaiting_ack',
    });

    getCommandStatus.mockResolvedValue({
      phase: 'terminal',
      outcome: 'completed',
      progress: {
        stage: 'completed',
        message: 'Completed successfully on 5/5 accepted drone(s).',
      },
      executions: {
        expected: 5,
        succeeded: 5,
        failed: 0,
      },
      acks: {
        expected: 5,
        received: 5,
        accepted: 5,
        offline: 0,
        rejected: 0,
        errors: 0,
      },
    });

    await submitCommandWithLifecycleFeedback(
      {
        missionType: 10,
        uiMeta: { operatorLabel: 'Take Off' },
      },
      { trackTimeoutMs: 10000 },
    );

    await flushMicrotasks();

    expect(toast.info.mock.calls.map(([message]) => message)).toContain(
      'Take Off submitted. 3/5 acknowledgments received so far. Monitoring remaining acknowledgments and outcome in background.',
    );
  });

  it('uses the backend mission-aware tracking timeout when no frontend override is provided', async () => {
    sendDroneCommand.mockResolvedValue({
      success: true,
      command_id: 'cmd-456',
      mission_name: 'RETURN_RTL',
      submitted_count: 3,
      target_drones: ['1', '2', '3'],
      ack_summary: {
        accepted: 3,
        offline: 0,
        rejected: 0,
        errors: 0,
      },
      tracking_phase: 'pending_execution',
      tracking_timeout_ms: 2500,
    });

    getCommandStatus.mockResolvedValue({
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
    });

    await submitCommandWithLifecycleFeedback({
      missionType: 104,
      uiMeta: { operatorLabel: 'Return RTL' },
    });

    await flushMicrotasks();
    await advanceLifecyclePoll(1500);
    await advanceLifecyclePoll(1500);

    expect(toast.warn).toHaveBeenCalledWith(
      'Return RTL was accepted, but tracking did not close before the timeout. The last known state remains visible.',
    );
  });

  it('uses server time instead of raw browser time for the initial scheduled snapshot', async () => {
    jest.setSystemTime(new Date('2026-04-01T12:00:10Z'));
    sendDroneCommand.mockResolvedValue({
      success: true,
      command_id: 'cmd-server-time',
      mission_name: 'SWARM_TRAJECTORY',
      submitted_count: 1,
      target_drones: ['1'],
      ack_summary: {
        accepted: 1,
        offline: 0,
        rejected: 0,
        errors: 0,
      },
      tracking_phase: 'pending_execution',
      timestamp: Date.parse('2026-04-01T12:00:00Z'),
    });
    getCommandStatus.mockResolvedValue({
      phase: 'terminal',
      outcome: 'completed',
      progress: {
        stage: 'completed',
        message: 'Completed successfully on 1/1 accepted drone(s).',
      },
      executions: {
        expected: 1,
        succeeded: 1,
        failed: 0,
      },
      acks: {
        expected: 1,
        offline: 0,
        rejected: 0,
        errors: 0,
      },
    });

    const onCommandAccepted = jest.fn();

    await submitCommandWithLifecycleFeedback(
      {
        missionType: 4,
        triggerTime: String(Math.floor(Date.parse('2026-04-01T12:00:05Z') / 1000)),
        uiMeta: { operatorLabel: 'Swarm Trajectory' },
      },
      {
        onCommandAccepted,
        trackTimeoutMs: 10000,
      },
    );

    expect(onCommandAccepted).toHaveBeenCalledWith(
      expect.objectContaining({
        progress: expect.objectContaining({
          stage: 'scheduled',
          message: expect.stringMatching(/Waiting for the scheduled trigger time/i),
        }),
      }),
      expect.any(Object),
    );
  });

  it('emits lifecycle callbacks for submission, status updates, and terminal completion', async () => {
    sendDroneCommand.mockResolvedValue({
      success: true,
      command_id: 'cmd-789',
      mission_name: 'SWARM_TRAJECTORY',
      submitted_count: 2,
      target_drones: ['1', '2'],
      ack_summary: {
        accepted: 2,
        offline: 0,
        rejected: 0,
        errors: 0,
      },
      tracking_phase: 'pending_execution',
    });

    getCommandStatus
      .mockResolvedValueOnce({
        command_id: 'cmd-789',
        phase: 'in_progress',
        progress: {
          stage: 'executing',
          label: 'Execution in progress',
          message: 'Execution is active on 2 drone(s).',
          active: 2,
          completed: 0,
          remaining: 2,
        },
        executions: {
          expected: 2,
          succeeded: 0,
          failed: 0,
          active: 2,
          remaining: 2,
        },
        acks: {
          expected: 2,
          received: 2,
          accepted: 2,
          offline: 0,
          rejected: 0,
          errors: 0,
        },
      })
      .mockResolvedValueOnce({
        command_id: 'cmd-789',
        phase: 'terminal',
        outcome: 'completed',
        progress: {
          stage: 'completed',
          label: 'Completed',
          message: 'Completed successfully on 2/2 accepted drone(s).',
          active: 0,
          completed: 2,
          remaining: 0,
        },
        executions: {
          expected: 2,
          succeeded: 2,
          failed: 0,
          active: 0,
          remaining: 0,
        },
        acks: {
          expected: 2,
          received: 2,
          accepted: 2,
          offline: 0,
          rejected: 0,
          errors: 0,
        },
      });

    const onCommandAccepted = jest.fn();
    const onStatusUpdate = jest.fn();
    const onTrackingComplete = jest.fn();

    await submitCommandWithLifecycleFeedback(
      {
        missionType: 4,
        target_drones: ['1', '2'],
        uiMeta: {
          operatorLabel: 'Swarm Trajectory',
          targetLabel: '2 selected drones',
          targetDescriptor: 'Selected drones: 1, 2',
        },
      },
      {
        trackTimeoutMs: 10000,
        onCommandAccepted,
        onStatusUpdate,
        onTrackingComplete,
      },
    );

    await flushMicrotasks();
    await advanceLifecyclePoll(1500);
    await advanceLifecyclePoll(1500);

    expect(onCommandAccepted).toHaveBeenCalledWith(
      expect.objectContaining({
        commandId: 'cmd-789',
        commandLabel: 'Swarm Trajectory',
        targetLabel: '2 selected drones',
        canCancelMission: true,
      }),
      expect.objectContaining({
        command_id: 'cmd-789',
      }),
    );
    expect(onStatusUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        commandId: 'cmd-789',
        progress: expect.objectContaining({
          stage: 'executing',
          label: 'Execution in progress',
        }),
      }),
      expect.objectContaining({
        phase: 'in_progress',
      }),
    );
    expect(onTrackingComplete).toHaveBeenCalledWith(
      expect.objectContaining({
        commandId: 'cmd-789',
        isTerminal: true,
        outcome: 'completed',
        progress: expect.objectContaining({
          stage: 'completed',
        }),
      }),
      expect.objectContaining({
        phase: 'terminal',
      }),
    );
  });

  it('emits a tracking-unavailable callback after repeated poll errors', async () => {
    sendDroneCommand.mockResolvedValue({
      success: true,
      command_id: 'cmd-999',
      mission_name: 'SWARM_TRAJECTORY',
      submitted_count: 2,
      target_drones: ['1', '2'],
      ack_summary: {
        accepted: 2,
        offline: 0,
        rejected: 0,
        errors: 0,
      },
      tracking_phase: 'pending_execution',
    });

    getCommandStatus.mockRejectedValue(new Error('network'));

    const onTrackingUnavailable = jest.fn();

    await submitCommandWithLifecycleFeedback(
      {
        missionType: 4,
        target_drones: ['1', '2'],
        triggerTime: '0',
        uiMeta: {
          operatorLabel: 'Swarm Trajectory',
          targetLabel: '2 selected drones',
          targetDescriptor: 'Selected drones: 1, 2',
        },
      },
      {
        trackTimeoutMs: 10000,
        onTrackingUnavailable,
      },
    );

    await flushMicrotasks();
    await advanceLifecyclePoll(1500);
    await advanceLifecyclePoll(1500);
    await advanceLifecyclePoll(1500);

    expect(onTrackingUnavailable).toHaveBeenCalledWith(
      expect.objectContaining({
        commandId: 'cmd-999',
        trackingIssue: 'unavailable',
      }),
      expect.any(Error),
    );
  });
});
