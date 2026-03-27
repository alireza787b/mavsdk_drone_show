import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SwarmTrajectoryTransferDialog from './SwarmTrajectoryTransferDialog';
import { getSwarmClusterStatus } from '../../services/droneApiService';

jest.mock('../../services/droneApiService', () => ({
  getSwarmClusterStatus: jest.fn(),
}));

describe('SwarmTrajectoryTransferDialog', () => {
  const baseProps = {
    isOpen: true,
    onClose: jest.fn(),
    onUploadCurrentTrajectory: jest.fn().mockResolvedValue({ message: 'Leader CSV uploaded.' }),
    onOpenSwarmTrajectory: jest.fn(),
    onOpenSwarmDesign: jest.fn(),
    trajectoryName: 'ridge-line-pass',
    waypointCount: 4,
    trajectoryStats: { totalTime: 92, maxSpeed: 8.4 },
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('loads clusters and uploads to the selected leader', async () => {
    const user = userEvent.setup();

    getSwarmClusterStatus.mockResolvedValue({
      clusters: [
        {
          leader_id: 1,
          follower_ids: [2, 3],
          follower_count: 2,
          ready: false,
          leader_uploaded: false,
          cluster_plot_available: false,
        },
        {
          leader_id: 5,
          follower_ids: [6],
          follower_count: 1,
          ready: true,
          leader_uploaded: true,
          cluster_plot_available: true,
        },
      ],
    });

    render(<SwarmTrajectoryTransferDialog {...baseProps} />);

    const selector = await screen.findByLabelText(/target cluster leader/i);
    await user.selectOptions(selector, '5');
    await user.click(screen.getByRole('button', { name: /upload to leader 5/i }));

    await waitFor(() => {
      expect(baseProps.onUploadCurrentTrajectory).toHaveBeenCalledWith(5);
    });

    expect(await screen.findByText(/leader csv uploaded/i)).toBeInTheDocument();
    expect(screen.getByText(/cluster ready/i)).toBeInTheDocument();
  });

  it('directs the user to swarm design when no leaders are available', async () => {
    const user = userEvent.setup();

    getSwarmClusterStatus.mockResolvedValue({ clusters: [] });

    render(<SwarmTrajectoryTransferDialog {...baseProps} />);

    expect(await screen.findByText(/no top-level swarm leaders are available yet/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /open swarm design/i }));

    expect(baseProps.onOpenSwarmDesign).toHaveBeenCalledTimes(1);
  });
});
