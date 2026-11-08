import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import SwarmFormationSource from './SwarmFormationSource';

test('source actions prepare a draft and are not flight-mode toggles', () => {
  const saved = jest.fn(), capture = jest.fn();
  render(<SwarmFormationSource onSaved={saved} onCapture={capture} savedCurrent />);
  const source = screen.getByRole('group', { name: 'Formation starting point' });
  expect(source).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Saved plan' }));
  fireEvent.click(screen.getByRole('button', { name: 'Capture positions' }));
  expect(saved).toHaveBeenCalledTimes(1);
  expect(capture).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Saved plan' })).not.toHaveAttribute('aria-pressed');
});

test('Operate uses review links and disables unavailable capture', () => {
  render(<SwarmFormationSource savedHref="/swarm-design?plan=saved" captureHref="/swarm-design?capture=1" captureDisabled />);
  expect(screen.getByRole('link', { name: 'Saved plan' })).toHaveAttribute('href', '/swarm-design?plan=saved');
  const capture = screen.getByLabelText('Capture positions');
  expect(capture).toHaveAttribute('aria-disabled', 'true');
  expect(capture).not.toHaveAttribute('href');
});
