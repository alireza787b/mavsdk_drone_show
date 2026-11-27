import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import UlogSummary from './UlogSummary';

const day = Date.UTC(2026, 0, 2);
const summary = { parsed: true, parser: { status: 'ok' }, timeline: { events: [
  { utc_ms: day + 1600, source: 'PX4 mode', label: 'Hold' },
  { utc_ms: null, elapsed_ms: 2000, source: 'PX4 mode', label: 'Offboard' },
], truncated: true }, companion_evidence: { status: 'partial', reason: 'Window ends early.', events: [
  { utc_ms: day - 200, source: 'Smart Swarm', label: 'Updates delayed', metrics: { rejected: 0 } },
] } };
test('chronology preserves UTC, separates unaligned events, and exposes missing coverage and zero counts', () => {
  render(<UlogSummary summary={summary} />);
  const utc = within(screen.getByRole('list', { name: 'UTC events' })).getAllByRole('listitem');
  expect(utc).toHaveLength(2);
  expect(utc[0]).toHaveTextContent('2026-01-01 UTC');
  expect(utc[1]).toHaveTextContent('2026-01-02 UTC');
  expect(utc[0].querySelector('time')).toHaveAttribute('datetime', '2026-01-01T23:59:59.800Z');
  fireEvent.click(within(utc[0]).getByText('Updates delayed'));
  expect(within(utc[0]).getByText('0')).toBeVisible();
  expect(screen.getByRole('list', { name: 'Elapsed events' })).toHaveTextContent('+2.000 sOffboard');
  expect(screen.getByText('Partial link record')).toBeVisible();
  expect(screen.getByText('Partial event list')).toBeVisible();
});
test('large summaries have a bounded initial event list and no fabricated link data', () => {
  const events = Array.from({ length: 12 }, (_, i) => ({ utc_ms: day + i, source: 'PX4', label: 'H' + i }));
  const { rerender } = render(<UlogSummary summary={{ timeline: { events }, companion_evidence: { status: 'unavailable' } }} />);
  expect(screen.getByText('Link record unavailable')).toBeVisible();
  expect(screen.getAllByRole('listitem')).toHaveLength(8);
  fireEvent.click(screen.getByRole('button', { name: 'Show more events (4)' }));
  expect(screen.getAllByRole('listitem')).toHaveLength(12);
  rerender(<UlogSummary summary={{ parsed: true, parser: { status: 'ok' } }} />);
  expect(screen.queryByRole('region', { name: 'Flight timeline' })).toBeNull();
});

test('periodic samples are opt-in alongside decisions and remain visible in sample-only recordings', () => {
  const sample = { utc_ms: day, kind: 'sample', source: 'Companion Wi-Fi', label: 'Aircraft Wi-Fi', metrics: { wifi_signal_percent: 72 } };
  const hold = { utc_ms: day + 5, kind: 'event', source: 'PX4 mode', label: 'Hold' };
  const { rerender } = render(<UlogSummary summary={{ timeline: { events: [sample, hold] } }} />);
  expect(screen.queryByText('Aircraft Wi-Fi')).toBeNull();
  expect(screen.getByText('Hold')).toBeVisible();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Link samples (1)' }));
  fireEvent.click(screen.getByText('Aircraft Wi-Fi'));
  expect(screen.getByText('72 %')).toBeVisible();
  rerender(<UlogSummary summary={{ timeline: { events: [sample] } }} />);
  expect(screen.getByText('Aircraft Wi-Fi')).toBeVisible();
  expect(screen.queryByRole('checkbox')).toBeNull();
});

test('single-source summaries label their coverage and keep parser errors visible', () => {
  render(<UlogSummary summary={{ parsed: false, parser: { status: 'error', error: 'PX4 parser failure' }, timeline: { events: [] } }} />);
  expect(screen.getByText('PX4 recording only')).toBeVisible();
  expect(screen.getByText('PX4 parser failure')).toBeVisible();
});
