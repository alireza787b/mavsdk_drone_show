import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import TacticalDroneCard from './TacticalDroneCard';
import { CommandActivityProvider } from '../contexts/CommandActivityContext';
import { getActiveCommands, getRecentCommands } from '../services/droneApiService';
import {
  encodePx4CustomMode,
  PX4_AUTO_SUB_MODES,
  PX4_MAIN_MODES,
} from '../constants/px4FlightModes';

jest.mock('../utilities/commandLifecycleFeedback', () => ({
  submitCommandWithLifecycleFeedback: jest.fn(),
}));

jest.mock('../services/droneApiService', () => {
  const actual = jest.requireActual('../services/droneApiService');
  return {
    ...actual,
    getActiveCommands: jest.fn(),
    getRecentCommands: jest.fn(),
  };
});

const renderCard = (ui) => render(
  <CommandActivityProvider>
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      {ui}
    </MemoryRouter>
  </CommandActivityProvider>
);

describe('TacticalDroneCard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getActiveCommands.mockResolvedValue({ commands: [] });
    getRecentCommands.mockResolvedValue({ commands: [] });
  });

  it('renders compact tactical status and operator quick controls', () => {
    renderCard(
      <TacticalDroneCard
        drone={{
          hw_id: '1',
          pos_id: '4',
          position: [35.123456, 51.654321, 112.3],
          stateLabel: 'Smart Swarm',
          follow_mode: 0,
          altitude: 112.3,
          battery_voltage: 16.25,
          distance_to_home_m: 18.4,
          flight_mode: encodePx4CustomMode(
            PX4_MAIN_MODES.AUTO,
            PX4_AUTO_SUB_MODES.AUTO_LOITER,
          ),
          is_armed: true,
          gps_fix_type: 3,
          satellites_visible: 14,
          mission: 2,
          speed_mps: 3.21,
          last_update: 1700000000000,
        }}
      />
    );

    expect(screen.getByRole('region', { name: /P4\|H1 tactical summary/i })).toBeInTheDocument();
    expect(screen.getAllByText('Smart Swarm')).toHaveLength(2);
    expect(screen.getByText('16.3V')).toBeInTheDocument();
    expect(screen.getByText('18 m')).toBeInTheDocument();
    expect(screen.queryByText('XYZ')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Return to Launch P4\|H1/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Open precision jog for P4\|H1/i })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Config/i })).not.toBeInTheDocument();
  });

  it('uses the operator alias as primary identity without hiding hardware identity', () => {
    renderCard(
      <TacticalDroneCard
        drone={{
          hw_id: '2',
          pos_id: '7',
          operator_alias: 'SCOUT-2',
          position: [35.1, 51.2, 100],
          stateLabel: 'Ready',
        }}
      />
    );

    expect(screen.getByRole('region', { name: /SCOUT-2 tactical summary/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'SCOUT-2' })).toBeInTheDocument();
    expect(screen.getByText('P7|H2')).toBeInTheDocument();
  });

  it('shares reported Ethernet/Wi-Fi semantics with Overview and keeps extra metadata collapsed', () => {
    renderCard(<TacticalDroneCard drone={{ hw_id: '2', ip: '192.0.2.2',
      heartbeat_last_seen: Date.now() / 1000,
      heartbeat_network_info: { primary_link: { type: 'ethernet', interface: 'end0' }, wifi: { signal_strength_percent: 80 } },
    }} />);
    expect(screen.getByText('Ethernet')).toBeInTheDocument();
    expect(screen.getByText('192.0.2.2')).toBeInTheDocument();
    expect(screen.queryByText('80%')).not.toBeInTheDocument();
    expect(screen.getByText('Details').closest('details')).not.toHaveAttribute('open');
  });

  it('missing GPS and distance evidence are not manufactured as zero or a fix', () => {
    renderCard(<TacticalDroneCard drone={{ hw_id: '2', gps_fix_type: null, distance_to_home_m: null, position: [35.1,51.2,20] }} />);
    expect(screen.getByLabelText('GPS: GPS n/a')).toBeInTheDocument();
    expect(screen.getByLabelText('Distance home: Map n/a')).toBeInTheDocument();
    expect(screen.getByText('Role unknown')).toBeInTheDocument();
  });

  it('a different inspected aircraft cannot inherit a reviewed return action', () => {
    const view = renderCard(<TacticalDroneCard drone={{ hw_id: '1', callsign: 'Alpha', is_armed: true }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Return to Launch Alpha' }));
    view.rerender(<CommandActivityProvider><MemoryRouter><TacticalDroneCard drone={{ hw_id: '2', callsign: 'Bravo', is_armed: true }} /></MemoryRouter></CommandActivityProvider>);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('describes source-aware altitude without treating relative altitude as MSL', () => {
    renderCard(
      <TacticalDroneCard
        drone={{
          hw_id: '3',
          pos_id: '8',
          position: [0, 0, 0],
          altitude_report: {
            display_m: 8.4,
            source: 'relative_home',
            label: 'REL',
            stale: false,
          },
        }}
      />
    );

    const altitudeMetric = screen.getByLabelText('Altitude: 8.4 m REL');
    expect(altitudeMetric).toHaveAttribute('data-help', expect.stringContaining('Home-relative altitude'));
  });
});
