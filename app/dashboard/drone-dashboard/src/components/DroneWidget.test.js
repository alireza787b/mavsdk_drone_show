import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import DroneWidget from './DroneWidget';

jest.mock('react-tooltip', () => ({
  Tooltip: () => null,
}));

const baseDrone = {
  hw_id: '1',
  pos_id: 1,
  update_time: Date.now(),
  telemetry_available: true,
  is_armed: false,
  base_mode: 0,
  flight_mode: 0,
  system_status: 4,
  battery_voltage: 16.0,
  gps_fix_type: 3,
  satellites_visible: 12,
};

const renderWidget = (props = {}) => render(
  <MemoryRouter>
    <DroneWidget
      drone={baseDrone}
      toggleDroneDetails={jest.fn()}
      setSelectedDrone={jest.fn()}
      isExpanded={false}
      {...props}
    />
  </MemoryRouter>,
);

describe('DroneWidget command scope state', () => {
  test('marks out-of-scope drones with a distinct card state', () => {
    const { container } = renderWidget({ commandScopeState: 'out' });

    const widget = container.querySelector('.drone-widget');
    expect(widget).toHaveClass('command-scope-out');
    expect(widget).toHaveAttribute('data-command-scope', 'out');
  });

  test('marks any active command scope and emits toggle requests', () => {
    const onToggleCommandScope = jest.fn();
    const { container } = renderWidget({
      commandScopeState: 'all',
      onToggleCommandScope,
    });

    const widget = container.querySelector('.drone-widget');
    expect(widget).toHaveClass('command-scope-active');
    expect(widget).toHaveAttribute('data-command-scope', 'all');

    fireEvent.click(screen.getByRole('button', { name: /all-drones command scope/i }));

    expect(onToggleCommandScope).toHaveBeenCalledWith('1');
  });
});
