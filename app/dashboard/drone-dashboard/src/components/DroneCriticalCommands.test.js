import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import DroneCriticalCommands from './DroneCriticalCommands';
import { CommandActivityProvider, useCommandActivity } from '../contexts/CommandActivityContext';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
import { getActiveCommands, getRecentCommands } from '../services/droneApiService';
import { getPrecisionMovePolicyResponse } from '../services/gcsApiService';

jest.mock('../utilities/commandLifecycleFeedback', () => ({
  submitCommandWithLifecycleFeedback: jest.fn(),
}));

jest.mock('../services/droneApiService', () => {
  const actual = jest.requireActual('../services/droneApiService');
  return {
    ...actual,
    getActiveCommands: jest.fn(),
    getRecentCommands: jest.fn(),
  };
});

jest.mock('../services/gcsApiService', () => ({
  ...jest.requireActual('../services/gcsApiService'),
  getPrecisionMovePolicyResponse: jest.fn(),
}));

jest.mock('react-toastify', () => ({
  toast: {
    info: jest.fn(),
    error: jest.fn(),
  },
}));

function MonitorProbe() {
  const { primaryMonitor } = useCommandActivity();
  return <div>{primaryMonitor ? `Monitor: ${primaryMonitor.commandLabel}` : 'Monitor: none'}</div>;
}

describe('DroneCriticalCommands', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getActiveCommands.mockResolvedValue({ commands: [] });
    getRecentCommands.mockResolvedValue({ commands: [] });
    getPrecisionMovePolicyResponse.mockResolvedValue({
      data: {
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
  });

  it('publishes per-drone overrides into the shared command activity stream', async () => {
    submitCommandWithLifecycleFeedback.mockImplementation(async (_commandData, options = {}) => {
      options.onCommandAccepted?.({
        commandId: 'cmd-hold-1',
        commandLabel: 'Hold',
        missionType: 102,
        targetDrones: ['1'],
        targetLabel: 'Drone 1',
        targetDescriptor: 'Per-drone override: drone 1',
        phase: 'pending_execution',
        outcome: null,
        isTerminal: false,
        trackingIssue: null,
        progress: {
          stage: 'pending_execution',
          label: 'Accepted, waiting for execution start',
          message: '1/1 targeted drone(s) accepted the command. Waiting for execution start reports from 1 drone(s).',
          ackPending: 0,
          active: 0,
          completed: 0,
          remaining: 1,
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
          succeeded: 0,
          failed: 0,
        },
        triggerTime: 0,
        canCancelMission: false,
        updatedAtMs: 1000,
      });

      return { success: true, command_id: 'cmd-hold-1' };
    });

    render(
      <CommandActivityProvider>
        <DroneCriticalCommands
          droneId="1"
          isArmed
          runtimeStatus={{ level: 'online', label: 'Live', tooltip: 'Telemetry fresh' }}
        />
        <MonitorProbe />
      </CommandActivityProvider>
    );

    fireEvent.click(screen.getAllByRole('button', { name: 'Hold' })[0]);

    await waitFor(() => {
      expect(screen.getByText('Confirm Action')).toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByRole('button', { name: 'Hold' })[1]);

    await waitFor(() => {
      expect(screen.getByText('Monitor: Hold')).toBeInTheDocument();
    });
  });

  it('keeps a stable action strip when grounded and only enables Take Off', () => {
    render(
      <CommandActivityProvider>
        <DroneCriticalCommands
          droneId="1"
          isArmed={false}
          runtimeStatus={{ level: 'online', label: 'Live', tooltip: 'Telemetry fresh' }}
        />
      </CommandActivityProvider>
    );

    expect(screen.getByRole('button', { name: 'Take Off' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Hold' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'RTL' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Kill' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Land' })).not.toBeInTheDocument();
  });

  it('opens per-drone jog and exposes cancel mission when a mission is active', async () => {
    render(
      <CommandActivityProvider>
        <DroneCriticalCommands
          droneId="1"
          isArmed
          canCancelMission
          currentMissionLabel="Smart Swarm"
          targetLabel="P1|H1"
          targetDescriptor="Per-drone override · P1|H1"
          runtimeStatus={{ level: 'online', label: 'Live', tooltip: 'Telemetry fresh' }}
        />
      </CommandActivityProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: 'Jog' }));

    expect(await screen.findByRole('dialog', { name: /precision move/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /close precision move dialog/i }));

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(await screen.findByText('Confirm Action')).toBeInTheDocument();
    expect(screen.getByText(/Cancel Smart Swarm for this drone/i)).toBeInTheDocument();
  });
});
