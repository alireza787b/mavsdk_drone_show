import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';

import DroneConfigCard from './DroneConfigCard';

describe('DroneConfigCard', () => {
  it('renders compact operator indicators and opens git details on demand', () => {
    render(
      <DroneConfigCard
        drone={{
          hw_id: '1',
          pos_id: '2',
          ip: '10.0.0.11',
          mavlink_port: '14551',
          serial_port: '',
          baudrate: '0',
          custom_fields: [
            { key: 'callsign', value: 'Alpha', type: 'string' },
          ],
        }}
        gitStatus={{
          branch: 'main',
          commit: 'abcdef1234567890',
          in_sync_with_gcs: true,
        }}
        gcsGitStatus={{ commit: 'abcdef1234567890' }}
        configData={[
          {
            hw_id: '1',
            pos_id: '2',
          },
        ]}
        availableHwIds={['1', '2']}
        editingDroneId={null}
        setEditingDroneId={jest.fn()}
        saveChanges={jest.fn()}
        removeDrone={jest.fn()}
        networkInfo={null}
        heartbeatData={{
          timestamp: Date.now(),
          ip: '10.0.0.11',
          pos_id: '2',
        }}
      />
    );

    const indicators = screen.getByLabelText('Operator card indicators');

    expect(within(indicators).getByRole('button', { name: /slot/i })).toBeInTheDocument();
    expect(within(indicators).getByText('Aligned')).toBeInTheDocument();
    expect(within(indicators).getByText('P2')).toBeInTheDocument();
    expect(within(indicators).getByRole('button', { name: /link/i })).toBeInTheDocument();
    expect(within(indicators).getByText('Simulated')).toBeInTheDocument();
    expect(within(indicators).getByRole('button', { name: /git/i })).toBeInTheDocument();
    expect(within(indicators).getByText('Synced')).toBeInTheDocument();
    expect(screen.queryByText('Source Drone 2.csv')).not.toBeInTheDocument();

    fireEvent.click(within(indicators).getByRole('button', { name: /slot/i }));

    expect(screen.getByText('Slot confirmed')).toBeInTheDocument();
    expect(screen.getByText('Source Drone 2.csv')).toBeInTheDocument();
    expect(screen.getByText('Identity')).toBeInTheDocument();

    expect(screen.queryByText('Full Hash')).not.toBeInTheDocument();

    fireEvent.click(within(indicators).getByRole('button', { name: /git/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Toggle Details' }));

    expect(screen.getByText('Full Hash')).toBeInTheDocument();
    expect(screen.getByText('abcdef1234567890')).toBeInTheDocument();
  });

  it('uses reassigned-slot wording when hardware and slot differ', () => {
    render(
      <DroneConfigCard
        drone={{
          hw_id: '5',
          pos_id: '6',
          ip: '10.0.0.15',
          mavlink_port: '14555',
          serial_port: '',
          baudrate: '0',
        }}
        gitStatus={null}
        gcsGitStatus={null}
        configData={[
          {
            hw_id: '5',
            pos_id: '6',
          },
        ]}
        availableHwIds={['5', '6']}
        editingDroneId={null}
        setEditingDroneId={jest.fn()}
        saveChanges={jest.fn()}
        removeDrone={jest.fn()}
        networkInfo={null}
        heartbeatData={null}
      />
    );

    expect(screen.getByText('Reassigned slot')).toBeInTheDocument();
  });

  it('prefers the heartbeat-declared runtime mode over local inference', () => {
    render(
      <DroneConfigCard
        drone={{
          hw_id: '7',
          pos_id: '7',
          ip: '10.0.0.17',
          mavlink_port: '14557',
          serial_port: '',
          baudrate: '0',
        }}
        gitStatus={null}
        gcsGitStatus={null}
        configData={[
          {
            hw_id: '7',
            pos_id: '7',
          },
        ]}
        availableHwIds={['7']}
        editingDroneId={null}
        setEditingDroneId={jest.fn()}
        saveChanges={jest.fn()}
        removeDrone={jest.fn()}
        networkInfo={null}
        heartbeatData={{
          timestamp: Date.now(),
          ip: '10.0.0.17',
          pos_id: '7',
          runtime_mode: 'real',
        }}
      />
    );

    expect(screen.getByText('REAL')).toBeInTheDocument();

    const indicators = screen.getByLabelText('Operator card indicators');
    fireEvent.click(within(indicators).getByRole('button', { name: /link/i }));

    expect(screen.getByText('REAL / hardware')).toBeInTheDocument();
    expect(screen.getByText('Runtime network telemetry unavailable')).toBeInTheDocument();
    expect(screen.queryByText('SITL / simulated')).not.toBeInTheDocument();
  });

  it('labels USB modem transport and internet status distinctly from Ethernet', () => {
    render(
      <DroneConfigCard
        drone={{
          hw_id: '1',
          pos_id: '1',
          ip: '100.82.72.33',
          mavlink_port: '14551',
          serial_port: '/dev/ttyAMA0',
          baudrate: '921600',
        }}
        gitStatus={null}
        gcsGitStatus={null}
        configData={[
          {
            hw_id: '1',
            pos_id: '1',
          },
        ]}
        availableHwIds={['1']}
        editingDroneId={null}
        setEditingDroneId={jest.fn()}
        saveChanges={jest.fn()}
        removeDrone={jest.fn()}
        networkInfo={{
          wifi: null,
          ethernet: null,
          usb_modem: {
            interface: 'usb0',
            connection_name: 'Wired connection 1',
          },
          primary_link: {
            type: 'usb_modem',
            label: '4G USB',
            interface: 'usb0',
            connection_name: 'Wired connection 1',
            internet_reachable: true,
          },
          internet: {
            enabled: true,
            reachable: true,
            target: '1.1.1.1',
          },
          timestamp: Date.now(),
        }}
        heartbeatData={{
          timestamp: Date.now(),
          ip: '100.82.72.33',
          pos_id: '1',
          runtime_mode: 'real',
        }}
      />
    );

    const indicators = screen.getByLabelText('Operator card indicators');
    expect(within(indicators).getByText('4G USB')).toBeInTheDocument();

    fireEvent.click(within(indicators).getByRole('button', { name: /link/i }));

    expect(screen.getByText('Primary link')).toBeInTheDocument();
    expect(screen.getAllByText('usb0').length).toBeGreaterThan(0);
    expect(screen.getByText('USB / 4G')).toBeInTheDocument();
    expect(screen.getByText('Reachable')).toBeInTheDocument();
  });
});
