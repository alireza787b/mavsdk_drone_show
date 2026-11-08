import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import SwarmFormationSource from './SwarmFormationSource';

test('source actions prepare a draft and are not flight-mode toggles', () => {
  const plan = jest.fn(), capture = jest.fn();
  render(<SwarmFormationSource onPlan={plan} onCapture={capture} />);
  const source = screen.getByRole('group', { name: 'Formation starting point' });
  expect(source).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Plan formation' }));
  fireEvent.click(screen.getByRole('button', { name: 'Capture positions' }));
  expect(plan).toHaveBeenCalledTimes(1);
  expect(capture).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Plan formation' })).not.toHaveAttribute('aria-pressed');
  expect(screen.queryByRole('button', { name: /Revert/ })).not.toBeInTheDocument();
});

test('Operate uses review links and disables unavailable capture', () => {
  render(<SwarmFormationSource planHref="/swarm-design?tab=formation" captureHref="/swarm-design?capture=1" captureDisabled />);
  expect(screen.getByRole('link', { name: 'Plan formation' })).toHaveAttribute('href', '/swarm-design?tab=formation');
  const capture = screen.getByLabelText('Capture positions');
  expect(capture).toHaveAttribute('aria-disabled', 'true');
  expect(capture).not.toHaveAttribute('href');
});
