import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import TacticalDroneCard from './TacticalDroneCard';

describe('TacticalDroneCard', () => {
  it('renders compact tactical status and operator quick links', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <TacticalDroneCard
          drone={{
            hw_id: '1',
            pos_id: '4',
            position: [35.123456, 51.654321, 112.3],
            stateLabel: 'Smart Swarm',
            follow_mode: 0,
            altitude: 112.3,
            marker_color: '#33cc88',
            battery_voltage: 16.25,
            distance_to_home_m: 18.4,
            flight_mode: 262147,
            is_armed: true,
            gps_fix_type: 3,
            satellites_visible: 14,
            mission: 2,
            speed_mps: 3.21,
            last_update: 1700000000000,
          }}
        />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /P4\|H1 tactical summary/i })).toBeInTheDocument();
    expect(screen.getAllByText('Smart Swarm')).toHaveLength(2);
    expect(screen.getByText('16.25 V')).toBeInTheDocument();
    expect(screen.getByText('18.4 m')).toBeInTheDocument();
    expect(screen.queryByText('XYZ')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Config/i })).toHaveAttribute('href', '/mission-config?drone=1&edit=1');
    expect(screen.getByRole('link', { name: /Swarm/i })).toHaveAttribute('href', '/swarm-design?drone=1');
  });
});
