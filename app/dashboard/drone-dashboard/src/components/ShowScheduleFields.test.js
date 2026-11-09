import React from 'react';
import { render, screen } from '@testing-library/react';
import ShowScheduleFields from './ShowScheduleFields';

test('When ready explains synchronized preparation without inventing an immediate flight time', () => {
  render(<ShowScheduleFields value={{ scheduleMode: 'now', timeDelay: 10, selectedDateTime: '' }}
    onChange={jest.fn()} referenceNowMs={Date.now()} />);
  expect(screen.getByRole('option', { name: 'When ready' })).toBeInTheDocument();
  expect(screen.getByText('Synchronized start after aircraft checks')).toBeInTheDocument();
  expect(screen.queryByText(/Immediate on acceptance/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Launch delay')).not.toBeInTheDocument();
});
