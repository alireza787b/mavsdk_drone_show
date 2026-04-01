import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';

import { CommandActivityProvider, useCommandActivity } from './CommandActivityContext';
import { getActiveCommands, getRecentCommands } from '../services/droneApiService';
import { buildLifecycleSnapshotFromStatus } from '../utilities/commandLifecycleFeedback';

jest.mock('../services/droneApiService', () => ({
  getActiveCommands: jest.fn(),
  getRecentCommands: jest.fn(),
}));

jest.mock('../utilities/commandLifecycleFeedback', () => ({
  buildLifecycleSnapshotFromStatus: jest.fn(),
}));

function MonitorProbe() {
  const { commandMonitors } = useCommandActivity();

  return (
    <div>
      {commandMonitors.map((monitor) => (
        <div key={monitor.commandId}>
          <span>{monitor.commandLabel}</span>
          <span>{monitor.phase}</span>
        </div>
      ))}
    </div>
  );
}

describe('CommandActivityContext', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
    buildLifecycleSnapshotFromStatus.mockImplementation((status) => ({
      commandId: status.command_id,
      commandLabel: status.mission_name,
      missionType: status.mission_type,
      targetDrones: status.target_drones || [],
      phase: status.phase,
      outcome: status.outcome,
      isTerminal: status.phase === 'terminal',
      trackingIssue: null,
      progress: status.progress || null,
      acks: status.acks || null,
      executions: status.executions || null,
      updatedAtMs: status.updated_at || 0,
    }));
  });

  afterEach(() => {
    jest.clearAllTimers();
    jest.useRealTimers();
  });

  it('discovers active commands started from another client during refresh polling', async () => {
    getActiveCommands
      .mockResolvedValueOnce({ commands: [] })
      .mockResolvedValueOnce({
        commands: [
          {
            command_id: 'cmd-remote-active',
            mission_name: 'Swarm Trajectory',
            mission_type: 4,
            target_drones: ['1', '2'],
            phase: 'in_progress',
            updated_at: 2000,
          },
        ],
      })
      .mockResolvedValue({ commands: [] });
    getRecentCommands.mockResolvedValue({ commands: [] });

    render(
      <CommandActivityProvider>
        <MonitorProbe />
      </CommandActivityProvider>,
    );

    await waitFor(() => {
      expect(getActiveCommands).toHaveBeenCalledTimes(1);
      expect(getRecentCommands).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      jest.advanceTimersByTime(2000);
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByText('Swarm Trajectory')).toBeInTheDocument();
      expect(screen.getByText('in_progress')).toBeInTheDocument();
    });
  });

  it('refreshes recent history when a tracked active command disappears from the active poll', async () => {
    getActiveCommands
      .mockResolvedValueOnce({
        commands: [
          {
            command_id: 'cmd-finish',
            mission_name: 'Drone Show from CSV',
            mission_type: 1,
            target_drones: ['1'],
            phase: 'in_progress',
            updated_at: 1000,
          },
        ],
      })
      .mockResolvedValueOnce({ commands: [] })
      .mockResolvedValue({ commands: [] });
    getRecentCommands
      .mockResolvedValueOnce({ commands: [] })
      .mockResolvedValueOnce({
        commands: [
          {
            command_id: 'cmd-finish',
            mission_name: 'Drone Show from CSV',
            mission_type: 1,
            target_drones: ['1'],
            phase: 'terminal',
            outcome: 'completed',
            updated_at: 3000,
          },
        ],
      })
      .mockResolvedValue({ commands: [] });

    render(
      <CommandActivityProvider>
        <MonitorProbe />
      </CommandActivityProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('Drone Show from CSV')).toBeInTheDocument();
      expect(screen.getByText('in_progress')).toBeInTheDocument();
    });

    await act(async () => {
      jest.advanceTimersByTime(2000);
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(getRecentCommands).toHaveBeenCalledTimes(2);
      expect(screen.getByText('terminal')).toBeInTheDocument();
    });
  });
});
