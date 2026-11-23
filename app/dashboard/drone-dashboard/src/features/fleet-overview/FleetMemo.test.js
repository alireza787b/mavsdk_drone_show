import React, { useEffect } from 'react';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FleetAlertsProvider, useFleetAlerts } from './FleetAlertsContext';
import FleetMemo from './FleetMemo';
import { useCommandActivity } from '../../contexts/CommandActivityContext';

jest.mock('../../contexts/CommandActivityContext', () => ({ useCommandActivity: jest.fn() }));
const NOW = 1780000000000;
const scope = 'test:operator';
const alerts = [{ id: '1', label: 'Scout', current: true,
  preflight: { can_arm: false, custom_mode: 123, mode: 'Hold', label: 'PX4 cannot arm' },
  issues: [{ key: 'battery', label: 'Battery low', tone: 'warning', source: 'MDS' }],
}];
const active = { commandId: 'live-1', commandLabel: 'Hold', targetDrones: ['1'], progress: { label: 'In progress' }, updatedAtMs: NOW };
const complete = { commandId: 'past-2', commandLabel: 'Takeoff', targetDrones: ['2'], isTerminal: true, outcome: 'completed', updatedAtMs: NOW };
const tracker = { commandMonitors: [complete, active], commandHistory: [complete], dismissCommandMonitor: jest.fn() };

function Source({ aircraft, sourceError }) {
  const { publishSnapshot, sourceUnavailable } = useFleetAlerts();
  useEffect(() => { publishSnapshot({ aircraft, sourceError, observedAtMs: Date.now() }); }, [aircraft, sourceError, publishSnapshot]);
  useEffect(() => () => sourceUnavailable(), [sourceUnavailable]);
  return null;
}
function tree(aircraft = alerts, sourceError = false) {
  return <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <FleetAlertsProvider historyKey={`${scope}:history`}>
      <FleetMemo scope={scope} /><Source aircraft={aircraft} sourceError={sourceError} />
    </FleetAlertsProvider>
  </MemoryRouter>;
}
function openMemo() {
  fireEvent.click(screen.getByRole('button', { name: 'Memo' }));
  return within(screen.getByRole('dialog', { name: 'Memo' }));
}
beforeEach(() => {
  jest.useFakeTimers();
  jest.setSystemTime(NOW);
  localStorage.clear();
  tracker.dismissCommandMonitor.mockClear();
  useCommandActivity.mockReturnValue(tracker);
});
afterEach(() => { cleanup(); jest.useRealTimers(); });

test('Live orders warnings, cautions and operations and omits completed receipts', () => {
  render(tree());
  const memo = openMemo();
  expect(memo.getAllByRole('listitem').map(row => row.textContent)).toEqual([
    'PX4 cannot arm · HoldScout · H1 · PX4', 'Battery lowScout · H1 · MDS', expect.stringContaining('Hold · In progress'),
  ]);
  expect(memo.queryByText('Takeoff · Complete')).not.toBeInTheDocument();
  fireEvent.click(memo.getByText('Hold · In progress'));
  expect(memo.getByText('live-1')).toBeVisible();
  expect(within(memo.getByText('PX4 cannot arm · Hold').closest('li')).getByRole('link', { name: 'Open aircraft H1' })).toHaveAttribute('href', '/?aircraft=1');
});

test('Clear resolved preserves active rows and records across refresh', () => {
  const view = render(tree());
  act(() => jest.advanceTimersByTime(500));
  const remaining = [{ ...alerts[0], issues: [] }];
  view.rerender(tree(remaining));
  let memo = openMemo();
  fireEvent.click(memo.getByRole('button', { name: 'History 2' }));
  expect(memo.getByText('Battery low')).toBeVisible();
  expect(memo.getByText('Takeoff · Complete')).toBeVisible();
  fireEvent.click(memo.getByRole('button', { name: 'Clear resolved' }));
  expect(memo.getByRole('button', { name: 'History' })).toBeVisible();
  expect(memo.getByText('Battery low')).toBeVisible();
  expect(memo.getByText('Takeoff · Complete')).toBeVisible();
  expect(tracker.dismissCommandMonitor).not.toHaveBeenCalled();
  view.unmount();
  render(tree(remaining));
  memo = openMemo();
  expect(memo.getByText('PX4 cannot arm · Hold')).toBeVisible();
  expect(memo.getByText('Hold · In progress')).toBeVisible();
  expect(memo.queryByText('Battery low')).not.toBeInTheDocument();
  fireEvent.click(memo.getByRole('button', { name: 'History' }));
  expect(memo.getByText('Battery low')).toBeVisible();
  expect(memo.getByText('Takeoff · Complete')).toBeVisible();
  expect(memo.getByRole('button', { name: 'Clear resolved' })).toHaveAttribute('aria-disabled', 'true');
});

test('acknowledgement keeps the condition visible until it clears and recurs', () => {
  const view = render(tree());
  const memo = openMemo();
  const button = memo.getByRole('button', { name: 'Mark Scout Battery low as seen' });
  button.focus();
  fireEvent.click(button);
  expect(memo.getByText('Battery low')).toBeVisible();
  expect(button).toHaveAccessibleName('Seen: Scout Battery low');
  expect(button).toHaveFocus();
  view.rerender(tree([{ ...alerts[0], issues: [] }]));
  view.rerender(tree());
  expect(memo.getByRole('button', { name: 'Mark Scout Battery low as seen' })).toBeEnabled();
});

test('expired conditions go to last reported and Escape restores focus', () => {
  render(tree());
  const trigger = screen.getByRole('button', { name: 'Memo' });
  const memo = openMemo();
  act(() => jest.advanceTimersByTime(6000));
  expect(memo.queryByRole('list', { name: 'Current alerts' })).not.toBeInTheDocument();
  fireEvent.click(memo.getByRole('button', { name: /History/ }));
  const last = memo.getByText('Last reported').closest('details');
  last.open = true;
  expect(within(last).getByRole('list')).toHaveTextContent('Battery low');
  fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true, cancelable: true }));
  expect(trigger).toHaveFocus();
});

test('100 instances of one current condition share one line with exact aircraft links', () => {
  const fleet = Array.from({ length: 100 }, (_, index) => ({
    id: String(index + 1), label: `Scout ${index + 1}`, current: true, issues: [alerts[0].issues[0]],
  }));
  render(tree(fleet));
  const list = within(openMemo().getByRole('list', { name: 'Current alerts' }));
  expect(list.getAllByRole('listitem')).toHaveLength(1);
  expect(list.queryByRole('link')).not.toBeInTheDocument();
  const group = list.getByText('100 aircraft · MDS').closest('details');
  group.open = true;
  fireEvent(group, new Event('toggle'));
  expect(list.getByRole('link', { name: 'Open aircraft H100' })).toHaveAttribute('href', '/?aircraft=100');
});

test('an unavailable native report moves a denial out of Live without resolving it', () => {
  const view = render(tree());
  const memo = openMemo();
  expect(memo.getByText('PX4 cannot arm · Hold')).toBeVisible();
  const noReport = [{ ...alerts[0], preflight: null, issues: [] }];
  view.rerender(tree(noReport));
  expect(memo.queryByText('PX4 cannot arm · Hold')).not.toBeInTheDocument();
  fireEvent.click(memo.getByRole('button', { name: 'History 2' }));
  const last = memo.getByText('Last reported').closest('details');
  expect(last).toHaveTextContent('PX4 cannot arm · Hold');
  view.rerender(tree([{ ...noReport[0], preflight: { can_arm: true, custom_mode: 456 } }]));
  expect(memo.getByText('Last reported')).toBeVisible();
  view.rerender(tree([{ ...noReport[0], preflight: { can_arm: true, custom_mode: 123 } }]));
  expect(memo.queryByText('Last reported')).not.toBeInTheDocument();
  expect(within(memo.getByRole('list', { name: 'Resolved alerts' })).getByText('PX4 cannot arm · Hold')).toBeVisible();
});

test('authoritatively active commands stay in Live through a tracking interruption', () => {
  const observation = { snapshots: [active], receivedAtMs: NOW + 1 };
  const unconfirmed = { ...active, trackingIssue: 'timeout' };
  useCommandActivity.mockReturnValue({
    commandMonitors: [unconfirmed], activeObservation: observation,
  });
  const view = render(tree([]));
  const memo = openMemo();
  expect(memo.getByText('Hold · In progress')).toBeVisible();
  fireEvent.click(memo.getByRole('button', { name: 'History' }));
  expect(memo.queryByText('Hold · Outcome unconfirmed')).not.toBeInTheDocument();
  useCommandActivity.mockReturnValue({
    commandMonitors: [unconfirmed], activeObservation: { snapshots: [], receivedAtMs: NOW + 2 },
  });
  view.rerender(tree([]));
  expect(memo.getByText('Hold · Outcome unconfirmed')).toBeVisible();
  fireEvent.click(memo.getByRole('button', { name: 'Live' }));
  expect(memo.getByText('Nothing needs attention')).toBeVisible();
});
