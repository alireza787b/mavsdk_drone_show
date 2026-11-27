import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import SwarmHeightAdvisory from './SwarmHeightAdvisory';

const now = Date.now();
const row = (id, altitude, extra = {}) => ({ hw_id: id, altitude_m: altitude, altitude_timestamp_ms: now,
  gps_fix_type: 3, gps_timestamp_ms: now, landed_state: 1, landed_timestamp_ms: now, planned_height_m: 0, ...extra });
const warning = { threshold_m: 1, max_age_ms: 5000, samples: [row('1', 100), row('2', 105.5), row('3', 101)] };

test('uses selected aircraft and read-only references, without command controls', () => {
  render(<SwarmHeightAdvisory warning={warning} targetIds={['1']} referenceIds={['2']} />);
  expect(screen.getByText('5.5 m')).toBeInTheDocument();
  expect(screen.getByText('2/2')).toBeInTheDocument();
  const details = screen.getByText('5.5 m').closest('details');
  details.open = true; fireEvent(details, new Event('toggle', { bubbles: true }));
  expect(within(details).getByText('H2')).toBeInTheDocument();
  expect(within(details).getByText('REF')).toBeInTheDocument();
  expect(screen.queryByText('H3')).not.toBeInTheDocument();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

test('stale and missing observations stay unknown', () => {
  const stale = { ...warning, samples: [row('1', 100), row('2', 105, { altitude_timestamp_ms: now - 6000, gps_timestamp_ms: null })] };
  render(<SwarmHeightAdvisory warning={stale} targetIds={['1', '2', '3']} />);
  expect(screen.getByText('1/3')).toBeInTheDocument();
  const details = screen.getByText('1/3').closest('details');
  details.open = true; fireEvent(details, new Event('toggle', { bubbles: true }));
  expect(screen.getByText(/stale/)).toBeInTheDocument();
  expect(screen.queryByText(/READINGS/)).toBeInTheDocument();
});

test('only fresh airborne measurements use planned offsets', () => {
  const airborne = { ...warning, samples: [row('1', 100, { landed_state: 2 }), row('2', 105.5, { landed_state: 2, planned_height_m: 5 })] };
  render(<SwarmHeightAdvisory warning={airborne} targetIds={['1', '2']} />);
  expect(screen.getByText('0.5 m')).toBeInTheDocument();
});


test('ages source observations using receipt time despite clock skew and expires without polling', () => {
  jest.useFakeTimers();
  try {
    const local = Date.now();
    const source = local - 3600000;
    const skewed = { threshold_m: 1, max_age_ms: 5000, observed_at_ms: source,
      samples: [row('1', 100, { altitude_timestamp_ms: source, gps_timestamp_ms: source }), row('2', 105, { altitude_timestamp_ms: source, gps_timestamp_ms: source })] };
    render(<SwarmHeightAdvisory warning={skewed} targetIds={['1', '2']} receivedAtMs={local} />);
    expect(screen.getByText('5.0 m')).toBeInTheDocument();
    act(() => { jest.advanceTimersByTime(6000); });
    expect(screen.getByText('UNKNOWN').closest('details')).toHaveTextContent('0/2');
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(screen.getByText('UNKNOWN').closest('details')).toHaveTextContent('0/2');
  } finally { jest.useRealTimers(); }
});


test('large roster is bounded and searchable by callsign', () => {
  const ids = Array.from({ length: 200 }, (_, i) => String(i + 1));
  const fleet = ids.map(id => ({ hw_id: id, callsign: `Aircraft ${id}` }));
  const large = { ...warning, samples: ids.map(id => row(id, 100)) };
  render(<SwarmHeightAdvisory warning={large} targetIds={ids} aircraft={fleet} />);
  const details = screen.getByText('200/200').closest('details');
  details.open = true; fireEvent(details, new Event('toggle', { bubbles: true }));
  expect(screen.getAllByRole('listitem')).toHaveLength(30);
  fireEvent.change(screen.getByLabelText('Find aircraft'), { target: { value: 'Aircraft 199' } });
  expect(screen.getAllByRole('listitem')).toHaveLength(1);
  expect(screen.getByText('Aircraft 199')).toBeInTheDocument();
});

test('RTK duration uses observed fixes rather than the current clock', () => {
  const rtk = { ...warning, samples: [row('1', 100, { gps_fix_type: 6, rtk_fixed_observed_since_ms: now - 2000 }), row('2', 101)] };
  render(<SwarmHeightAdvisory warning={rtk} targetIds={['1', '2']} />);
  const details = screen.getByText('2/2').closest('details');
  details.open = true; fireEvent(details, new Event('toggle', { bubbles: true }));
  expect(screen.getByText(/RTK fixed for 2 seconds/)).toBeInTheDocument();
});
