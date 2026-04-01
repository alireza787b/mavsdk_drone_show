import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import SwarmRuntimeControls from './SwarmRuntimeControls';
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
    error: jest.fn(),
  },
}));

function MonitorProbe() {
  const { primaryMonitor } = useCommandActivity();
  return <div>{primaryMonitor ? `Monitor: ${primaryMonitor.commandLabel}` : 'Monitor: none'}</div>;
}

const leaderDrone = {
  hw_id: '1',
  title: 'Leader 1',
  clusterId: 'cluster-1',
  role: 'topLeader',
  warnings: [],
  hasBlockingWarnings: false,
  follow: '0',
  frame: 'ned',
};

const viewModel = {
  drones: [leaderDrone],
  dronesById: {
    '1': leaderDrone,
  },
  clusters: [
    {
      id: 'cluster-1',
      type: 'cluster',
      title: 'Cluster 1',
      subtitle: '1 target drone',
      leaderId: '1',
      drones: [leaderDrone],
    },
  ],
};

describe('SwarmRuntimeControls', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getActiveCommands.mockResolvedValue({ commands: [] });
    getRecentCommands.mockResolvedValue({ commands: [] });
    window.confirm = jest.fn(() => true);
  });

  it('publishes Smart Swarm runtime commands into the shared command activity stream', async () => {
    submitCommandWithLifecycleFeedback.mockImplementation(async (_commandData, options = {}) => {
      options.onCommandAccepted?.({
        commandId: 'cmd-smart-swarm-1',
        commandLabel: 'Start Smart Swarm',
        missionType: 2,
        targetDrones: ['1'],
        targetLabel: 'Leader 1 (1 drone)',
        targetDescriptor: 'Targets only the selected drone. Other swarm drones continue until they receive their own command, failover event, or follow-chain update.',
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
        canCancelMission: true,
        updatedAtMs: 1000,
      });

      return { success: true, command_id: 'cmd-smart-swarm-1' };
    });

    render(
      <CommandActivityProvider>
        <SwarmRuntimeControls
          viewModel={viewModel}
          selectedDroneId="1"
          dirtyIds={[]}
          pendingSyncIds={[]}
          telemetryById={{}}
        />
        <MonitorProbe />
      </CommandActivityProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: /start smart swarm/i }));

    await waitFor(() => {
      expect(screen.getByText('Monitor: Start Smart Swarm')).toBeInTheDocument();
    });
  });
});
