import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';

import CommandPreflightSummary from './CommandPreflightSummary';
import useNormalizedTelemetry from '../hooks/useNormalizedTelemetry';

jest.mock('../hooks/useNormalizedTelemetry', () => ({ __esModule: true, default: jest.fn() }));

const NOW = Date.UTC(2026, 10, 9, 12);
const aircraft = (id, overrides = {}) => ({
  hw_id: id,
  pos_id: id,
  update_time: NOW,
  telemetry_available: true,
  is_ready_to_arm: true,
  readiness_status: 'ready',
  preflight_last_update: NOW,
  is_armed: false,
  ...overrides,
});
const metric = (name) => screen.getByRole('button', { name: new RegExp(`^${name}`) });

beforeEach(() => {
  jest.spyOn(Date, 'now').mockReturnValue(NOW);
  useNormalizedTelemetry.mockReturnValue({ data: { gcs_status: { commit: 'abc1234' }, git_status: {} }, loading: false });
});

afterEach(() => jest.restoreAllMocks());

test('an empty target set is neutral and never Ready', () => {
  render(<CommandPreflightSummary drones={[aircraft('1')]} targetMode="selected" targetDroneIds={[]} referenceNowMs={NOW} />);

  expect(screen.getByText('NO TARGETS')).toBeInTheDocument();
  expect(screen.queryByText(/^READY/)).not.toBeInTheDocument();
  expect(metric('Readiness')).toHaveClass('command-preflight__metric--neutral');
  expect(within(metric('Readiness')).getByText('0/0')).toBeInTheDocument();
});

test('cached ready and armed values cannot count as fresh evidence', () => {
  render(<CommandPreflightSummary drones={[
    aircraft('1', { update_time: NOW - 20_000, heartbeat_last_seen: NOW, is_armed: true }),
    aircraft('2', { update_time: NOW - 61_000, is_armed: false }),
  ]} referenceNowMs={NOW} />);

  expect(screen.getByText('NOT READY')).toBeInTheDocument();
  expect(within(metric('Readiness')).getByText('0/2')).toBeInTheDocument();
  expect(within(metric('Armed')).getByText('0')).toBeInTheDocument();
  expect(within(metric('Armed')).getByText('0 disarmed · 2 unknown')).toBeInTheDocument();
  fireEvent.click(metric('Readiness'));
  expect(screen.getAllByText('Live readiness unavailable')).toHaveLength(2);
});

test('counts exact fresh arm booleans and keeps missing values unknown', () => {
  render(<CommandPreflightSummary drones={[
    aircraft('1', { is_armed: true }), aircraft('2'),
    aircraft('3', { is_armed: undefined }), aircraft('4', { is_armed: 'true' }),
  ]} referenceNowMs={NOW} />);

  expect(within(metric('Armed')).getByText('1')).toBeInTheDocument();
  expect(within(metric('Armed')).getByText('1 disarmed · 2 unknown')).toBeInTheDocument();
});

test('missing selected aircraft stay in every denominator and do not become disarmed', () => {
  render(<CommandPreflightSummary drones={[aircraft('1')]} targetMode="selected"
    targetDroneIds={['1', 'missing', '1']} referenceNowMs={NOW} />);

  expect(screen.getByText('NOT READY')).toBeInTheDocument();
  expect(within(metric('Live Link')).getByText('1/2')).toBeInTheDocument();
  expect(within(metric('Readiness')).getByText('1/2')).toBeInTheDocument();
  expect(within(metric('Armed')).getByText('1 disarmed · 1 unknown')).toBeInTheDocument();
  fireEvent.click(metric('Live Link'));
  expect(screen.getByText('Selected aircraft unavailable')).toBeInTheDocument();
});

test('unavailable telemetry cannot count as ready even with a recent timestamp', () => {
  render(<CommandPreflightSummary drones={[aircraft('1', { telemetry_available: false })]} referenceNowMs={NOW} />);

  expect(screen.getByText('NOT READY')).toBeInTheDocument();
  expect(within(metric('Readiness')).getByText('0/1')).toBeInTheDocument();
  expect(within(metric('Armed')).getByText('0 disarmed · 1 unknown')).toBeInTheDocument();
});

test('fresh armable aircraft with advisory warnings remain ready with caution', () => {
  render(<CommandPreflightSummary drones={[aircraft('1', {
    readiness_status: 'warning',
    preflight_warnings: [{ source: 'px4', severity: 'warning', message: 'Review heading', timestamp: NOW }],
  })]} referenceNowMs={NOW} />);

  expect(screen.getByText('READY · CAUTION')).toBeInTheDocument();
  expect(within(metric('Readiness')).getByText('1/1')).toBeInTheDocument();
});

test('review-only unarmable aircraft cannot produce a Ready summary', () => {
  render(<CommandPreflightSummary drones={[aircraft('1', { readiness_status: 'warning', is_ready_to_arm: false })]} referenceNowMs={NOW} />);

  expect(screen.getByText('NOT READY')).toBeInTheDocument();
  expect(within(metric('Readiness')).getByText('0/1')).toBeInTheDocument();
});

test('exception totals count the complete cohort while disclosure remains bounded', () => {
  const fleet = Array.from({ length: 20 }, (_, index) => aircraft(String(index + 1), { update_time: NOW - 120_000 }));
  render(<CommandPreflightSummary drones={fleet} referenceNowMs={NOW} />);

  expect(within(metric('Readiness')).getByText('20')).toBeInTheDocument();
  fireEvent.click(metric('Readiness'));
  expect(screen.getByText('(8/20)')).toBeInTheDocument();
  expect(screen.getAllByText('Live readiness unavailable')).toHaveLength(8);
  expect(screen.getByText('12 more entries. Select a metric to narrow the list.')).toBeInTheDocument();
});

test('duplicate roster rows do not inflate fleet counts', () => {
  render(<CommandPreflightSummary drones={[aircraft('1'), aircraft('1')]} referenceNowMs={NOW} />);

  expect(within(metric('Readiness')).getByText('1/1')).toBeInTheDocument();
});
