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

const commandReceipt = ({
  command_id,
  mission_type = 10,
  mission_name = 'TAKE_OFF',
  target_drones = ['1'],
  ...overrides
}) => ({
  accepted_for_tracking: true,
  command_id,
  idempotency_key: `test-${command_id}`,
  replayed: false,
  mission_type,
  mission_name,
  target_drones,
  tracking_url: `/api/v1/commands/${command_id}`,
  message: 'Command accepted for tracked preparation.',
  timestamp: 1000,
  ...overrides,
});

describe('commandLifecycleFeedback', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.clearAllTimers();
    jest.useRealTimers();
  });

  it('passes one canonical command draft to the serializer with typed ground-test evidence', async () => {
    sendDroneCommand.mockResolvedValue(commandReceipt({
      command_id: 'cmd-ground-test',
      mission_type: 100,
      mission_name: 'TEST',
    }));
    getCommandStatus.mockResolvedValue({
      command_id: 'cmd-ground-test',
      phase: 'terminal',
      outcome: 'failed',
      acks: { expected: 1, received: 0, accepted: 0 },
      executions: { expected: 0, succeeded: 0, failed: 0 },
    });
    const safetyAcknowledgement = {
      mode: 'operator_acknowledged',
      props_removed: true,
      airframe_secured: true,
      area_clear: true,
    };

    await submitCommandWithLifecycleFeedback({
      mission_type: 100,
      trigger_time: 0,
      target_drone_ids: ['1'],
      ground_test_safety: safetyAcknowledgement,
      uiMeta: {
        operatorLabel: 'Arm/Disarm Ground Test',
        confirmationMessage: 'frontend-only',
      },
    });

    expect(sendDroneCommand).toHaveBeenCalledWith({
      mission_type: 100,
      trigger_time: 0,
      target_drone_ids: ['1'],
      ground_test_safety: safetyAcknowledgement,
      uiMeta: {
        operatorLabel: 'Arm/Disarm Ground Test',
        confirmationMessage: 'frontend-only',
      },
    });
  });

  it('tracks a recovered command that is still preparing without claiming acceptance', async () => {
    sendDroneCommand.mockResolvedValue(commandReceipt({
      command_id: 'cmd-preparing',
      target_drones: ['1', '2'],
      replayed: true,
    }));
    getCommandStatus.mockResolvedValue({
      phase: 'terminal',
      outcome: 'failed',
      error_summary: 'Drone 2 battery reserve is below policy',
      progress: {
        stage: 'failed',
        message: 'Launch was not dispatched under all-required policy: 1 not ready',
      },
      preparations: { expected: 2, ready: 1, blocked: 1, unavailable: 0 },
      acks: { expected: 2, received: 0, accepted: 0, offline: 0, rejected: 0, errors: 0 },
      executions: { expected: 0, succeeded: 0, failed: 0 },
    });

    await submitCommandWithLifecycleFeedback({
      mission_type: 10,
      trigger_time: 0,
      target_scope: 'all',
      uiMeta: { operatorLabel: 'Take Off' },
    });
    await flushMicrotasks();

    expect(toast.info).toHaveBeenCalledWith(
      'Take Off accepted for tracking for 2 target drones. Monitoring preparation, dispatch, and execution now.'
    );
    expect(getCommandStatus).toHaveBeenCalledWith('cmd-preparing');
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('emits progress toasts when a command moves from active execution into final completion', async () => {
    sendDroneCommand.mockResolvedValue(commandReceipt({
      command_id: 'cmd-123',
      mission_type: 4,
      mission_name: 'SWARM_TRAJECTORY',
      target_drones: ['1', '2', '3'],
    }));

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
        mission_type: 4,
        trigger_time: 0,
        target_scope: 'all',
        uiMeta: { operatorLabel: 'Swarm Trajectory' },
      },
      { trackTimeoutMs: 10000 },
    );

    expect(response.accepted_for_tracking).toBe(true);

    await flushMicrotasks();

    expect(toast.info.mock.calls.map(([message]) => message)).toContain(
      'Swarm Trajectory accepted for tracking for 3 target drones. Monitoring preparation, dispatch, and execution now.',
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

  it('keeps the submission receipt unclassified while acknowledgments are still arriving', async () => {
    sendDroneCommand.mockResolvedValue(commandReceipt({
      command_id: 'cmd-partial-acks',
      target_drones: ['1', '2', '3', '4', '5'],
    }));

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
        mission_type: 10,
        trigger_time: 0,
        target_scope: 'all',
        uiMeta: { operatorLabel: 'Take Off' },
      },
      { trackTimeoutMs: 10000 },
    );

    await flushMicrotasks();

    expect(toast.info.mock.calls.map(([message]) => message)).toContain(
      'Take Off accepted for tracking for 5 target drones. Monitoring preparation, dispatch, and execution now.',
    );
  });

  it('replaces the bounded first-poll fallback with the authoritative tracker deadline', async () => {
    sendDroneCommand.mockResolvedValue(commandReceipt({
      command_id: 'cmd-456',
      mission_type: 104,
      mission_name: 'RETURN_RTL',
      target_drones: ['1', '2', '3'],
    }));
    const trackerDeadline = Date.now() + 2500;

    getCommandStatus.mockImplementation(async () => ({
      phase: 'in_progress',
      timeout_at: trackerDeadline,
      observed_at: Date.now(),
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
    }));

    await submitCommandWithLifecycleFeedback({
      mission_type: 104,
      trigger_time: 0,
      target_scope: 'all',
      uiMeta: { operatorLabel: 'Return RTL' },
    }, { trackTimeoutMs: 500 });

    await flushMicrotasks();
    await advanceLifecyclePoll(1500);
    await advanceLifecyclePoll(1500);

    expect(toast.warn).toHaveBeenCalledWith(
      'Return RTL: Tracking did not close before the timeout. The final execution outcome is not confirmed. The last known state remains visible.',
    );
  });

  it('reconciles late execution success after a delivery-unknown timeout without rewriting the timeout outcome', async () => {
    sendDroneCommand.mockResolvedValue(commandReceipt({
      command_id: 'cmd-late-success',
    }));
    const timedOutStatus = {
      command_id: 'cmd-late-success',
      phase: 'terminal',
      status: 'timeout',
      outcome: 'timeout',
      error_summary: 'Delivery remained unconfirmed before the tracker timeout.',
      progress: {
        stage: 'timeout',
        label: 'Tracking timed out',
        message: 'Delivery remained unconfirmed before the tracker timeout.',
      },
      acks: {
        expected: 1,
        received: 1,
        accepted: 0,
        offline: 0,
        rejected: 0,
        errors: 1,
        details: { '1': { delivery_state: 'delivery_unknown' } },
      },
      executions: { expected: 0, received: 0, succeeded: 0, failed: 0 },
      late_reports: {
        acks: { received: 0, details: {} },
        execution_starts: { received: 0, details: {} },
        executions: { received: 0, succeeded: 0, failed: 0, details: {} },
      },
      updated_at: 1000,
    };
    getCommandStatus
      .mockResolvedValueOnce(timedOutStatus)
      .mockResolvedValueOnce({
        ...timedOutStatus,
        late_reports: {
          acks: { received: 0, details: {} },
          execution_starts: { received: 1, details: { '1': 2000 } },
          executions: {
            received: 1,
            succeeded: 1,
            failed: 0,
            details: { '1': { success: true, timestamp: 2000 } },
          },
        },
        updated_at: 2000,
      });
    const onLateEvidence = jest.fn();
    const onSubmissionTracked = jest.fn();

    await submitCommandWithLifecycleFeedback(
      { mission_type: 10, trigger_time: 0, target_scope: 'all', uiMeta: { operatorLabel: 'Take Off' } },
      {
        onSubmissionTracked,
        onLateEvidence,
        lateReconciliationWindowMs: 5000,
        lateReconciliationPollIntervalMs: 1000,
      },
    );
    await flushMicrotasks();
    await advanceLifecyclePoll(1000);

    expect(onLateEvidence).toHaveBeenCalledWith(
      expect.objectContaining({
        outcome: 'timeout',
        isTerminal: true,
        lateEvidence: expect.objectContaining({
          result: 'succeeded',
          originalOutcome: 'timeout',
          succeeded: 1,
        }),
        progress: expect.objectContaining({
          stage: 'timeout',
          label: 'Late evidence: execution succeeded',
        }),
      }),
      expect.objectContaining({ outcome: 'timeout' }),
    );
    expect(toast.info).toHaveBeenCalledWith(
      'Take Off: 1 drone reported successful execution after tracking closed. The original tracker outcome remains timeout.',
    );
    expect(onSubmissionTracked).toHaveBeenCalledWith(
      expect.objectContaining({
        commandId: 'cmd-late-success',
        acks: expect.objectContaining({ accepted: 0 }),
      }),
      expect.objectContaining({ accepted_for_tracking: true }),
    );
    expect(Object.values(toast).flatMap((mock) => mock.mock.calls.flat()).join(' ')).not.toMatch(/drone(?:s)? accepted/i);
    expect(toast.success.mock.calls.flat().join(' ')).not.toMatch(/late evidence|late execution/i);
  });

  it('surfaces late execution failure while preserving the original timeout', async () => {
    sendDroneCommand.mockResolvedValue(commandReceipt({
      command_id: 'cmd-late-failure',
      mission_type: 102,
      mission_name: 'LAND',
    }));
    const timedOutStatus = {
      command_id: 'cmd-late-failure',
      phase: 'terminal',
      status: 'timeout',
      outcome: 'timeout',
      error_summary: 'Final landing result was not confirmed.',
      progress: {
        stage: 'timeout',
        label: 'Tracking timed out',
        message: 'Final landing result was not confirmed.',
      },
      acks: { expected: 1, received: 1, accepted: 1, offline: 0, rejected: 0, errors: 0 },
      executions: { expected: 1, received: 0, succeeded: 0, failed: 0 },
      late_reports: {
        acks: { received: 0, details: {} },
        execution_starts: { received: 0, details: {} },
        executions: { received: 0, succeeded: 0, failed: 0, details: {} },
      },
      updated_at: 1000,
    };
    getCommandStatus
      .mockResolvedValueOnce(timedOutStatus)
      .mockResolvedValueOnce({
        ...timedOutStatus,
        late_reports: {
          acks: { received: 0, details: {} },
          execution_starts: { received: 1, details: { '1': 2000 } },
          executions: {
            received: 1,
            succeeded: 0,
            failed: 1,
            details: { '1': { success: false, error: 'PX4 command denied', timestamp: 2000 } },
          },
        },
        updated_at: 2000,
      });
    const onLateEvidence = jest.fn();

    await submitCommandWithLifecycleFeedback(
      { mission_type: 102, trigger_time: 0, target_drone_ids: ['1'], uiMeta: { operatorLabel: 'Land' } },
      {
        onLateEvidence,
        lateReconciliationWindowMs: 5000,
        lateReconciliationPollIntervalMs: 1000,
      },
    );
    await flushMicrotasks();
    await advanceLifecyclePoll(1000);

    expect(toast.error).toHaveBeenCalledWith(
      'Land: 1 drone reported execution failure after tracking closed. The original tracker outcome remains timeout.',
    );
    expect(onLateEvidence).toHaveBeenCalledWith(
      expect.objectContaining({
        outcome: 'timeout',
        lateEvidence: expect.objectContaining({ result: 'failed', failed: 1 }),
        progress: expect.objectContaining({
          stage: 'timeout',
          label: 'Late evidence: execution failed',
        }),
      }),
      expect.objectContaining({ outcome: 'timeout' }),
    );
  });

  it('does not reconcile or continue polling a normally completed command', async () => {
    sendDroneCommand.mockResolvedValue(commandReceipt({
      command_id: 'cmd-normal-complete',
      mission_type: 102,
      mission_name: 'LAND',
    }));
    getCommandStatus.mockResolvedValue({
      command_id: 'cmd-normal-complete',
      phase: 'terminal',
      status: 'completed',
      outcome: 'completed',
      progress: { stage: 'completed', label: 'Completed', message: 'Landing completed.' },
      acks: { expected: 1, received: 1, accepted: 1, offline: 0, rejected: 0, errors: 0 },
      executions: { expected: 1, received: 1, succeeded: 1, failed: 0 },
      late_reports: {
        acks: { received: 0, details: {} },
        execution_starts: { received: 0, details: {} },
        executions: { received: 0, succeeded: 0, failed: 0, details: {} },
      },
    });

    await submitCommandWithLifecycleFeedback(
      { mission_type: 102, trigger_time: 0, target_drone_ids: ['1'], uiMeta: { operatorLabel: 'Land' } },
      {
        lateReconciliationWindowMs: 5000,
        lateReconciliationPollIntervalMs: 1000,
      },
    );
    await flushMicrotasks();
    await advanceLifecyclePoll(10000);

    expect(getCommandStatus).toHaveBeenCalledTimes(1);
  });

  it('stops timeout reconciliation at the configured bound when no late evidence arrives', async () => {
    sendDroneCommand.mockResolvedValue(commandReceipt({
      command_id: 'cmd-timeout-no-late-report',
      mission_type: 104,
      mission_name: 'RETURN_RTL',
    }));
    getCommandStatus.mockResolvedValue({
      command_id: 'cmd-timeout-no-late-report',
      phase: 'terminal',
      status: 'timeout',
      outcome: 'timeout',
      error_summary: 'Final RTL result was not confirmed.',
      progress: { stage: 'timeout', label: 'Tracking timed out', message: 'Final RTL result was not confirmed.' },
      acks: { expected: 1, received: 1, accepted: 1, offline: 0, rejected: 0, errors: 0 },
      executions: { expected: 1, received: 0, succeeded: 0, failed: 0 },
      late_reports: {
        acks: { received: 0, details: {} },
        execution_starts: { received: 0, details: {} },
        executions: { received: 0, succeeded: 0, failed: 0, details: {} },
      },
    });
    const onLateEvidence = jest.fn();

    await submitCommandWithLifecycleFeedback(
      { mission_type: 104, trigger_time: 0, target_drone_ids: ['1'], uiMeta: { operatorLabel: 'Return RTL' } },
      {
        onLateEvidence,
        lateReconciliationWindowMs: 2500,
        lateReconciliationPollIntervalMs: 1000,
      },
    );
    await flushMicrotasks();
    await advanceLifecyclePoll(1000);
    await advanceLifecyclePoll(1000);
    await advanceLifecyclePoll(500);

    expect(getCommandStatus).toHaveBeenCalledTimes(4);
    expect(onLateEvidence).not.toHaveBeenCalled();

    await advanceLifecyclePoll(10000);

    expect(getCommandStatus).toHaveBeenCalledTimes(4);
  });

  it('fetches tracker terminal details without treating the receipt as outcome evidence', async () => {
    sendDroneCommand.mockResolvedValue(commandReceipt({
      command_id: 'cmd-preflight-failed',
      target_drones: ['1', '2'],
    }));
    getCommandStatus.mockResolvedValue({
      command_id: 'cmd-preflight-failed',
      phase: 'terminal',
      outcome: 'failed',
      error_summary: 'Drone 2 battery reserve is below policy.',
      progress: { stage: 'failed', message: 'No launch command was dispatched.' },
      acks: { expected: 2, received: 0, accepted: 0, offline: 0, rejected: 0, errors: 0 },
      executions: { expected: 0, succeeded: 0, failed: 0 },
    });
    const onTrackingComplete = jest.fn();

    await submitCommandWithLifecycleFeedback(
      { mission_type: 10, trigger_time: 0, target_scope: 'all', uiMeta: { operatorLabel: 'Take Off' } },
      { onTrackingComplete },
    );
    await flushMicrotasks();

    expect(getCommandStatus).toHaveBeenCalledWith('cmd-preflight-failed');
    expect(toast.error).toHaveBeenCalledWith('Drone 2 battery reserve is below policy.');
    expect(onTrackingComplete).toHaveBeenCalledWith(
      expect.objectContaining({ commandId: 'cmd-preflight-failed', isTerminal: true }),
      expect.objectContaining({ outcome: 'failed' }),
    );
  });

  it('does not claim acceptance when preparation tracking becomes unavailable', async () => {
    sendDroneCommand.mockResolvedValue(commandReceipt({
      command_id: 'cmd-preparing-unavailable',
    }));
    getCommandStatus.mockRejectedValue(new Error('network'));

    await submitCommandWithLifecycleFeedback(
      { mission_type: 10, trigger_time: 0, target_drone_ids: ['1'], uiMeta: { operatorLabel: 'Take Off' } },
      { trackTimeoutMs: 10000 },
    );
    await flushMicrotasks();
    await advanceLifecyclePoll();
    await advanceLifecyclePoll();
    await advanceLifecyclePoll();

    expect(toast.warn).toHaveBeenCalledWith(
      'Take Off: Live tracking updates are currently unavailable. Launch readiness, command delivery, and execution are not confirmed. The last known state remains visible.',
    );
    expect(toast.warn.mock.calls.flat().join(' ')).not.toMatch(/drone(?:s)? accepted/i);
  });

  it('does not infer scheduled or accepted state from receipt timing metadata', async () => {
    jest.setSystemTime(new Date('2026-04-01T12:00:10Z'));
    sendDroneCommand.mockResolvedValue(commandReceipt({
      command_id: 'cmd-server-time',
      mission_type: 4,
      mission_name: 'SWARM_TRAJECTORY',
      timestamp: Date.parse('2026-04-01T12:00:00Z'),
    }));
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

    const onSubmissionTracked = jest.fn();

    await submitCommandWithLifecycleFeedback(
      {
        mission_type: 4,
        trigger_time: Math.floor(Date.parse('2026-04-01T12:00:05Z') / 1000),
        target_drone_ids: ['1'],
        uiMeta: { operatorLabel: 'Swarm Trajectory' },
      },
      {
        onSubmissionTracked,
        trackTimeoutMs: 10000,
      },
    );

    expect(onSubmissionTracked).toHaveBeenCalledWith(
      expect.objectContaining({
        progress: expect.objectContaining({
          stage: 'preparing',
          message: expect.stringMatching(/tracked preparation/i),
        }),
        acks: expect.objectContaining({ accepted: 0, received: 0 }),
      }),
      expect.any(Object),
    );
  });

  it('emits lifecycle callbacks for submission, status updates, and terminal completion', async () => {
    sendDroneCommand.mockResolvedValue(commandReceipt({
      command_id: 'cmd-789',
      mission_type: 4,
      mission_name: 'SWARM_TRAJECTORY',
      target_drones: ['1', '2'],
    }));

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

    const onSubmissionTracked = jest.fn();
    const onStatusUpdate = jest.fn();
    const onTrackingComplete = jest.fn();

    await submitCommandWithLifecycleFeedback(
      {
        mission_type: 4,
        trigger_time: 0,
        target_drone_ids: ['1', '2'],
        uiMeta: {
          operatorLabel: 'Swarm Trajectory',
          targetLabel: '2 selected drones',
          targetDescriptor: 'Selected drones: 1, 2',
        },
      },
      {
        trackTimeoutMs: 10000,
        onSubmissionTracked,
        onStatusUpdate,
        onTrackingComplete,
      },
    );

    await flushMicrotasks();
    await advanceLifecyclePoll(1500);
    await advanceLifecyclePoll(1500);

    expect(onSubmissionTracked).toHaveBeenCalledWith(
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
    sendDroneCommand.mockResolvedValue(commandReceipt({
      command_id: 'cmd-999',
      mission_type: 4,
      mission_name: 'SWARM_TRAJECTORY',
      target_drones: ['1', '2'],
    }));

    getCommandStatus.mockRejectedValue(new Error('network'));

    const onTrackingUnavailable = jest.fn();

    await submitCommandWithLifecycleFeedback(
      {
        mission_type: 4,
        target_drone_ids: ['1', '2'],
        trigger_time: 0,
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
