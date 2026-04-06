import React from 'react';
import { render, screen, within } from '@testing-library/react';

import DroneConfigCard from './DroneConfigCard';

describe('DroneConfigCard', () => {
  it('renders compact runtime summary chips in read-only mode', () => {
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

    const runtimeSummary = screen.getByLabelText('Runtime summary');

    expect(within(runtimeSummary).getByText('Path')).toBeInTheDocument();
    expect(within(runtimeSummary).getByText('10.0.0.11')).toBeInTheDocument();
    expect(within(runtimeSummary).getByText('Link')).toBeInTheDocument();
    expect(within(runtimeSummary).getByText('SITL / simulated')).toBeInTheDocument();
    expect(within(runtimeSummary).getByText('Git')).toBeInTheDocument();
    expect(within(runtimeSummary).getByText('Git main-candidate synced')).toBeInTheDocument();
    expect(screen.getByText('Diagnostics & metadata')).toBeInTheDocument();
  });
});
