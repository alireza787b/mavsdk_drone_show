import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import InfoHint from './InfoHint';

test('context help supports hover, keyboard focus/Escape and click', () => {
  render(<InfoHint icon="?" hoverable label="Frame help" content="Body follows leader heading" />);
  const button = screen.getByRole('button', { name: 'Frame help' });
  fireEvent.mouseEnter(button);
  expect(screen.getByRole('tooltip')).toHaveTextContent('Body follows leader heading');
  fireEvent.mouseLeave(button);
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  fireEvent.focus(button);
  expect(screen.getByRole('tooltip')).toBeInTheDocument();
  fireEvent.mouseLeave(button);
  expect(screen.getByRole('tooltip')).toBeInTheDocument();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  fireEvent.click(button); expect(screen.getByRole('tooltip')).toBeInTheDocument();
  fireEvent.pointerDown(document.body); expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
});

test('a tap keeps help open when the browser focuses the button before clicking', () => {
  render(<InfoHint hoverable label="Scope help" content="Search preserves the update scope." />);
  const button = screen.getByRole('button', { name: 'Scope help' });
  fireEvent.pointerDown(button, { pointerType: 'touch' });
  fireEvent.focus(button);
  fireEvent.click(button);
  expect(button).toHaveAttribute('aria-expanded', 'true');
  expect(button).toHaveAccessibleDescription('Search preserves the update scope.');
  expect(screen.getByRole('tooltip')).toBeVisible();

  fireEvent.click(button);
  expect(button).toHaveAttribute('aria-expanded', 'false');
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
});

test('a click-only hint stays closed on focus and toggles on click', () => {
  render(<InfoHint label="Scope help" content="Search preserves the update scope." />);
  const button = screen.getByRole('button', { name: 'Scope help' });
  fireEvent.focus(button);
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  fireEvent.click(button);
  expect(screen.getByRole('tooltip')).toBeVisible();
  fireEvent.click(button);
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
});
