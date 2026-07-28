import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import DroneCard from './DroneCard';

const baseDrone = {
  hw_id: '2',
  title: 'Drone 2',
  subtitle: 'Slot 2',
  alias: '',
  follow: '1',
  followTargetExists: true,
  followTargetPosId: 1,
  directFollowers: [],
  offsetSummary: 'North -6.0 m, East 0.0 m, Up 0.0 m',
  frameLabel: 'Geographic NED',
  frameDescription: 'North, East, Up offsets in meters.',
  axisLabels: { x: 'North', y: 'East', z: 'Up' },
  role: 'follower',
  roleLabel: 'Follower',
  roleSummary: 'Follows Drone 1',
  warnings: [],
  hasWarnings: false,
  isRoleSwap: false,
};

function renderDroneCard(overrides = {}) {
  const onAssignmentChange = jest.fn();
  const props = {
    drone: baseDrone,
    draftAssignment: {
      hw_id: '2',
      follow: '1',
      frame: 'ned',
      offset_x: '-6',
      offset_y: '0',
      offset_z: '0',
    },
    followOptions: [
      { value: '1', label: 'Drone 1' },
      { value: '2', label: 'Drone 2' },
    ],
    onSelect: jest.fn(),
    onToggleExpand: jest.fn(),
    onAssignmentChange,
    isSelected: true,
    isExpanded: true,
    isDirty: true,
    ...overrides,
  };
  render(<DroneCard {...props} />);
  return { onAssignmentChange };
}

describe('DroneCard', () => {
  test('uses mobile-friendly signed decimal offset inputs', () => {
    const { onAssignmentChange } = renderDroneCard();

    const northInput = screen.getByLabelText(/north offset in meters/i);
    expect(northInput).toHaveAttribute('type', 'text');
    expect(northInput).toHaveAttribute('inputmode', 'decimal');
    expect(northInput).toHaveAttribute('pattern', '-?[0-9]*[.]?[0-9]*');
    expect(northInput).toHaveValue('-6');

    fireEvent.change(northInput, { target: { value: '-7.5' } });
    expect(onAssignmentChange).toHaveBeenCalledWith('2', { offset_x: '-7.5' });
  });
});
