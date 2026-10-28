import React from 'react';
import { render, screen } from '@testing-library/react';
import ShowPlotImage from './ShowPlotImage';

let mockTheme = 'dark';
jest.mock('../contexts/ThemeContext', () => ({ useTheme: () => ({ theme: mockTheme }) }));
jest.mock('../services/gcsApiService', () => ({ buildShowPlotUrl: (name) => `/plots/${name}` }));

test('shared renderer reacts to theme changes without filters or gallery duplicates', () => {
  const plots = { revision: '123', variants: { 'combined.jpg': { light: 'combined.jpg', dark: 'combined_dark.jpg' } } };
  const { rerender } = render(<ShowPlotImage filename="combined.jpg" plots={plots} alt="Paths" />);
  expect(screen.getByAltText('Paths')).toHaveAttribute('src', '/plots/combined_dark.jpg?revision=123');
  mockTheme = 'light';
  rerender(<ShowPlotImage filename="combined.jpg" plots={plots} alt="Paths" />);
  expect(screen.getByAltText('Paths')).toHaveAttribute('src', '/plots/combined.jpg?revision=123');
  expect(screen.getByAltText('Paths').style.filter).toBe('');
});

test('legacy manifest does not request nonexistent dark images', () => {
  mockTheme = 'dark';
  render(<ShowPlotImage filename="legacy.jpg" alt="Legacy" />);
  expect(screen.getByAltText('Legacy')).toHaveAttribute('src', '/plots/legacy.jpg');
});
