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
const open = () => { fireEvent.click(screen.getByRole('button', { name: /^Alerts/ })); return screen.getByRole('dialog', { name: 'Fleet alerts' }); };

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
  expect(within(dialog).getByText(/Seen does not clear a condition/)).toBeInTheDocument();
  const conditions = within(dialog).getByRole('list', { name: 'Observed conditions' });
  expect(within(conditions).getByRole('link', { name: 'Open aircraft H1' })).toHaveAttribute('href', '/?aircraft=1');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Mark Scout Battery: Low as seen' }));
  expect(within(conditions).getByText('Seen')).toBeInTheDocument();
  expect(within(conditions).getByText('Battery: Low')).toBeInTheDocument();
  expect(within(dialog).queryByText(/Recently cleared/)).not.toBeInTheDocument();
});

test('condition history survives navigation but is explicitly last observed until source returns', () => {
  render(tree());
  fireEvent.click(screen.getByRole('link', { name: 'Open workspace' }));
  expect(screen.getByRole('heading', { name: 'Mission workspace' })).toBeInTheDocument();
  act(() => jest.advanceTimersByTime(12000));
  const dialog = open();
  expect(within(dialog).getByText(/Last observed 12s ago · not live/)).toBeInTheDocument();
  expect(within(dialog).queryByRole('list', { name: 'Observed conditions' })).not.toBeInTheDocument();
  expect(within(dialog).getByRole('list', { name: 'Last-observed conditions' })).toHaveTextContent('Last observed 12s ago');
  fireEvent.click(within(dialog).getByRole('link', { name: 'Open aircraft H1' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(within(open()).getByRole('list', { name: 'Observed conditions' })).toHaveTextContent('Battery: Low');
});

test('without newer events, age alone removes the current-observation presentation', () => {
  render(tree());
  const dialog = open();
  expect(within(dialog).getByRole('list', { name: 'Observed conditions' })).toBeInTheDocument();
  act(() => jest.advanceTimersByTime(6000));
  expect(within(dialog).queryByRole('list', { name: 'Observed conditions' })).not.toBeInTheDocument();
  expect(within(dialog).getByText(/Last observed 6s ago · not live/)).toBeInTheDocument();
  expect(within(dialog).getByRole('list', { name: 'Last-observed conditions' })).toHaveTextContent('6s ago');
});

test('100 unavailable aircraft during a GCS outage create one aggregate alert', () => {
  const aircraft = Array.from({ length: 100 }, (_, index) => ({ id: String(index + 1), current: false, issues: [{ key: 'telemetry', label: 'Offline' }] }));
  render(tree({ aircraft, sourceError: true }));
  expect(screen.getByRole('button', { name: 'Alerts 1' })).toBeInTheDocument();
  const dialog = open();
  expect(within(dialog).getAllByRole('listitem')).toHaveLength(1);
  expect(within(dialog).getByText('Telemetry source unavailable')).toBeInTheDocument();
  expect(within(dialog).queryByRole('link', { name: /Open aircraft/ })).not.toBeInTheDocument();
});

test('runtime/operator provider remount clears local history', () => {
  const view = render(tree());
  expect(screen.getByRole('button', { name: 'Alerts 1' })).toBeInTheDocument();
  view.rerender(tree({ scope: 'real:operator-b', aircraft: [] }));
  expect(screen.getByRole('button', { name: 'Alerts' })).toBeInTheDocument();
  expect(within(open()).queryByText('Battery: Low')).not.toBeInTheDocument();
});

test('a remembered GCS outage is not presented as current connectivity after navigation', () => {
  render(tree({ sourceError: true }));
  fireEvent.click(screen.getByRole('link', { name: 'Open workspace' }));
  const dialog = open();
  expect(within(dialog).getByText('Last observed: telemetry source unavailable.')).toBeInTheDocument();
  expect(within(dialog).queryByRole('list', { name: 'Observed conditions' })).not.toBeInTheDocument();
});

test('native dialog cancellation closes and restores trigger focus', () => {
  render(tree());
  const trigger = screen.getByRole('button', { name: /^Alerts/ });
  trigger.focus();
  const dialog = open();
  expect(dialog.closest('.fleet-alerts')).toBeNull();
  fireEvent(dialog, new Event('cancel', { bubbles: true, cancelable: true }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});
