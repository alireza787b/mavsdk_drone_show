import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { EditableAircraft } from './SwarmFormation3D';

const mockReset = jest.fn();
jest.mock('@react-three/fiber', () => ({ Canvas: () => null, useThree: jest.fn() }));
jest.mock('@react-three/drei', () => {
  const React = require('react');
  return {
    Html: () => null, Line: () => null, OrbitControls: () => null,
    TransformControls: React.forwardRef(({ onMouseDown, onMouseUp, onObjectChange, position, children }, ref) => {
      React.useImperativeHandle(ref, () => ({ object: { position: { x: 5, y: 8, z: -10 } }, reset: mockReset }));
      return <div data-testid="gizmo" data-position={JSON.stringify(position)}>
        <button onClick={onMouseDown}>Begin</button><button onClick={onObjectChange}>Move</button>
        <button onClick={onMouseUp}>End</button>{children}
      </div>;
    }),
  };
});

function setup() {
  const callbacks = { onAssignmentChange: jest.fn(), onEditBegin: jest.fn(), onEditEnd: jest.fn() };
  render(<EditableAircraft assignment={{ hw_id: '2', follow: '1', frame: 'body' }}
    position={{ east: 2, up: 3, north: 6 }} parentPosition={{ north: 6, east: 2, up: 3 }}
    previewHeadings={{ 1: 90 }} {...callbacks}><span>Aircraft</span></EditableAircraft>);
  return callbacks;
}

beforeEach(() => jest.clearAllMocks());

test('3D handles use the aircraft position, convert axes and emit only deliberate drag edits', () => {
  const callbacks = setup();
  expect(screen.getByTestId('gizmo').dataset.position).toBe('[2,3,-6]');
  fireEvent.click(screen.getByText('Move'));
  expect(callbacks.onAssignmentChange).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('Begin'));
  fireEvent.click(screen.getByText('Move'));
  const [id, patch] = callbacks.onAssignmentChange.mock.calls[0];
  expect(id).toBe('2');
  expect(patch.offset_x).toBeCloseTo(3);
  expect(patch.offset_y).toBeCloseTo(-4);
  expect(patch.offset_z).toBe(5);
  fireEvent.click(screen.getByText('End'));
  expect(callbacks.onEditBegin).toHaveBeenCalledTimes(1);
  expect(callbacks.onEditEnd).toHaveBeenCalledWith({ cancelled: false });
});

test('Escape cancels the gesture once; later pointer release cannot commit it', () => {
  const callbacks = setup();
  fireEvent.click(screen.getByText('Begin'));
  fireEvent.keyDown(window, { key: 'Escape' });
  fireEvent.click(screen.getByText('End'));
  expect(mockReset).toHaveBeenCalledTimes(1);
  expect(callbacks.onEditEnd).toHaveBeenCalledTimes(1);
  expect(callbacks.onEditEnd).toHaveBeenCalledWith({ cancelled: true });
});

test('interrupted pointer drag cancels rather than saving incomplete movement', () => {
  const callbacks = setup();
  fireEvent.click(screen.getByText('Begin'));
  fireEvent(window, new Event('pointercancel'));
  expect(callbacks.onEditEnd).toHaveBeenCalledWith({ cancelled: true });
});
