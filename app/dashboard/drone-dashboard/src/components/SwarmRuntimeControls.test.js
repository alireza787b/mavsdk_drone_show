import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

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

const followerDrone = {
  hw_id: '2',
  title: 'Follower 2',
  clusterId: 'cluster-1',
  role: 'follower',
  warnings: [],
  hasBlockingWarnings: false,
  follow: '1',
  frame: 'ned',
  offsetSummary: 'North +6.0 m',
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

const twoDroneViewModel = {
  drones: [leaderDrone, followerDrone],
  dronesById: { '1': leaderDrone, '2': followerDrone },
  clusters: [{
    id: 'cluster-1',
    type: 'cluster',
    title: 'Cluster 1',
    subtitle: 'Leader and follower',
    leaderId: '1',
    drones: [leaderDrone, followerDrone],
  }],
};

function buildAirborneTelemetry() {
  const nowMs = Date.now();
  return {
    '1': {
      hw_id: '1',
      timestamp: nowMs,
      heartbeat_last_seen: nowMs,
      is_armed: true,
      is_ready_to_arm: true,
      readiness_status: 'ready',
      relative_altitude_m: 5,
      altitude_report: {
        source: 'relative_home',
        display_m: 5,
        relative_home_m: 5,
        stale: false,
      },
    },
  };
}

describe('SwarmRuntimeControls', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getActiveCommands.mockResolvedValue({ commands: [] });
    getRecentCommands.mockResolvedValue({ commands: [] });
  });

  it('publishes Smart Swarm runtime commands into the shared command activity stream', async () => {
    submitCommandWithLifecycleFeedback.mockImplementation(async (_commandData, options = {}) => {
      options.onSubmissionTracked?.({
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

      return { accepted_for_tracking: true, command_id: 'cmd-smart-swarm-1' };
    });

    render(
      <CommandActivityProvider>
        <SwarmRuntimeControls
          viewModel={viewModel}
          selectedDroneId="1"
          dirtyIds={[]}
          pendingSyncIds={[]}
          telemetryById={buildAirborneTelemetry()}
        />
        <MonitorProbe />
      </CommandActivityProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: /start smart swarm/i }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /start smart swarm/i }));

    await waitFor(() => {
      expect(screen.getByText('Monitor: Start Smart Swarm')).toBeInTheDocument();
    });
  });

  it('defaults to one drone and requires an explicit cluster choice for both-drone RTL', async () => {
    submitCommandWithLifecycleFeedback.mockResolvedValue({ accepted_for_tracking: true, command_id: 'rtl-1' });
    render(
      <CommandActivityProvider>
        <SwarmRuntimeControls viewModel={twoDroneViewModel} selectedDroneId="1" selectedClusterId="cluster-1" />
      </CommandActivityProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: /rtl swarm/i }));
    expect(within(screen.getByRole('dialog')).getByText(/1 target drone: Leader 1/)).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /cancel/i }));

    fireEvent.click(screen.getByRole('button', { name: /use selected cluster runtime scope/i }));
    fireEvent.click(screen.getByRole('button', { name: /rtl swarm/i }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(/2 target drones: Leader 1/)).toHaveTextContent('Follower 2 (Drone 2)');
    expect(within(dialog).getByText(/do not return as a coordinated formation/i)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: /rtl swarm/i }));

    await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith(
      expect.objectContaining({ mission_type: 104, target_drone_ids: ['1', '2'] }),
      expect.any(Object)
    ));
  });

  it('refuses to dispatch when confirmed targets change after the review opened', async () => {
    submitCommandWithLifecycleFeedback.mockResolvedValue({ accepted_for_tracking: true, command_id: 'rtl-2' });
    const { rerender } = render(
      <CommandActivityProvider>
        <SwarmRuntimeControls viewModel={twoDroneViewModel} selectedDroneId="1" selectedClusterId="cluster-1" />
      </CommandActivityProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: /rtl swarm/i }));
    rerender(
      <CommandActivityProvider>
        <SwarmRuntimeControls viewModel={twoDroneViewModel} selectedDroneId="2" selectedClusterId="cluster-1" />
      </CommandActivityProvider>
    );
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /rtl swarm/i }));

    expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  });

  it.each([
    ['Stop Swarm (Hold)', 102, /must be airborne/i],
    ['Land Swarm', 101, /land at its current position/i],
  ])('confirms and dispatches %s to the exact selected cluster', async (label, missionType, explanation) => {
    submitCommandWithLifecycleFeedback.mockResolvedValue({ accepted_for_tracking: true, command_id: 'recovery-1' });
    const onReviewSelection = jest.fn();
    const onOpenMissionConfig = jest.fn();
    render(
      <CommandActivityProvider>
        <SwarmRuntimeControls
          viewModel={twoDroneViewModel}
          selectedDroneId="1"
          selectedClusterId="cluster-1"
          onReviewSelection={onReviewSelection}
          onOpenMissionConfig={onOpenMissionConfig}
        />
      </CommandActivityProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: /use selected cluster runtime scope/i }));
    fireEvent.click(screen.getByRole('button', { name: /review leader/i }));
    fireEvent.click(screen.getByRole('button', { name: /mission config \(leader\)/i }));
    expect(onReviewSelection).toHaveBeenCalledWith('1');
    expect(onOpenMissionConfig).toHaveBeenCalledWith('1');

    const actionName = new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
    fireEvent.click(screen.getByRole('button', { name: actionName }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(explanation)).toBeInTheDocument();
    expect(within(dialog).getByText(/2 target drones: Leader 1/)).toHaveTextContent('Follower 2 (Drone 2)');
    fireEvent.click(within(dialog).getByRole('button', { name: actionName }));

    await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith(
      expect.objectContaining({ mission_type: missionType, target_drone_ids: ['1', '2'] }),
      expect.any(Object)
    ));
  });
});
