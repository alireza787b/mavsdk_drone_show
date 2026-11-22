import React, { useEffect } from 'react';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { FleetAlertsProvider, useFleetAlerts } from './FleetAlertsContext';
import FleetAlertsPanel from './FleetAlertsPanel';

const NOW = 1780000000000;
const AIRCRAFT = [{ id: '1', label: 'Scout', current: true, issues: [{ key: 'battery', label: 'Battery: Low', tone: 'warning' }] }];
function Source({ aircraft = AIRCRAFT, sourceError = false }) {
  const { publishSnapshot, sourceUnavailable } = useFleetAlerts();
  useEffect(() => { publishSnapshot({ aircraft, sourceError, observedAtMs: Date.now() }); }, [aircraft, sourceError, publishSnapshot]);
  useEffect(() => () => sourceUnavailable(), [sourceUnavailable]);
  return <Link to="/workspace">Open workspace</Link>;
}
function tree({ scope = 'sitl:operator-a', aircraft = AIRCRAFT, sourceError = false, start = '/' } = {}) {
  return <MemoryRouter initialEntries={[start]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <FleetAlertsProvider key={scope}>
      <FleetAlertsPanel />
      <Routes><Route path="/" element={<Source aircraft={aircraft} sourceError={sourceError} />} />
        <Route path="/workspace" element={<h1>Mission workspace</h1>} /></Routes>
    </FleetAlertsProvider>
  </MemoryRouter>;
}
const open = (name = /^(Caution:|Alerts$)/) => {
  fireEvent.click(screen.getByRole('button', { name }));
  return screen.getByRole('dialog');
};

beforeEach(() => { jest.useFakeTimers(); jest.setSystemTime(NOW); });
afterEach(() => { cleanup(); jest.useRealTimers(); });

test('normal view is only a compact affordance, with no verbose health box', () => {
  render(tree({ aircraft: [] }));
  expect(screen.getByRole('button', { name: 'Alerts' })).toHaveAttribute('aria-expanded', 'false');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.queryByText(/No conditions/)).not.toBeInTheDocument();
});

test('acknowledgement stays Seen, not resolved, and aircraft links preserve exact ID', () => {
  render(tree());
  const dialog = open();
  const conditions = within(dialog).getByRole('list', { name: 'Current alerts' });
  expect(within(conditions).getByRole('link', { name: 'Open aircraft H1' })).toHaveAttribute('href', '/?aircraft=1');
  const seen = within(dialog).getByRole('button', { name: 'Mark Scout Battery: Low as seen' });
  seen.focus();
  fireEvent.click(seen);
  expect(seen).toHaveAttribute('aria-disabled', 'true');
  expect(seen).toHaveAccessibleName('Seen: Scout Battery: Low');
  expect(seen).toHaveFocus();
  expect(within(conditions).getByText(/Battery: Low/)).toBeInTheDocument();
  expect(within(dialog).queryByText(/Recently cleared/)).not.toBeInTheDocument();
});

test('condition history survives navigation but is explicitly last observed until source returns', () => {
  render(tree());
  fireEvent.click(screen.getByRole('link', { name: 'Open workspace' }));
  expect(screen.getByRole('heading', { name: 'Mission workspace' })).toBeInTheDocument();
  act(() => jest.advanceTimersByTime(12000));
  const dialog = open();
  expect(within(dialog).queryByRole('list', { name: 'Current alerts' })).not.toBeInTheDocument();
  expect(within(dialog).getByRole('list', { name: 'Last reported alerts' })).toHaveTextContent('Battery: Low');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close fleet alerts' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Caution: 1' })).not.toBeInTheDocument();
});

test('without newer events, age alone removes the current-observation presentation', () => {
  render(tree());
  const dialog = open();
  expect(within(dialog).getByRole('list', { name: 'Current alerts' })).toBeInTheDocument();
  act(() => jest.advanceTimersByTime(6000));
  expect(within(dialog).queryByRole('list', { name: 'Current alerts' })).not.toBeInTheDocument();
  expect(within(dialog).getByRole('list', { name: 'Last reported alerts' })).toHaveTextContent('Battery: Low');
});

test('100 unavailable aircraft during a GCS outage create one aggregate alert', () => {
  const aircraft = Array.from({ length: 100 }, (_, index) => ({ id: String(index + 1), current: false, issues: [{ key: 'telemetry', label: 'Offline' }] }));
  render(tree({ aircraft, sourceError: true }));
  expect(screen.getByRole('button', { name: 'Warning: 1' })).toBeInTheDocument();
  const dialog = open('Warning: 1');
  expect(within(dialog).getAllByRole('listitem')).toHaveLength(1);
  expect(within(dialog).getByText(/Telemetry source unavailable/)).toBeInTheDocument();
  expect(within(dialog).queryByRole('link', { name: /Open aircraft/ })).not.toBeInTheDocument();
});

test('runtime/operator provider remount clears local history', () => {
  const view = render(tree());
  expect(screen.getByRole('button', { name: 'Caution: 1' })).toBeInTheDocument();
  view.rerender(tree({ scope: 'real:operator-b', aircraft: [] }));
  expect(screen.getByRole('button', { name: 'Alerts' })).toBeInTheDocument();
  expect(within(open()).queryByText('Battery: Low')).not.toBeInTheDocument();
});

test('a remembered GCS outage is not presented as current connectivity after navigation', () => {
  render(tree({ sourceError: true }));
  fireEvent.click(screen.getByRole('link', { name: 'Open workspace' }));
  const dialog = open();
  expect(within(dialog).getByRole('list', { name: 'Last reported alerts' })).toHaveTextContent('Telemetry source unavailable');
  expect(within(dialog).queryByRole('list', { name: 'Current alerts' })).not.toBeInTheDocument();
});

test('native dialog cancellation closes and restores trigger focus', () => {
  render(tree());
  const trigger = screen.getByRole('button', { name: 'Caution: 1' });
  trigger.focus();
  const dialog = open();
  expect(dialog.closest('.fleet-alerts')).toBeNull();
  fireEvent(dialog, new Event('cancel', { bubbles: true, cancelable: true }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

test('the sheet switches severity in place and keeps history within that filter', () => {
  const mixed = [{ id: '1', label: 'Scout', current: true, issues: [
    { key: 'battery', label: 'Battery low', tone: 'warning' },
    { key: 'link', label: 'Link lost', tone: 'danger' },
  ] }];
  const view = render(tree({ aircraft: mixed }));
  const dialog = open('Warning: 1');
  expect(within(dialog).getByText('Link lost')).toBeVisible();
  expect(within(dialog).queryByText('Battery low')).not.toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cautions 1' }));
  expect(screen.getByRole('dialog')).toBe(dialog);
  expect(within(dialog).getByText('Battery low')).toBeVisible();
  view.rerender(tree({ aircraft: [{ ...mixed[0], issues: [] }] }));
  const history = within(dialog).getByText('Recently cleared').closest('details');
  expect(history).not.toHaveAttribute('open');
  history.open = true;
  expect(within(dialog).getByRole('list', { name: 'Recently cleared alerts' })).toHaveTextContent('Battery low');
  expect(within(dialog).queryByText('Link lost')).not.toBeInTheDocument();
});

test('the same condition on 100 aircraft is one row until the operator expands it', () => {
  const aircraft = Array.from({ length: 100 }, (_, index) => ({
    ...AIRCRAFT[0], id: String(index + 1), label: `Scout ${index + 1}`,
  }));
  render(tree({ aircraft }));
  const dialog = open('Caution: 100');
  const rows = within(dialog).getByRole('list', { name: 'Current alerts' });
  expect(within(rows).getAllByRole('listitem')).toHaveLength(1);
  expect(within(rows).queryByRole('link')).not.toBeInTheDocument();
  const group = within(rows).getByText('100 aircraft').closest('details');
  group.open = true;
  fireEvent(group, new Event('toggle'));
  expect(within(rows).getByRole('link', { name: 'Open aircraft H100' })).toHaveAttribute('href', '/?aircraft=100');
});

test('an expiring trigger returns focus to the remaining alerts control on close', () => {
  render(tree());
  const dialog = open('Caution: 1');
  act(() => jest.advanceTimersByTime(6000));
  expect(screen.getByRole('button', { name: 'Caution: 0' })).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close fleet alerts' }));
  expect(screen.getByRole('button', { name: 'Alerts' })).toHaveFocus();
});

test('repeated history for one aircraft is counted by report', () => {
  const cleared = [{ ...AIRCRAFT[0], issues: [] }];
  const view = render(tree());
  view.rerender(tree({ aircraft: cleared }));
  view.rerender(tree());
  view.rerender(tree({ aircraft: cleared }));
  const dialog = open('Alerts');
  const history = within(dialog).getByText('Recently cleared').closest('details');
  history.open = true;
  expect(within(history).getByText('2 reports')).toBeVisible();
});
