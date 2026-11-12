import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import MapAircraftInspector from './MapAircraftInspector';
jest.mock('./TacticalDroneCard', () => ({ drone }) => <div>Aircraft {drone.hw_id}</div>);

test('one non-modal inspector owns map details and closes on its own Escape', () => {
  const onClose=jest.fn();
  render(<MapAircraftInspector drone={{hw_id:'2'}} onClose={onClose} />);
  const panel=screen.getByRole('complementary',{name:'Aircraft inspector'});
  expect(screen.getByText('Aircraft 2')).toBeInTheDocument();
  expect(screen.queryByText('No current map position')).not.toBeInTheDocument();
  fireEvent.keyDown(panel,{key:'Escape'});
  expect(onClose).toHaveBeenCalledTimes(1);
});
test('an unmapped selected aircraft remains inspectable without an invented map marker', () => {
  render(<MapAircraftInspector drone={{hw_id:'2'}} onClose={jest.fn()} noMapFix />);
  expect(screen.getByText('No current map position')).toBeInTheDocument();
});
