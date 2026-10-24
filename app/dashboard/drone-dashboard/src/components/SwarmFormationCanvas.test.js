import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import SwarmFormationCanvas from './SwarmFormationCanvas';

const assignments = [
  { hw_id: '1', follow: '0', offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
  { hw_id: '2', follow: '1', offset_x: 6, offset_y: 2, offset_z: 1, frame: 'ned' },
];
function setup(props = {}) {
  const onAssignmentChange = jest.fn(), onEditBegin = jest.fn(), onEditEnd = jest.fn();
  render(<SwarmFormationCanvas assignments={assignments} configData={[]} clusterId="1" selectedId="2" onAssignmentChange={onAssignmentChange} onEditBegin={onEditBegin} onEditEnd={onEditEnd} {...props} />);
  return { onAssignmentChange, onEditBegin, onEditEnd };
}
test('keyboard nudge is one edit transaction and preserves existing offset', () => {
  const { onAssignmentChange, onEditBegin, onEditEnd } = setup();
  fireEvent.keyDown(screen.getByRole('button', { name: 'Drone 2, formation position' }), { key: 'ArrowUp' });
  expect(onEditBegin).toHaveBeenCalledTimes(1);
  expect(onAssignmentChange).toHaveBeenCalledWith('2', { offset_x: 6.1, offset_y: 2, offset_z: 1 });
  expect(onEditEnd).toHaveBeenCalledWith({ cancelled: false });
});
test('side keyboard nudge changes height rather than North', () => {
  const { onAssignmentChange } = setup({ plane: 'east-up' });
  fireEvent.keyDown(screen.getByRole('button', { name: 'Drone 2, formation position' }), { key: 'ArrowUp', shiftKey: true });
  expect(onAssignmentChange).toHaveBeenCalledWith('2', { offset_x: 6, offset_y: 2, offset_z: 2 });
});
test('root leader does not move through arrow keys', () => {
  const { onAssignmentChange } = setup();
  fireEvent.keyDown(screen.getByRole('button', { name: 'Drone 1, leader origin' }), { key: 'ArrowUp' });
  expect(onAssignmentChange).not.toHaveBeenCalled();
});
test('canvas zoom never modifies the formation', () => {
  const { onAssignmentChange } = setup();
  fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
  fireEvent.click(screen.getByRole('button', { name: 'Fit' }));
  expect(onAssignmentChange).not.toHaveBeenCalled();
});

test('pointer drag uses SVG screen transform and Escape restores the gesture start', () => {
  const previousPointerEvent = window.PointerEvent;
  window.PointerEvent = MouseEvent;
  try {
    const { onAssignmentChange, onEditBegin, onEditEnd } = setup();
    const svg = screen.getByRole('group', { name: 'Editable swarm top view' });
    svg.getScreenCTM = () => ({ inverse: () => ({}) });
    // A letterboxed/scaled SVG must use the screen matrix rather than rect ratios.
    svg.createSVGPoint = () => ({ x: 0, y: 0, matrixTransform() { return { x: this.x / 2, y: this.y / 2 }; } });
    svg.setPointerCapture = jest.fn();
    const follower = screen.getByRole('button', { name: 'Drone 2, formation position' });
    fireEvent.pointerDown(follower, { button: 0, clientX: 200, clientY: 200 });
    fireEvent.pointerMove(svg, { clientX: 240, clientY: 200 });
    expect(onEditBegin).toHaveBeenCalledTimes(1);
    const patch = onAssignmentChange.mock.calls[0][1];
    expect(patch.offset_x).toBe(6);
    expect(patch.offset_y).toBeGreaterThan(2);
    expect(patch.offset_y).toBeLessThan(3);
    fireEvent.keyDown(svg, { key: 'Escape' });
    expect(onAssignmentChange).toHaveBeenLastCalledWith('2', { offset_x: 6, offset_y: 2, offset_z: 1 });
    expect(onEditEnd).toHaveBeenCalledWith({ cancelled: true });
  } finally { window.PointerEvent = previousPointerEvent; }
});
