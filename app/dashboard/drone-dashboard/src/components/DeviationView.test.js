import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import DeviationView from './DeviationView';
jest.mock('react-plotly.js', () => props => <div data-testid="launch-plot">{props.layout.title.text}</div>);
test('unknown geometry summary stays unknown; zero latitude/longitude is a valid origin', () => {
  render(<DeviationView drones={[{ hw_id: '1', pos_id: '1' }]} origin={{ lat: 0, lon: 0 }} trajectoryPositionsByPosId={{ '1': { x: 0, y: 0 } }} />);
  expect(screen.getByTestId('launch-plot')).toBeInTheDocument();
  expect(screen.getByText('—/—')).toBeInTheDocument();
  expect(screen.queryByText('0.00m')).not.toBeInTheDocument();
  expect(screen.queryByText(/single source of truth|last updated/i)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Current positions' }));
  expect(screen.getByTestId('launch-plot')).toHaveTextContent('Expected launch positions');
});
test('measured summary and refresh remain available without duplicate legend blocks', () => {
  const refresh = jest.fn();
  render(<DeviationView drones={[]} origin={{ lat: 35, lon: 51 }} onRefresh={refresh}
    deviationData={{ summary: { online: 2, within_threshold: 1, errors: 0, warnings: 1, worst_deviation: 4.25 } }} />);
  expect(screen.getByText('1/2')).toBeInTheDocument();
  expect(screen.getByText('4.3 m')).toBeInTheDocument();
  expect(screen.getByText('Plot key').closest('details')).not.toHaveAttribute('open');
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
  expect(refresh).toHaveBeenCalledTimes(1);
});
