import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import DroneWidget from './DroneWidget';
import { CommandActivityProvider } from '../contexts/CommandActivityContext';
import { getActiveCommands, getRecentCommands } from '../services/droneApiService';

jest.mock('react-tooltip', () => ({
  Tooltip: () => null,
}));

jest.mock('../services/droneApiService', () => {
  const actual = jest.requireActual('../services/droneApiService');
  return {
    ...actual,
    getActiveCommands: jest.fn(),
    getRecentCommands: jest.fn(),
  };
});

const baseDrone = {
  hw_id: '1',
  pos_id: 1,
  update_time: Date.now(),
  telemetry_available: true,
  is_armed: false,
  base_mode: 0,
  flight_mode: 0,
  state: 0,
  system_status: 4,
  battery_voltage: 16.0,
  gps_fix_type: 3,
  satellites_visible: 12,
};

const renderWidget = (props = {}) => render(
  <CommandActivityProvider>
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <DroneWidget
        drone={baseDrone}
        toggleDroneDetails={jest.fn()}
        setSelectedDrone={jest.fn()}
        isExpanded={false}
        {...props}
      />
    </MemoryRouter>
  </CommandActivityProvider>,
);

describe('DroneWidget command scope state', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getActiveCommands.mockResolvedValue({ commands: [] });
    getRecentCommands.mockResolvedValue({ commands: [] });
  });

  test('marks out-of-scope drones with a distinct card state', () => {
    const { container } = renderWidget({ commandScopeState: 'out' });

    const widget = container.querySelector('.drone-widget');
    expect(widget).toHaveClass('command-scope-out');
    expect(widget).toHaveAttribute('data-command-scope', 'out');
    expect(screen.getAllByText('Out').length).toBeGreaterThan(0);
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
    expect(screen.getByText('In')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /all-drones command scope/i }));

    expect(onToggleCommandScope).toHaveBeenCalledWith('1');
  });

  test('shows primary network link as a compact status icon', () => {
    const { container } = renderWidget({
      drone: {
        ...baseDrone,
        heartbeat_network_info: {
          primary_link: {
            type: 'wifi',
            label: 'Wi-Fi',
            ssid: 'field-router',
            interface: 'wlan0',
            signal_strength_percent: 82,
            internet_reachable: true,
          },
        },
      },
    });

    const indicator = container.querySelector('.drone-network-indicator');
    expect(indicator).toHaveClass('link-wifi');
    expect(indicator).toHaveClass('signal-strong');
    expect(indicator).toHaveClass('tone-strong');
    expect(indicator).toHaveAttribute(
      'aria-label',
      expect.stringContaining('Primary link: Wi-Fi (field-router)'),
    );
    expect(indicator).toHaveAttribute('aria-label', expect.stringContaining('Signal: 82%'));
  });
});
