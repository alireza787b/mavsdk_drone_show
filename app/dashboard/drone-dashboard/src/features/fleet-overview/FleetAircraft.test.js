import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AircraftInspector, AircraftTile } from './FleetAircraft';
import { buildAircraftViewModel } from './fleetViewModel';
import { DRONE_MISSION_TYPES } from '../../constants/droneConstants';

const NOW = 1780000000000;
const aircraft = (extra = {}, now = NOW) => buildAircraftViewModel({
  hw_id: '7', pos_id: '3', callsign: 'Scout', update_time: NOW / 1000, telemetry_available: true,
  heartbeat_last_seen: NOW / 1000, heartbeat_network_info: { wifi: { signal_strength_percent: 72 } },
  is_armed: false, landed_state: 1, flight_mode: 0x03040000, mission: DRONE_MISSION_TYPES.SMART_SWARM,
  battery_remaining_percent: 80, battery_voltage: 16.1, position_alt: 1200,
  gps_fix_type: 6, satellites_visible: 18, ...extra,
}, now);

function tile(item = aircraft()) {
  const props = { item, selected: false, inspected: false, onToggle: jest.fn(), onInspect: jest.fn() };
  return { ...render(<AircraftTile {...props} />), props };
}

test('tile exposes compact identity, named telemetry and separately addressable selection/inspection', () => {
  const { props, container } = tile();
  expect(screen.getByText('H7 · P3')).toBeInTheDocument();
  expect(screen.getByLabelText('Flight mode: Hold')).toBeInTheDocument();
  expect(screen.getByLabelText('Altitude: 1200.0 m MSL')).toBeInTheDocument();
  expect(screen.getByLabelText('GNSS: RTK fixed · 18 sats')).toBeInTheDocument();
  expect(screen.getByLabelText('Link: Fresh · 0s · Wi-Fi 72%')).toBeInTheDocument();
  expect(screen.getByLabelText('Mission: Smart Swarm')).toBeInTheDocument();
  expect(container.querySelector('.fleet-state-symbol')).toHaveAttribute('data-state', 'grounded');
  expect(container.querySelector('article')).toHaveAttribute('data-readiness', 'unknown');
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select Scout · H7' }));
  expect(props.onToggle).toHaveBeenCalledWith('7');
  expect(props.onInspect).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Inspect Scout · H7' }));
  expect(props.onInspect).toHaveBeenCalledWith('7');
});

test('stale tile labels cached measurements and cannot infer an aircraft phase or show cached Wi-Fi', () => {
  const { container } = tile(aircraft({}, NOW + 20000));
  expect(screen.getByText('Flight state unknown')).toBeInTheDocument();
  expect(screen.getByLabelText('Flight mode: Hold, Last known')).toBeInTheDocument();
  expect(screen.getByLabelText('Altitude: 1200.0 m MSL, Last known')).toBeInTheDocument();
  expect(screen.getByLabelText('Link: Stale · 20s')).toBeInTheDocument();
  expect(screen.queryByText(/Wi-Fi 72/)).not.toBeInTheDocument();
  expect(container.querySelector('article')).toHaveClass('is-stale');
  expect(container.querySelector('article')).toHaveAttribute('data-availability', 'stale');
  expect(container.querySelector('.fleet-state-symbol')).toHaveAttribute('data-state', 'unknown');
});

test('airborne glyph does not turn a native ground-preflight status into an overall flight warning', () => {
  const { container } = tile(aircraft({ landed_state: 2, readiness_status: 'blocked' }));
  expect(screen.getByText('Airborne')).toBeInTheDocument();
  expect(container.querySelector('.fleet-state-symbol')).toHaveAttribute('data-state', 'airborne');
  expect(container.querySelector('.fleet-aircraft__readiness')).toBeNull();
});

test('inspector uses current model identity for every action and retains decoded mode with raw code only in diagnostics', () => {
  const props = { item: aircraft({ landed_state: 2 }), onClose: jest.fn(), onAction: jest.fn(), onMove: jest.fn(), onMore: jest.fn() };
  const { rerender } = render(<MemoryRouter><AircraftInspector {...props} /></MemoryRouter>);
  const inspector = within(screen.getByRole('dialog', { name: 'Scout' }));
  expect(inspector.getByText('Hold', { selector: 'dd' })).toBeInTheDocument();
  fireEvent.click(inspector.getByRole('button', { name: 'Return' }));
  expect(props.onAction).toHaveBeenCalledWith('RETURN_RTL', props.item);
  fireEvent.click(inspector.getByRole('button', { name: 'More' }));
  expect(props.onMore).toHaveBeenCalledWith(props.item);
  const updated = aircraft({ landed_state: 1, readiness_status: 'ready', flight_mode: 0 });
  rerender(<MemoryRouter><AircraftInspector {...props} item={updated} /></MemoryRouter>);
  expect(inspector.getByText('Initializing', { selector: 'dd' })).toBeInTheDocument();
  expect(inspector.getByRole('button', { name: 'Move' })).toBeDisabled();
  fireEvent.click(inspector.getByRole('button', { name: 'Takeoff' }));
  expect(props.onAction).toHaveBeenLastCalledWith('TAKE_OFF', updated);
  fireEvent.click(inspector.getByRole('button', { name: 'More' }));
  expect(props.onMore).toHaveBeenLastCalledWith(updated);
});
