import React from 'react';
import { render, screen } from '@testing-library/react';

import DroneStatusCard from './DroneStatusCard';

describe('DroneStatusCard', () => {
  it('shows compact slot and hardware identity when both are available', () => {
    render(
      <DroneStatusCard
        droneState={{
          hw_id: '5',
          pos_id: 12,
          state: 'executing',
          coverage_percent: 42.5,
          current_waypoint_index: 4,
          total_waypoints: 10,
        }}
      />
    );

    expect(screen.getByText('P12|H5')).toBeInTheDocument();
    expect(screen.getByText('42.5%')).toBeInTheDocument();
    expect(screen.getByText('WP 4/10')).toBeInTheDocument();
  });
});
