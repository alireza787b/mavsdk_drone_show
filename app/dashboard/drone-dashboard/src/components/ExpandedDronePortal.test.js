import React from 'react';
import { render, screen } from '@testing-library/react';
import ExpandedDronePortal from './ExpandedDronePortal';

jest.mock('./DroneDetail', () => () => <div data-testid="drone-detail" />);
jest.mock('./DroneCriticalCommands', () => () => <div data-testid="critical-commands" />);
jest.mock('./DroneReadinessReport', () => () => <div data-testid="readiness-report" />);

const baseDrone = {
  hw_id: '1',
  pos_id: 1,
  update_time: Date.now(),
  telemetry_available: true,
  is_armed: false,
  base_mode: 0,
  flight_mode: 0,
  state: 0,
  battery_voltage: 16.0,
  gps_fix_type: 0,
  global_position_valid: false,
};

function renderPortal(drone) {
  const portalRoot = document.createElement('div');
  portalRoot.id = 'expanded-drone-portal-root';
  document.body.appendChild(portalRoot);
  return render(
    <ExpandedDronePortal
      drone={{ ...baseDrone, ...drone }}
      isOpen
      onClose={jest.fn()}
    />
  );
}

describe('ExpandedDronePortal altitude display', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  test('uses source-aware local altitude instead of legacy map altitude', () => {
    renderPortal({
      position_alt: 0,
      altitude_report: {
        display_m: 3.2,
        source: 'local_ned',
        label: 'LCL',
        stale: false,
      },
    });

    const altitude = screen.getByText('3.2 m LCL');
    expect(altitude).toHaveAttribute(
      'data-help',
      expect.stringContaining('LOCAL_POSITION_NED')
    );
  });
});
