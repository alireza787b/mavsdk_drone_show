import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import CommandSender from './CommandSender';
import { CommandActivityProvider } from '../contexts/CommandActivityContext';
import {
  buildLifecycleSnapshotFromStatus,
  submitCommandWithLifecycleFeedback,
} from '../utilities/commandLifecycleFeedback';
import { getPrecisionMovePolicyResponse } from '../services/gcsApiService';
import { getActiveCommands, getRecentCommands } from '../services/droneApiService';

jest.mock('../utilities/commandLifecycleFeedback', () => ({
  buildLifecycleSnapshotFromStatus: jest.fn(),
  submitCommandWithLifecycleFeedback: jest.fn(),
}));

jest.mock('../services/droneApiService', () => ({
  getActiveCommands: jest.fn(),
  getRecentCommands: jest.fn(),
}));

jest.mock('../services/gcsApiService', () => ({
  ...jest.requireActual('../services/gcsApiService'),
  getPrecisionMovePolicyResponse: jest.fn(),
}));

jest.mock('./MissionTrigger', () => (props) => (
  <button
    type="button"
    onClick={() => props.onSendCommand({
      missionType: '4',
      triggerTime: '1761955200',
      target_drones: ['1', '2'],
      uiMeta: {
        triggerSummary: 'Executes at 2025-11-01 00:00:00 UTC',
        details: [
          { label: 'Schedule', value: 'UTC synchronized trigger' },
        ],
      },
    })}
  >
    Mock Send Mission
  </button>
));

jest.mock('./DroneActions', () => (props) => (
  <div>
    <button type="button" onClick={() => props.onRequestPrecisionMove?.()}>
      Mock Precision Move
    </button>
    <div>Mock Actions</div>
  </div>
));
jest.mock('./CommandPreflightSummary', () => () => <div>Mock Preflight</div>);

const drones = [
  { hw_id: '1', update_time: Date.now() },
  { hw_id: '2', update_time: Date.now() },
  { hw_id: '3', update_time: Date.now() },
];

const renderWithCommandActivity = (ui) => render(
  <CommandActivityProvider>
    {ui}
  </CommandActivityProvider>
);

const openCommandControl = () => {
  fireEvent.click(screen.getByRole('button', { name: /show dispatch setup/i }));
};

describe('CommandSender', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getActiveCommands.mockResolvedValue({ commands: [] });
    getRecentCommands.mockResolvedValue({ commands: [] });
    getPrecisionMovePolicyResponse.mockResolvedValue({
      data: {
        action: 'precision_move',
        defaults: {
          speed_m_s: 1,
          position_tolerance_m: 0.15,
          yaw_tolerance_deg: 5,
          settle_time_sec: 1,
          timeout_sec: 30,
        },
        limits: {
          max_translation_m: 100,
          max_speed_m_s: 5,
          min_position_tolerance_m: 0.05,
          max_timeout_sec: 180,
          min_airborne_altitude_m: 0.3,
          control_rate_hz: 10,
        },
        execution: {
          supported_frames: ['body', 'ned'],
          supported_yaw_modes: ['hold_current', 'relative_delta', 'absolute_heading'],
          hold_mode: 'px4_hold',
          immediate_only: true,
          requires_airborne: true,
          requires_local_position: true,
        },
      },
    });
    buildLifecycleSnapshotFromStatus.mockImplementation((status) => ({
      commandId: status.command_id,
      commandLabel: status.mission_name,
      missionType: status.mission_type,
      targetDrones: status.target_drones || [],
      targetLabel: `${(status.target_drones || []).length} selected drones`,
      targetDescriptor: `Selected drones: ${(status.target_drones || []).join(', ')}`,
      phase: status.phase,
      outcome: status.outcome,
      isTerminal: status.phase === 'terminal',
      trackingIssue: null,
      progress: status.progress || {
        stage: 'pending_execution',
        label: 'Accepted, waiting for execution start',
        message: 'Waiting for execution start reports.',
        ackPending: 0,
        active: 0,
        completed: 0,
        remaining: 0,
      },
      acks: status.acks || {
        expected: 0,
        accepted: 0,
        offline: 0,
        rejected: 0,
        errors: 0,
      },
      executions: status.executions || {
        expected: 0,
        succeeded: 0,
        failed: 0,
      },
      triggerTime: 0,
      canCancelMission: Number(status.mission_type) > 0 && Number(status.mission_type) < 100,
      updatedAtMs: status.updated_at || 0,
    }));
  });

  it('renders a persistent command monitor after command acceptance', async () => {
    submitCommandWithLifecycleFeedback.mockImplementation(async (_commandData, options = {}) => {
      options.onCommandAccepted?.({
        commandId: 'cmd-1',
        commandLabel: 'Swarm Trajectory',
        missionType: 4,
        targetDrones: ['1', '2'],
        targetLabel: '2 selected drones',
        targetDescriptor: 'Selected drones: 1, 2',
        phase: 'pending_execution',
        outcome: null,
        isTerminal: false,
        trackingIssue: null,
        progress: {
          stage: 'scheduled',
          label: 'Scheduled, waiting for trigger time',
          message: '2/2 targeted drone(s) accepted the command. Waiting for the scheduled trigger time.',
          scheduledTriggerTime: 1761955200000,
          ackPending: 0,
          active: 0,
          completed: 0,
          remaining: 2,
        },
        acks: {
          expected: 2,
          accepted: 2,
          offline: 0,
          rejected: 0,
          errors: 0,
        },
        executions: {
          expected: 2,
          succeeded: 0,
          failed: 0,
        },
        triggerTime: 1761955200,
        canCancelMission: true,
      });

      return { success: true, command_id: 'cmd-1' };
    });

    renderWithCommandActivity(<CommandSender drones={drones} />);
    openCommandControl();

    fireEvent.click(screen.getByRole('button', { name: 'Mock Send Mission' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(screen.getByText('Live Command Monitor')).toBeInTheDocument();
    });

    const liveMonitor = screen.getByText('Live Command Monitor').closest('section');
    expect(screen.getByText('Swarm Trajectory')).toBeInTheDocument();
    expect(within(liveMonitor).getByText('Scheduled, waiting for trigger time')).toBeInTheDocument();
    expect(screen.getByText('Selected drones: 1, 2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel Before Trigger' })).toBeInTheDocument();
    expect(screen.getByText('Accepted')).toBeInTheDocument();
    expect(screen.getByText('2/2')).toBeInTheDocument();
  });

  it('submits precision move directly from the dedicated dialog without opening the generic confirm modal', async () => {
    submitCommandWithLifecycleFeedback.mockResolvedValue({ success: true, command_id: 'cmd-precision' });

    renderWithCommandActivity(<CommandSender drones={drones} />);
    openCommandControl();

    fireEvent.click(screen.getByRole('button', { name: 'Actions' }));
    fireEvent.click(screen.getByRole('button', { name: 'Mock Precision Move' }));
    await waitFor(() => expect(getPrecisionMovePolicyResponse).toHaveBeenCalled());

    expect(screen.getByRole('dialog', { name: /precision move/i })).toBeInTheDocument();
    expect(screen.queryByText('Confirm Command')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText(/manual values/i));
    fireEvent.change(screen.getByLabelText(/forward \(\+\) \/ back \(-\)/i), { target: { value: '1.5' } });
    fireEvent.change(screen.getByLabelText(/up \(\+\) \/ down \(-\)/i), { target: { value: '0.5' } });
    fireEvent.click(screen.getByRole('button', { name: /dispatch planned move/i }));

    await waitFor(() => {
      expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith(
        expect.objectContaining({
          missionType: '112',
          triggerTime: '0',
          precision_move: {
            frame: 'body',
            translation_m: {
              forward: 1.5,
              right: 0,
              up: 0.5,
            },
            yaw: {
              mode: 'hold_current',
            },
            hold_mode: 'px4_hold',
          },
          uiMeta: expect.objectContaining({
            operatorLabel: 'Precision Move',
            targetLabel: 'all 3 drones',
          }),
        }),
        expect.any(Object),
      );
    });

    expect(screen.queryByText('Confirm Command')).not.toBeInTheDocument();
  });

  it('keeps the precision move dialog open while dispatching live jog steps', async () => {
    submitCommandWithLifecycleFeedback.mockResolvedValue({ success: true, command_id: 'cmd-jog' });

    renderWithCommandActivity(<CommandSender drones={drones} />);
    openCommandControl();

    fireEvent.click(screen.getByRole('button', { name: 'Actions' }));
    fireEvent.click(screen.getByRole('button', { name: 'Mock Precision Move' }));
    await waitFor(() => expect(getPrecisionMovePolicyResponse).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: /live jog/i }));
    expect(screen.queryByRole('button', { name: /dispatch planned move/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /forward/i }));

    await waitFor(() => {
      expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith(
        expect.objectContaining({
          missionType: '112',
          triggerTime: '0',
          precision_move: {
            frame: 'body',
            translation_m: {
              forward: 1,
              right: 0,
              up: 0,
            },
            yaw: {
              mode: 'hold_current',
            },
            hold_mode: 'px4_hold',
          },
        }),
        expect.any(Object),
      );
    });

    expect(screen.getByRole('dialog', { name: /precision move/i })).toBeInTheDocument();
  });

  it('offers a direct hold override from the precision move dialog', async () => {
    submitCommandWithLifecycleFeedback.mockResolvedValue({ success: true, command_id: 'cmd-hold' });

    renderWithCommandActivity(<CommandSender drones={drones} />);
    openCommandControl();

    fireEvent.click(screen.getByRole('button', { name: 'Actions' }));
    fireEvent.click(screen.getByRole('button', { name: 'Mock Precision Move' }));
    await waitFor(() => expect(getPrecisionMovePolicyResponse).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: /dispatch hold/i }));

    await waitFor(() => {
      expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith(
        expect.objectContaining({
          missionType: '102',
          triggerTime: '0',
          uiMeta: expect.objectContaining({
            operatorLabel: 'Hold',
            targetLabel: 'all 3 drones',
          }),
        }),
        expect.any(Object),
      );
    });
  });

  it('shows the active manual scope without rendering a separate visible-card bridge inside dispatch setup', async () => {
    const ScopeHarness = () => {
      const [targetMode, setTargetMode] = React.useState('selected');
      const [selectedDrones, setSelectedDrones] = React.useState(['1', '3']);
      const [selectedClusterScope, setSelectedClusterScope] = React.useState('');

      return (
        <CommandActivityProvider>
          <CommandSender
            drones={drones}
            targetMode={targetMode}
            onTargetModeChange={setTargetMode}
            selectedDrones={selectedDrones}
            onSelectedDronesChange={setSelectedDrones}
            selectedClusterScope={selectedClusterScope}
            onSelectedClusterScopeChange={setSelectedClusterScope}
          />
        </CommandActivityProvider>
      );
    };

    render(<ScopeHarness />);
    openCommandControl();

    await waitFor(() => {
      expect(screen.getAllByText('2 selected drones').length).toBeGreaterThan(0);
    });

    expect(screen.getByText('Selected: 2')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /copy .* visible cards to scope/i })).not.toBeInTheDocument();
  });

  it('dispatches Cancel Mission to the same targets from the monitor', async () => {
    submitCommandWithLifecycleFeedback.mockImplementation(async (commandData, options = {}) => {
      if (commandData.missionType === '0') {
        options.onCommandAccepted?.({
          commandId: 'cmd-cancel',
          commandLabel: 'Cancel Mission',
          missionType: 0,
          targetDrones: ['1', '2'],
          targetLabel: '2 selected drones',
          targetDescriptor: 'Selected drones: 1, 2',
          phase: 'pending_execution',
          outcome: null,
          isTerminal: false,
          trackingIssue: null,
          progress: {
            stage: 'pending_execution',
            label: 'Accepted, waiting for execution start',
            message: '2/2 targeted drone(s) accepted the command. Waiting for execution start reports from 2 drone(s).',
            ackPending: 0,
            active: 0,
            completed: 0,
            remaining: 2,
          },
          acks: {
            expected: 2,
            accepted: 2,
            offline: 0,
            rejected: 0,
            errors: 0,
          },
          executions: {
            expected: 2,
            succeeded: 0,
            failed: 0,
          },
          triggerTime: 0,
          canCancelMission: false,
        });
      } else {
        options.onCommandAccepted?.({
          commandId: 'cmd-1',
          commandLabel: 'Swarm Trajectory',
          missionType: 4,
          targetDrones: ['1', '2'],
          targetLabel: '2 selected drones',
          targetDescriptor: 'Selected drones: 1, 2',
          phase: 'pending_execution',
          outcome: null,
          isTerminal: false,
          trackingIssue: null,
          progress: {
            stage: 'scheduled',
            label: 'Scheduled, waiting for trigger time',
            message: '2/2 targeted drone(s) accepted the command. Waiting for the scheduled trigger time.',
            scheduledTriggerTime: 1761955200000,
            ackPending: 0,
            active: 0,
            completed: 0,
            remaining: 2,
          },
          acks: {
            expected: 2,
            accepted: 2,
            offline: 0,
            rejected: 0,
            errors: 0,
          },
          executions: {
            expected: 2,
            succeeded: 0,
            failed: 0,
          },
          triggerTime: 1761955200,
          canCancelMission: true,
        });
      }

      return { success: true, command_id: commandData.missionType === '0' ? 'cmd-cancel' : 'cmd-1' };
    });

    renderWithCommandActivity(<CommandSender drones={drones} />);
    openCommandControl();

    fireEvent.click(screen.getByRole('button', { name: 'Mock Send Mission' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Cancel Before Trigger' })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Cancel Before Trigger' }));

    await waitFor(() => {
      expect(screen.getByText('Cancel Swarm Trajectory for 2 selected drones?')).toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByRole('button', { name: 'Yes' })[0]);

    await waitFor(() => {
      expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(2);
    });

    expect(submitCommandWithLifecycleFeedback.mock.calls[1][0]).toMatchObject({
      missionType: '0',
      target_drones: ['1', '2'],
      triggerTime: '0',
    });
  });

  it('keeps older command snapshots visible when a newer command is sent', async () => {
    let invocation = 0;

    submitCommandWithLifecycleFeedback.mockImplementation(async (_commandData, options = {}) => {
      invocation += 1;
      const snapshot = invocation === 1
        ? {
          commandId: 'cmd-1',
          commandLabel: 'Swarm Trajectory',
          missionType: 4,
          targetDrones: ['1', '2'],
          targetLabel: '2 selected drones',
          targetDescriptor: 'Selected drones: 1, 2',
          phase: 'pending_execution',
          outcome: null,
          isTerminal: false,
          trackingIssue: null,
          progress: {
            stage: 'scheduled',
            label: 'Scheduled, waiting for trigger time',
            message: '2/2 targeted drone(s) accepted the command. Waiting for the scheduled trigger time.',
            scheduledTriggerTime: 1761955200000,
            ackPending: 0,
            active: 0,
            completed: 0,
            remaining: 2,
          },
          acks: {
            expected: 2,
            accepted: 2,
            offline: 0,
            rejected: 0,
            errors: 0,
          },
          executions: {
            expected: 2,
            succeeded: 0,
            failed: 0,
          },
          triggerTime: 1761955200,
          canCancelMission: true,
          updatedAtMs: 1000,
        }
        : {
          commandId: 'cmd-2',
          commandLabel: 'Take Off',
          missionType: 10,
          targetDrones: ['1', '2'],
          targetLabel: '2 selected drones',
          targetDescriptor: 'Selected drones: 1, 2',
          phase: 'pending_execution',
          outcome: null,
          isTerminal: false,
          trackingIssue: null,
          progress: {
            stage: 'pending_execution',
            label: 'Accepted, waiting for execution start',
            message: '2/2 targeted drone(s) accepted the command. Waiting for execution start reports from 2 drone(s).',
            ackPending: 0,
            active: 0,
            completed: 0,
            remaining: 2,
          },
          acks: {
            expected: 2,
            accepted: 2,
            offline: 0,
            rejected: 0,
            errors: 0,
          },
          executions: {
            expected: 2,
            succeeded: 0,
            failed: 0,
          },
          triggerTime: 0,
          canCancelMission: true,
          updatedAtMs: 2000,
        };

      options.onCommandAccepted?.(snapshot);
      return { success: true, command_id: snapshot.commandId };
    });

    renderWithCommandActivity(<CommandSender drones={drones} />);
    openCommandControl();

    fireEvent.click(screen.getByRole('button', { name: 'Mock Send Mission' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(screen.getByText('Swarm Trajectory')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Mock Send Mission' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(screen.getByText(/recent commands/i)).toBeInTheDocument();
    });

    const liveMonitor = screen.getByText('Live Command Monitor').closest('section');
    expect(within(liveMonitor).getByText('Take Off')).toBeInTheDocument();

    const recentCommands = screen.getByLabelText(/recent commands/i);
    fireEvent.click(within(recentCommands).getByRole('button', { name: /show recent command history/i }));
    expect(within(recentCommands).getByText('Swarm Trajectory')).toBeInTheDocument();
  });

  it('rehydrates active and recent command monitors from backend command history', async () => {
    getActiveCommands.mockResolvedValue({
      commands: [
        {
          command_id: 'cmd-active',
          mission_name: 'Swarm Trajectory',
          mission_type: 4,
          target_drones: ['1', '2'],
          phase: 'in_progress',
          outcome: null,
          updated_at: 2000,
          progress: {
            stage: 'executing',
            label: 'Execution in progress',
            message: 'Execution is active on 2 drone(s).',
            ackPending: 0,
            active: 2,
            completed: 0,
            remaining: 2,
          },
          acks: {
            expected: 2,
            accepted: 2,
            offline: 0,
            rejected: 0,
            errors: 0,
          },
          executions: {
            expected: 2,
            succeeded: 0,
            failed: 0,
          },
        },
      ],
    });
    getRecentCommands.mockResolvedValue({
      commands: [
        {
          command_id: 'cmd-active',
          mission_name: 'Swarm Trajectory',
          mission_type: 4,
          target_drones: ['1', '2'],
          phase: 'in_progress',
          outcome: null,
          updated_at: 2000,
        },
        {
          command_id: 'cmd-recent',
          mission_name: 'Take Off',
          mission_type: 10,
          target_drones: ['1'],
          phase: 'terminal',
          outcome: 'completed',
          updated_at: 1000,
          progress: {
            stage: 'completed',
            label: 'Completed',
            message: 'Completed successfully on 1/1 accepted drone(s).',
            ackPending: 0,
            active: 0,
            completed: 1,
            remaining: 0,
          },
          acks: {
            expected: 1,
            accepted: 1,
            offline: 0,
            rejected: 0,
            errors: 0,
          },
          executions: {
            expected: 1,
            succeeded: 1,
            failed: 0,
          },
        },
      ],
    });

    renderWithCommandActivity(<CommandSender drones={drones} />);

    await waitFor(() => {
      expect(getActiveCommands).toHaveBeenCalledTimes(1);
      expect(getRecentCommands).toHaveBeenCalledWith({ limit: 8 });
    });

    openCommandControl();

    expect(await screen.findByText('Live Command Monitor')).toBeInTheDocument();
    expect(screen.getByText('Swarm Trajectory')).toBeInTheDocument();
    expect(within(screen.getByText('Live Command Monitor').closest('section')).getByText('Accepted, waiting for execution start')).toBeInTheDocument();

    const history = await screen.findByLabelText('Recent commands');
    fireEvent.click(within(history).getByRole('button', { name: /show recent command history/i }));
    expect(within(history).getByText('Take Off')).toBeInTheDocument();
    expect(buildLifecycleSnapshotFromStatus.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
