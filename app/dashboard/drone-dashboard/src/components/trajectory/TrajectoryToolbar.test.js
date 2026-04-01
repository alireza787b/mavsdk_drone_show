import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import TrajectoryToolbar from './TrajectoryToolbar';

const renderToolbar = (overrides = {}) => {
  const props = {
    isAddingWaypoint: false,
    onToggleAddWaypoint: jest.fn(),
    onClearTrajectory: jest.fn(),
    onExportTrajectory: jest.fn(),
    showTerrain: false,
    onToggleTerrain: jest.fn(),
    sceneMode: '2D',
    onSceneModeChange: jest.fn(),
    waypointCount: 3,
    canUndo: false,
    canRedo: false,
    onUndo: jest.fn(),
    onRedo: jest.fn(),
    onSave: jest.fn(),
    onLoad: jest.fn(),
    onSendToSwarm: jest.fn(),
    canSendToSwarm: false,
    missionReadiness: {
      posture: {
        tone: 'success',
        label: 'Ready to process',
        summary: 'This path is ready to assign to a leader cluster.',
        transferLabel: 'Assign to Cluster',
      },
    },
    saveStatus: { saved: true, autoSaveTime: null },
    trajectoryName: 'mission-pass',
    ...overrides,
  };

  return {
    ...render(<TrajectoryToolbar {...props} />),
    props,
  };
};

describe('TrajectoryToolbar', () => {
  it('shows disabled cluster-assignment action when no mission handoff is allowed', () => {
    renderToolbar({ canSendToSwarm: false });

    expect(screen.getByRole('button', { name: /assign to cluster/i })).toBeDisabled();
  });

  it('calls send callback when enabled', async () => {
    const { props } = renderToolbar({ canSendToSwarm: true });

    fireEvent.click(screen.getByRole('button', { name: /assign to cluster/i }));

    expect(props.onSendToSwarm).toHaveBeenCalledTimes(1);
  });

  it('surfaces handoff posture and uses the readiness-specific transfer label', () => {
    renderToolbar({
      canSendToSwarm: true,
      missionReadiness: {
        posture: {
          tone: 'warning',
          label: 'Review required',
          summary: 'Operator review is still required before processing and mission launch.',
          transferLabel: 'Assign for Review',
        },
      },
    });

    expect(screen.getByText('Handoff')).toBeInTheDocument();
    expect(screen.getByText('Review required')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /assign for review/i })).toBeInTheDocument();
  });

  it('shows shortcuts in an inline popover instead of a blocking alert', () => {
    renderToolbar();

    fireEvent.click(screen.getByRole('button', { name: /show planner shortcuts/i }));

    expect(screen.getByRole('dialog', { name: /planner shortcuts/i })).toBeInTheDocument();
    expect(screen.getByText(/toggle add waypoint mode/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /close planner shortcuts/i }));

    expect(screen.queryByRole('dialog', { name: /planner shortcuts/i })).not.toBeInTheDocument();
  });

  it('replaces dead terrain/view controls with a 2D fallback note when advanced map controls are unavailable', () => {
    renderToolbar({ terrainControlsAvailable: false });

    expect(screen.queryByRole('button', { name: /terrain/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.getByText('2D fallback')).toBeInTheDocument();
  });
});
