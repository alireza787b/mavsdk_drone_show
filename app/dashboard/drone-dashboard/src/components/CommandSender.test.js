import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import CommandSender from './CommandSender';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';

jest.mock('../utilities/commandLifecycleFeedback', () => ({
  submitCommandWithLifecycleFeedback: jest.fn(),
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

jest.mock('./DroneActions', () => () => <div>Mock Actions</div>);
jest.mock('./CommandPreflightSummary', () => () => <div>Mock Preflight</div>);

const drones = [
  { hw_id: '1', update_time: Date.now() },
  { hw_id: '2', update_time: Date.now() },
  { hw_id: '3', update_time: Date.now() },
];

describe('CommandSender', () => {
  beforeEach(() => {
    jest.clearAllMocks();
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

    render(<CommandSender drones={drones} />);

    fireEvent.click(screen.getByRole('button', { name: 'Mock Send Mission' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(screen.getByText('Live Command Monitor')).toBeInTheDocument();
    });

    expect(screen.getByText('Swarm Trajectory')).toBeInTheDocument();
    expect(screen.getByText('Scheduled, waiting for trigger time')).toBeInTheDocument();
    expect(screen.getByText('Selected drones: 1, 2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel Before Trigger' })).toBeInTheDocument();
    expect(screen.getByText('Accepted')).toBeInTheDocument();
    expect(screen.getByText('2/2')).toBeInTheDocument();
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

    render(<CommandSender drones={drones} />);

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
});
