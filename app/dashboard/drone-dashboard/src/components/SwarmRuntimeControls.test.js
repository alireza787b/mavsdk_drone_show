import React from 'react';
import { render, screen } from '@testing-library/react';
import SwarmRuntimeControls from './SwarmRuntimeControls';
jest.mock('./SwarmOperations', () => ({ showMap }) => <div>{showMap ? 'Shared operations with live map' : 'Shared operations'}</div>);
test('the dedicated page shares the operator workflow rather than design selection', () => {
  render(<SwarmRuntimeControls selectedDroneId="2" selectedClusterId="all" />);
  expect(screen.getByText('Shared operations with live map')).toBeInTheDocument();
});
