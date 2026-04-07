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
          branch: 'main-candidate',
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
});
