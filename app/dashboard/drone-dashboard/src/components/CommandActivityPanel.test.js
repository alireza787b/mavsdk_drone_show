import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import CommandActivityPanel from './CommandActivityPanel';
import { useCommandActivity } from '../contexts/CommandActivityContext';
import { sendDroneCommand } from '../services/droneApiService';
import { fetchGcsResource } from '../services/gcsApiService';
import {
  buildLifecycleSnapshotFromStatus,
  submitCommandWithLifecycleFeedback,
} from '../utilities/commandLifecycleFeedback';

jest.mock('../contexts/CommandActivityContext', () => ({ useCommandActivity: jest.fn() }));
jest.mock('../services/droneApiService', () => ({
  sendDroneCommand: jest.fn(),
}));
jest.mock('../services/gcsApiService', () => ({
  ...jest.requireActual('../services/gcsApiService'),
  fetchGcsResource: jest.fn(),
}));
jest.mock('../utilities/commandLifecycleFeedback', () => ({
  ...jest.requireActual('../utilities/commandLifecycleFeedback'),
  submitCommandWithLifecycleFeedback: jest.fn(),
}));

const dismiss = jest.fn();
const snapshot = (status = {}) => buildLifecycleSnapshotFromStatus({
  command_id: 'command-1', mission_name: 'Drone Show', mission_type: 1,
  target_drones: ['1', '2'], phase: 'in_progress', updated_at: 1234,
  progress: { stage: 'executing', label: 'Running', message: 'Aircraft executing' },
  ...status,
});
const provide = (monitors) => useCommandActivity.mockReturnValue({
  commandMonitors: monitors, dismissCommandMonitor: dismiss,
});
const openActivity = () => fireEvent.click(screen.getByRole('button', { name: /^Activity/ }));
const renderPanel = () => render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
  <CommandActivityPanel />
</MemoryRouter>);

beforeEach(() => {
  jest.clearAllMocks();
  provide([]);
});

test('empty activity remains available without polling or creating commands', () => {
  renderPanel();

  expect(screen.getByText('No commands recorded')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /^Activity/ })).toHaveAttribute('aria-expanded', 'false');
  openActivity();
  expect(screen.getByText('No recent commands in this GCS history.')).toBeVisible();
  expect(fetchGcsResource).not.toHaveBeenCalled();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});

test('renders actual recovered snapshot fields and only allows terminal dismissal', () => {
  provide([snapshot(), snapshot({ command_id: 'finished', mission_name: 'Land', mission_type: 101,
    phase: 'terminal', outcome: 'completed', progress: { stage: 'completed', label: 'Completed' } })]);
  renderPanel();
  openActivity();

  expect(screen.getByRole('heading', { name: 'Drone Show', level: 3 })).toBeInTheDocument();
  expect(screen.getByText('Running')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Dismiss Drone Show' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss Land' }));
  expect(dismiss).toHaveBeenCalledWith('finished');
  expect(screen.queryByRole('button', { name: 'Cancel Land' })).not.toBeInTheDocument();
});

test('partial outcomes and bounded per-aircraft reasons remain visible', () => {
  provide([snapshot({ phase: 'terminal', outcome: 'partial',
    executions: { expected: 2, succeeded: 1, failed: 1, details: {
      '1': { success: true, outcome: 'completed' },
      '2': { success: false, outcome: 'failed', error: 'Flight controller rejected launch' },
    } },
  })]);
  renderPanel();

  expect(screen.getByRole('button', { name: /^Activity/ })).toHaveTextContent('Partial result');
  expect(screen.getByText('0 active · 1 need review')).toBeInTheDocument();
  openActivity();
  expect(screen.getByText('Partial result').closest('li')).toHaveClass('command-activity__item--warning');
  const details = screen.getByText('Aircraft & details · 1 affected').closest('details');
  fireEvent.click(within(details).getByText('Aircraft & details · 1 affected'));
  expect(within(details).getByText('Drone 2 · Execution: Flight controller rejected launch')).toBeVisible();
  expect(within(details).getByText('Targets: 1, 2')).toBeVisible();
});

test.each(['timeout', 'unavailable'])('tracking issue %s stays highlighted when collapsed', (trackingIssue) => {
  provide([{ ...snapshot(), trackingIssue }]);
  renderPanel();

  expect(screen.getByText('1 active · 1 need review')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /^Activity/ })).toHaveTextContent(
    trackingIssue === 'timeout' ? 'Outcome unconfirmed' : 'Tracking unavailable'
  );
});

test('terminal timeouts are uncertain, while supersession is informational', () => {
  provide([snapshot({ phase: 'terminal', outcome: 'timeout' }), snapshot({ command_id: 'replaced',
    mission_name: 'Hold', phase: 'terminal', outcome: 'superseded' })]);
  renderPanel();
  openActivity();

  expect(screen.getByText('Outcome unconfirmed').closest('li')).toHaveClass('command-activity__item--warning');
  expect(screen.getByText('Replaced').closest('li')).toHaveClass('command-activity__item--neutral');
  expect(screen.getByText('0 active · 1 need review')).toBeInTheDocument();
});

test('disclosure never renders more than eight distinct command rows', () => {
  const monitors = Array.from({ length: 10 }, (_, index) => snapshot({ command_id: `cmd-${index}` }));
  provide([monitors[0], ...monitors]);
  renderPanel();
  openActivity();

  expect(screen.getAllByRole('heading', { level: 3 })).toHaveLength(8);
  expect(screen.getByText('8 active · 0 need review')).toBeInTheDocument();
});

test('unknown target counts remain unknown without exposing flight actions', () => {
  provide([snapshot({ target_drones: [] })]);
  renderPanel();
  openActivity();

  expect(screen.getByText('Targets not reported')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Cancel Drone Show' })).not.toBeInTheDocument();
});

test.each([
  [1, '/drone-show'], [2, '/swarm-design'], [3, '/custom-show'],
  [4, '/swarm-trajectory'], [5, '/quickscout'],
])('mission %i links its owning workspace without dispatch or receipt requests', (missionType, route) => {
  provide([snapshot({ mission_type: missionType })]);
  renderPanel();
  openActivity();

  const link = screen.getByRole('link', { name: /^Open mission workspace/ });
  expect(link).toHaveAttribute('href', route);
  fireEvent.click(link);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /cancel|recover|stop/i })).not.toBeInTheDocument();
  expect(fetchGcsResource).not.toHaveBeenCalled();
  expect(sendDroneCommand).not.toHaveBeenCalled();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});

test.each([0, 10, 101, 102, 104, 105, 112, 999])(
  'action or unknown type %i links fleet controls without guessing an originating mission', (missionType) => {
    provide([snapshot({ mission_type: missionType })]);
    renderPanel();
    openActivity();

    expect(screen.getByRole('link', { name: /^Open fleet controls/ })).toHaveAttribute('href', '/');
    expect(screen.queryByRole('link', { name: /^Open mission workspace/ })).not.toBeInTheDocument();
    expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  }
);

test('mission links remain available for failed and uncertain terminal outcomes', () => {
  provide([snapshot({ mission_type: 3, phase: 'terminal', outcome: 'timeout' })]);
  renderPanel();
  openActivity();

  expect(screen.getByRole('link', { name: /^Open mission workspace/ })).toHaveAttribute('href', '/custom-show');
  expect(screen.getByRole('button', { name: 'Dismiss Drone Show' })).toBeInTheDocument();
});
