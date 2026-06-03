import React from 'react';
import { render, screen, within } from '@testing-library/react';

import IdentityDoctrineStrip from './IdentityDoctrineStrip';

describe('IdentityDoctrineStrip', () => {
  test('keeps compact chip details accessible for Smart Swarm', () => {
    render(<IdentityDoctrineStrip surface="swarm-design" className="identity-doctrine-strip--compact" />);

    expect(screen.getByLabelText(/identity rule/i)).toHaveClass('identity-doctrine-strip--compact');
    expect(screen.getByText(/follow chains stay on hardware/i)).toBeInTheDocument();

    const chipGroup = screen.getByLabelText(/identity rule/i);
    expect(within(chipGroup).getByLabelText('P: slot')).toHaveAttribute('title', 'P: slot');
    expect(within(chipGroup).getByLabelText('H: hardware')).toHaveAttribute('title', 'H: hardware');
    expect(within(chipGroup).getByLabelText('Swarm: Follow = H')).toHaveAttribute('title', 'Swarm: Follow = H');
  });
});
