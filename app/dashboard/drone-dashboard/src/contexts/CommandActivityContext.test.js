import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';

import { CommandActivityProvider, useCommandActivity } from './CommandActivityContext';
import { getActiveCommands, getRecentCommands } from '../services/droneApiService';
import { buildLifecycleSnapshotFromStatus } from '../utilities/commandLifecycleFeedback';

jest.mock('../services/droneApiService', () => ({
  getActiveCommands: jest.fn(),
  getRecentCommands: jest.fn(),
}));

function MonitorProbe() {
  const {
    commandMonitors,
    dismissCommandMonitor,
    primaryMonitor,
    recentCommandMonitors,
  } = useCommandActivity();

  return (
    <div>
      <div data-testid="primary-command">
        {primaryMonitor?.commandId || 'none'}
      </div>
      <div data-testid="recent-commands">
        {recentCommandMonitors.map((monitor) => monitor.commandId).join(',') || 'none'}
      </div>
      {commandMonitors.map((monitor) => (
        <div key={monitor.commandId}>
          <span>{monitor.commandLabel}</span>
          <span>{monitor.phase}</span>
          <span>{monitor.missionType}</span>
          <button
            type="button"
            onClick={() => dismissCommandMonitor(monitor.commandId)}
          >
            Dismiss {monitor.commandId}
          </button>
        </div>
      ))}
    </div>
  );
}

describe('CommandActivityContext', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.resetAllMocks();
  });

  afterEach(() => {
    jest.clearAllTimers();
    jest.useRealTimers();
  });

  it('builds recovered status snapshots with canonical mission identity', () => {
    expect(buildLifecycleSnapshotFromStatus({
      command_id: 'cmd-recovered',
      mission_name: 'TAKE_OFF',
      mission_type: 10,
      target_drones: ['1'],
      phase: 'terminal',
      outcome: 'failed',
      updated_at: 4000,
    })).toEqual(expect.objectContaining({
      commandId: 'cmd-recovered',
      missionType: 10,
      isTerminal: true,
    }));
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
      expect(screen.getByText('Drone Show From CSV')).toBeInTheDocument();
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

  it('keeps terminal history out of the primary monitor while retaining typed mission identity', async () => {
    getActiveCommands.mockResolvedValue({ commands: [] });
    getRecentCommands.mockResolvedValue({
      commands: [
        {
          command_id: 'cmd-failed-history',
          mission_name: 'TAKE_OFF',
          mission_type: 10,
          target_drones: ['1'],
          phase: 'terminal',
          outcome: 'failed',
          updated_at: 4000,
        },
      ],
    });

    render(
      <CommandActivityProvider>
        <MonitorProbe />
      </CommandActivityProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('Take Off')).toBeInTheDocument();
      expect(screen.getByText('10')).toBeInTheDocument();
    });
    expect(screen.getByTestId('primary-command')).toHaveTextContent('none');
    expect(screen.getByTestId('recent-commands')).toHaveTextContent('cmd-failed-history');
  });

  it('does not re-add dismissed terminal history during periodic recent polling', async () => {
    const terminalStatus = {
      command_id: 'cmd-dismissed-failure',
      mission_name: 'LAND',
      mission_type: 102,
      target_drones: ['1'],
      phase: 'terminal',
      outcome: 'failed',
      updated_at: 5000,
    };
    getActiveCommands.mockResolvedValue({ commands: [] });
    getRecentCommands.mockResolvedValue({ commands: [terminalStatus] });

    render(
      <CommandActivityProvider>
        <MonitorProbe />
      </CommandActivityProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('Land')).toBeInTheDocument();
    });

    act(() => {
      screen.getByRole('button', { name: 'Dismiss cmd-dismissed-failure' }).click();
    });
    expect(screen.queryByText('Land')).not.toBeInTheDocument();

    await act(async () => {
      jest.advanceTimersByTime(15000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(getRecentCommands.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('Land')).not.toBeInTheDocument();
    expect(screen.getByTestId('primary-command')).toHaveTextContent('none');
  });
});
