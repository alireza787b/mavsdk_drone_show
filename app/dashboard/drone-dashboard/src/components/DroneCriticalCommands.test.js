import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import DroneCriticalCommands from './DroneCriticalCommands';
import { CommandActivityProvider, useCommandActivity } from '../contexts/CommandActivityContext';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
import { getActiveCommands, getRecentCommands } from '../services/droneApiService';

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
});
