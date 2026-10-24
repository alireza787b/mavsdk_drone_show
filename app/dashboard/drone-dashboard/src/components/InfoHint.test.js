import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import InfoHint from './InfoHint';

test('context help supports hover, keyboard focus/Escape and click', () => {
  render(<InfoHint icon="?" hoverable label="Frame help" content="Body follows leader heading" />);
  const button = screen.getByRole('button', { name: 'Frame help' });
  fireEvent.mouseEnter(button.parentElement);
  expect(screen.getByRole('tooltip')).toHaveTextContent('Body follows leader heading');
  fireEvent.mouseLeave(button.parentElement);
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  fireEvent.focus(button); expect(screen.getByRole('tooltip')).toBeInTheDocument();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  fireEvent.click(button); expect(screen.getByRole('tooltip')).toBeInTheDocument();
  fireEvent.pointerDown(document.body); expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
});
