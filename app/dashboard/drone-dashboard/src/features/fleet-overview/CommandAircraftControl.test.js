import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import CommandAircraftControl from './CommandAircraftControl';

const review = { unresolvedIds: [], hiddenIds: [] };
const setup = (overrides = {}) => {
  const props = { ids: ['1', '2'], aircraft: [{ id: '1', label: 'ALPHA' }], review,
    onOpen: jest.fn(), onShowRecipients: jest.fn(), ...overrides };
  render(<CommandAircraftControl {...props} />);
  return props;
};

test('recipient identity and count remain visible and accessible with identity fallback', () => {
  const props = setup();
  const button = screen.getByRole('button', { name: 'Choose command aircraft' });
  expect(button).toHaveTextContent('ALPHA, H2');
  expect(button).toHaveAttribute('data-recipient-count', '2');
  expect(button).toHaveAccessibleDescription('2 command aircraft: ALPHA, H2');
  fireEvent.click(button);
  expect(props.onOpen).toHaveBeenCalledTimes(1);
});

test('large selections have a bounded visual summary and complete accessible description', () => {
  setup({ ids: Array.from({ length: 100 }, (_, index) => String(index + 1)) });
  const button = screen.getByRole('button', { name: 'Choose command aircraft' });
  expect(button).toHaveTextContent('ALPHA, H2 +98');
  expect(button).toHaveAttribute('data-recipient-count', '100');
  expect(button).toHaveAccessibleDescription(/H100$/);
});

test('empty selection is explicit; hidden map recipients only request a display change', () => {
  const props = setup({ ids: [], map: true, review: { ...review, hiddenIds: ['1'] } });
  expect(screen.getByRole('button', { name: 'Choose command aircraft' })).toHaveAccessibleDescription('0 command aircraft: None');
  fireEvent.click(screen.getByRole('button', { name: 'Show 1 command aircraft outside this map' }));
  expect(props.onShowRecipients).toHaveBeenCalledTimes(1);
  expect(props.onOpen).not.toHaveBeenCalled();
});

test('a flight review locks both ways into recipient editing', () => {
  const props = setup({ disabled: true, review: { ...review, unresolvedIds: ['2'] } });
  expect(screen.getByRole('button', { name: 'Choose command aircraft' })).toBeDisabled();
  const missing = screen.getByRole('button', { name: 'Review missing command aircraft' });
  expect(missing).toBeDisabled();
  fireEvent.click(missing);
  expect(props.onOpen).not.toHaveBeenCalled();
});
