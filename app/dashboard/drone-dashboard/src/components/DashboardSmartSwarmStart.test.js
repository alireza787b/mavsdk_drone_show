import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import DashboardSmartSwarmStart from './DashboardSmartSwarmStart';
jest.mock('./SwarmOperations', () => () => <div data-testid="shared-swarm-operations" />);
test('opening the card reveals controls without sending a command', () => {
  const onReview = jest.fn();
  const { rerender } = render(<DashboardSmartSwarmStart onReview={onReview} />);
  fireEvent.click(screen.getByRole('button', { name: /^Smart Swarm/ }));
  expect(onReview).toHaveBeenCalledTimes(1);
  rerender(<DashboardSmartSwarmStart review onBack={jest.fn()} />);
  expect(screen.getByTestId('shared-swarm-operations')).toBeInTheDocument();
});
