import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
    const user = userEvent.setup();
    const { props } = renderToolbar({ canSendToSwarm: true });

    await user.click(screen.getByRole('button', { name: /send to swarm/i }));

    expect(props.onSendToSwarm).toHaveBeenCalledTimes(1);
  });
});
