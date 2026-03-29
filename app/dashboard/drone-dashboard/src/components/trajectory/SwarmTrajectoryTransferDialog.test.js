import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import SwarmTrajectoryTransferDialog from './SwarmTrajectoryTransferDialog';

const renderDialog = (overrides = {}) => {
  const props = {
    isOpen: true,
    onClose: jest.fn(),
    onSubmit: jest.fn(),
    clusters: [
      {
        leader_id: 1,
        follower_ids: [2, 3],
        follower_count: 2,
        ready: true,
        leader_uploaded: true,
      },
      {
        leader_id: 5,
        follower_ids: [6],
        follower_count: 1,
        ready: false,
        leader_uploaded: true,
      },
    ],
    loading: false,
    submitting: false,
    selectedLeaderId: 1,
    onSelectLeaderId: jest.fn(),
    error: '',
    successMessage: '',
    onOpenSwarmTrajectory: jest.fn(),
    onOpenSwarmDesign: jest.fn(),
    trajectoryName: 'ridge-line-pass',
    waypointCount: 4,
    totalDistance: 1250,
    totalTime: 92,
    missionReadiness: {
      blockers: [],
      advisories: [],
      notes: [],
      posture: {
        tone: 'success',
        label: 'Ready to process',
        summary: 'This path is internally consistent and ready to assign to a leader cluster for swarm processing.',
        transferLabel: 'Assign to Cluster',
      },
    },
    ...overrides,
  };

  return {
    ...render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <SwarmTrajectoryTransferDialog {...props} />
      </MemoryRouter>
    ),
    props,
  };
};

describe('SwarmTrajectoryTransferDialog', () => {
  it('renders cluster readiness and lets the operator select a different leader', () => {
    const { props } = renderDialog();

    expect(screen.getByText('ridge-line-pass')).toBeInTheDocument();
    expect(screen.getByText('1.25 km')).toBeInTheDocument();
    expect(screen.getByText('1m 32s')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Leader 5'));

    expect(props.onSelectLeaderId).toHaveBeenCalledWith(5);
  });

  it('submits when the selected leader is ready to send', () => {
    const { props } = renderDialog({ selectedLeaderId: 5 });

    fireEvent.click(screen.getByRole('button', { name: /assign to cluster/i }));

    expect(props.onSubmit).toHaveBeenCalledTimes(1);
  });

  it('shows draft posture and adjusted button labeling when mission blockers exist', () => {
    renderDialog({
      missionReadiness: {
        blockers: [{ code: 'time_conflict', tone: 'danger', text: '1 timing conflict breaks mission chronology.' }],
        advisories: [],
        notes: [],
        posture: {
          tone: 'danger',
          label: 'Draft only',
          summary: 'This path can be uploaded for draft review, but launch blockers still need correction before processing or execution.',
          transferLabel: 'Assign Draft to Cluster',
        },
      },
    });

    expect(screen.getAllByText('Draft only').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /assign draft to cluster/i })).toBeInTheDocument();
    expect(screen.getAllByText(/launch blockers/i).length).toBeGreaterThan(0);
  });

  it('directs the user to swarm design when no leaders are available', () => {
    const { props } = renderDialog({
      clusters: [],
      selectedLeaderId: '',
    });

    expect(screen.getByText(/no top leaders are available yet/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /open swarm design/i }));

    expect(props.onOpenSwarmDesign).toHaveBeenCalledTimes(1);
  });

  it('opens the swarm trajectory workspace after a successful upload', () => {
    const { props } = renderDialog({
      successMessage: 'Trajectory uploaded for Leader 1. Next step: process the swarm formation.',
    });

    fireEvent.click(screen.getByRole('button', { name: /open swarm trajectory/i }));

    expect(props.onOpenSwarmTrajectory).toHaveBeenCalledTimes(1);
  });
});
