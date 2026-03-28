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
  it('shows disabled send-to-swarm action when no mission handoff is allowed', () => {
    renderToolbar({ canSendToSwarm: false });

    expect(screen.getByRole('button', { name: /send to swarm/i })).toBeDisabled();
  });

  it('calls send callback when enabled', async () => {
    const { props } = renderToolbar({ canSendToSwarm: true });

    fireEvent.click(screen.getByRole('button', { name: /send to swarm/i }));

    expect(props.onSendToSwarm).toHaveBeenCalledTimes(1);
  });

  it('shows shortcuts in an inline popover instead of a blocking alert', () => {
    renderToolbar();

    fireEvent.click(screen.getByRole('button', { name: /show planner shortcuts/i }));

    expect(screen.getByRole('dialog', { name: /planner shortcuts/i })).toBeInTheDocument();
    expect(screen.getByText(/toggle add waypoint mode/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /close planner shortcuts/i }));

    expect(screen.queryByRole('dialog', { name: /planner shortcuts/i })).not.toBeInTheDocument();
  });
});
