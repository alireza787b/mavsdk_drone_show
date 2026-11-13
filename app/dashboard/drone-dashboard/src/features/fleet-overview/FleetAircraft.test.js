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
  const props = { item, selected: false, inspected: false, onInspect: jest.fn(), onToggle: jest.fn() };
  return { ...render(<AircraftTile {...props} />), props };
}

test('tile exposes compact identity and inspection without editing command recipients', () => {
  const { props, container } = tile();
  expect(screen.getByText('H7 · P3')).toBeInTheDocument();
  expect(screen.getByLabelText('Flight mode: Hold')).toBeInTheDocument();
  expect(screen.getByLabelText('Altitude: 1200.0 m MSL')).toBeInTheDocument();
  expect(screen.getByLabelText('GNSS: RTK fixed · 18 sats')).toBeInTheDocument();
  expect(screen.getByLabelText('Link: Fresh · 0s · Wi-Fi 72%')).toBeInTheDocument();
  expect(screen.getByLabelText('Mission: Smart Swarm')).toBeInTheDocument();
  expect(container.querySelector('.fleet-state-symbol')).toHaveAttribute('data-state', 'grounded');
  expect(container.querySelector('article')).toHaveAttribute('data-readiness', 'unknown');
  expect(container.querySelector('.fleet-aircraft__schematic')).toBeInTheDocument();
  expect(container.querySelector('.fleet-aircraft__instruments')).toBeInTheDocument();
  expect(screen.queryByText('Details')).not.toBeInTheDocument();
  expect(screen.queryByText(/16\.1\s*V/)).not.toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: 'Include Scout (H7)' })).not.toBeChecked();
  expect(props.onInspect).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Inspect Scout · H7' }));
  expect(props.onInspect).toHaveBeenCalledWith('7');
  expect(props.onToggle).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Include Scout (H7)' }));
  expect(props.onToggle).toHaveBeenCalledWith('7');
  expect(props.onInspect).toHaveBeenCalledTimes(1);
});

test('normal idle cards omit routine mission prose but retain all details in inspection', () => {
  tile(aircraft({ mission: DRONE_MISSION_TYPES.NONE }));
  expect(screen.queryByLabelText(/Mission:/)).not.toBeInTheDocument();
  expect(screen.getByText('80%')).toBeInTheDocument();
  expect(screen.queryByText('Fresh')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Link: Fresh · 0s · Wi-Fi 72%')).toHaveTextContent('72%');
  expect(screen.getByText('RTK fixed')).toBeInTheDocument();
});

test('unknown measurements use a compact mark without inventing a measured value', () => {
  const item = aircraft();
  item.battery = { ...item.battery, text: 'Unknown', remaining: null };
  item.gps = { ...item.gps, label: 'Unknown' };
  item.altitude = { ...item.altitude, value: null };
  tile(item);
  expect(screen.getByLabelText('Battery: Unknown')).toHaveTextContent('—');
  expect(screen.getByLabelText('Altitude: Unknown')).toHaveTextContent('—');
  expect(screen.getByLabelText('GNSS: Unknown · 18 sats')).toHaveTextContent('—');
});

test('fresh cards do not display ticking second counters; inspection shows the configured address', () => {
  const model = aircraft({ ip: '192.0.2.7' });
  const view = tile(model);
  expect(screen.queryByText(/\d+s ago/)).not.toBeInTheDocument();
  expect(screen.getByLabelText('Link: Fresh · 0s · Wi-Fi 72%')).toHaveTextContent('72%');
  view.unmount();
  render(<MemoryRouter><AircraftInspector item={model} onClose={jest.fn()} onAction={jest.fn()} onMove={jest.fn()} /></MemoryRouter>);
  expect(screen.getByText('192.0.2.7')).toBeInTheDocument();
  const age = screen.getByText('0s ago');
  expect(age.closest('details')).not.toHaveAttribute('open');
});

test.each([
  [{ primary_link: { type: 'ethernet', interface: 'end0' }, wifi: { signal_strength_percent: 72 } }, 'Ethernet'],
  [{ primary_link: { type: 'wifi', interface: 'wlan0' }, wifi: { signal_strength_percent: 72 } }, 'Wi-Fi · 72%'],
  [null, 'Unknown'],
])('inspector labels the reported transport without an unrelated Wi-Fi row', (network, expected) => {
  const model = aircraft({ heartbeat_network_info: network });
  render(<MemoryRouter><AircraftInspector item={model} onClose={jest.fn()} onAction={jest.fn()} onMove={jest.fn()} /></MemoryRouter>);
  expect(screen.getByText('Network', { selector: 'dt' }).nextElementSibling).toHaveTextContent(expected);
  expect(screen.queryByText('Wi-Fi signal')).not.toBeInTheDocument();
});

test('Ethernet card uses the wired symbol and never presents another radio signal', () => {
  const { container } = tile(aircraft({ heartbeat_network_info: {
    primary_link: { type: 'ethernet', interface: 'end0' }, wifi: { signal_strength_percent: 72 },
  } }));
  expect(screen.getByLabelText('Link: Fresh · 0s · Ethernet')).toHaveTextContent('');
  expect(container.querySelector('.fleet-aircraft__metric--link svg')).toBeInTheDocument();
  expect(screen.queryByText('72%')).not.toBeInTheDocument();
});

test('stale network details clearly mark the cached transport without a cached signal', () => {
  const model = aircraft({}, NOW + 20000);
  render(<MemoryRouter><AircraftInspector item={model} onClose={jest.fn()} onAction={jest.fn()} onMove={jest.fn()} /></MemoryRouter>);
  expect(screen.getByText('Network', { selector: 'dt' }).nextElementSibling).toHaveTextContent('Wi-Fi · last known');
  expect(screen.queryByText('72%')).not.toBeInTheDocument();
});

test('ground readiness and initialization use distinct truthful aircraft badges', () => {
  const view = tile(aircraft({ readiness_status: 'ready' }));
  expect(screen.getByLabelText('Preflight ready')).toHaveAttribute('data-status', 'ready');
  view.rerender(<AircraftTile {...view.props} item={aircraft({
    node_boot_status: { phase: 'starting_mds', status: 'running', timestamp: NOW },
  }, NOW + 20000)} />);
  expect(screen.getByLabelText('Initializing')).toHaveAttribute('data-status', 'initializing');
  expect(screen.queryByLabelText('Preflight ready')).not.toBeInTheDocument();
  expect(screen.getByText('Flight state unknown')).toBeInTheDocument();
});

test('stale-link and prioritized alert badges open inspection without changing targets', () => {
  const item = aircraft({
    heartbeat_last_seen: (NOW - 20000) / 1000,
    preflight_blockers: [{ message: 'Heading estimate not stable' }],
    preflight_warnings: [{ message: 'Battery check required' }],
  });
  const { props } = tile(item);
  expect(screen.getByLabelText('Heartbeat stale')).toHaveAttribute('data-status', 'stale');
  const alert = screen.getByLabelText('Warning: 2 aircraft conditions');
  expect(alert).toHaveClass('tone-danger');
  fireEvent.click(alert);
  expect(props.onInspect).toHaveBeenCalledWith('7');
  expect(screen.getByText('Heading estimate not stable')).toBeInTheDocument();
});

test('caution is distinguished by shape/label, and an airborne vehicle never gains a ground-ready badge', () => {
  tile(aircraft({ landed_state: 2, readiness_status: 'ready', preflight_warnings: [{ message: 'Check link' }] }));
  expect(screen.getByLabelText('Caution: 1 aircraft conditions')).toHaveClass('tone-warning');
  expect(screen.queryByLabelText('Preflight ready')).not.toBeInTheDocument();
  expect(screen.getByText('Airborne')).toBeInTheDocument();
});

test('loss of evidence overrides an old initializing/ready report without inventing a landed state', () => {
  tile(aircraft({ readiness_status: 'ready', node_boot_status: { phase: 'starting_mds', status: 'running', timestamp: NOW } }, NOW + 50000));
  expect(screen.getByLabelText('Link lost')).toHaveAttribute('data-status', 'lost');
  expect(screen.queryByLabelText('Initializing')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Preflight ready')).not.toBeInTheDocument();
  expect(screen.getByText('Flight state unknown')).toBeInTheDocument();
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
