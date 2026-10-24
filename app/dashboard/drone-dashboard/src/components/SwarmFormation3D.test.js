import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { EditableAircraft } from './SwarmFormation3D';

const mockReset = jest.fn();
const mockAttachments = [];
jest.mock('@react-three/fiber', () => ({ Canvas: () => null, useThree: jest.fn() }));
jest.mock('@react-three/drei', () => {
  const React = require('react');
  return {
    Html: () => null, Line: () => null, OrbitControls: () => null,
    TransformControls: React.forwardRef(({ onMouseDown, onMouseUp, onObjectChange, object, children }, ref) => {
      mockAttachments.push(object);
      React.useImperativeHandle(ref, () => ({ object: { position: { x: 5, y: 8, z: -10 } }, reset: mockReset }));
      return <div data-testid="gizmo" data-explicit-object={Boolean(object)} data-has-children={Boolean(children)}>
        <button onClick={onMouseDown}>Begin</button><button onClick={onObjectChange}>Move</button>
        <button onClick={onMouseUp}>End</button>{children}
      </div>;
    }),
  };
});

function setup(props = {}) {
  const callbacks = { onAssignmentChange: jest.fn(), onEditBegin: jest.fn(), onEditEnd: jest.fn() };
  render(<EditableAircraft assignment={{ hw_id: '2', follow: '1', frame: 'body' }}
    position={{ east: 2, up: 3, north: 6 }} parentPosition={{ north: 6, east: 2, up: 3 }}
    previewHeadings={{ 1: 90 }} {...callbacks} {...props}><span>Aircraft</span></EditableAircraft>);
  return callbacks;
}

beforeEach(() => { jest.clearAllMocks(); mockAttachments.length = 0; });

test('3D handles use the aircraft position, convert axes and emit only deliberate drag edits', () => {
  const callbacks = setup();
  expect(screen.getByText('Aircraft').parentElement.getAttribute('position')).toBe('2,3,-6');
  expect(screen.getByTestId('gizmo').dataset.explicitObject).toBe('true');
  expect(screen.getByTestId('gizmo').dataset.hasChildren).toBe('false');
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

test('3D body-view handles inverse-transform through view heading then parent heading', () => {
  const callbacks = setup({ viewFrame: 'body', viewHeading: 90 });
  const rendered = screen.getByText('Aircraft').parentElement.getAttribute('position').split(',').map(Number);
  expect(rendered[0]).toBeCloseTo(-6); expect(rendered[1]).toBe(3); expect(rendered[2]).toBeCloseTo(-2);
  fireEvent.click(screen.getByText('Begin'));
  fireEvent.click(screen.getByText('Move'));
  const patch = callbacks.onAssignmentChange.mock.calls[0][1];
  // Handle (Right=5, Up=8, Forward=10) => world N=-5,E=10,U=8.
  // Parent N=6,E=2,U=3, parent heading=90 => Forward=8,Right=11,Up=5.
  expect(patch.offset_x).toBeCloseTo(8); expect(patch.offset_y).toBeCloseTo(11); expect(patch.offset_z).toBe(5);
  fireEvent.click(screen.getByText('End'));
  expect(callbacks.onEditEnd).toHaveBeenCalledWith({ cancelled: false });
});

test('offset and identity rerenders preserve the explicit handle attachment', () => {
  const common = { assignment: { hw_id: '2', follow: '1', frame: 'ned' }, parentPosition: { north: 0, east: 0, up: 0 }, previewHeadings: {}, onAssignmentChange: jest.fn() };
  const { rerender } = render(<EditableAircraft {...common} position={{ north: 6, east: 0, up: 0 }}><span>Before</span></EditableAircraft>);
  const attachment = mockAttachments[0];
  fireEvent.click(screen.getByText('Begin'));
  rerender(<EditableAircraft {...common} position={{ north: 7, east: 1, up: 1 }}><span>Renamed aircraft</span></EditableAircraft>);
  expect(mockAttachments[mockAttachments.length - 1]).toBe(attachment);
  fireEvent.click(screen.getByText('Move'));
  expect(common.onAssignmentChange).toHaveBeenCalledTimes(1);
});
