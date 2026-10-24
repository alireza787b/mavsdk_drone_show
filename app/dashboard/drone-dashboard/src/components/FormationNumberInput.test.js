import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import FormationNumberInput from './FormationNumberInput';

test('formatting does not mutate data; focus exposes full precision', () => {
  const change = jest.fn();
  render(<FormationNumberInput aria-label="Distance" value={0.920493} onChange={change} />);
  const input = screen.getByRole('spinbutton');
  expect(input).toHaveValue(0.92);
  fireEvent.focus(input); expect(input).toHaveValue(0.920493);
  fireEvent.blur(input); expect(input).toHaveValue(0.92);
  expect(change).not.toHaveBeenCalled();
});
