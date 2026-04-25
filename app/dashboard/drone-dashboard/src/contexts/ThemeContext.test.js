import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { ThemeProvider, THEMES, useTheme } from './ThemeContext';

function ThemeProbe() {
  const { isDark, setTheme, theme, themePreference } = useTheme();
  return (
    <div>
      <div data-testid="theme-state">{`${theme}:${themePreference}:${isDark ? 'dark' : 'light'}`}</div>
      <button type="button" onClick={() => setTheme(THEMES.LIGHT)}>Light</button>
      <button type="button" onClick={() => setTheme(THEMES.DARK)}>Dark</button>
    </div>
  );
}

describe('ThemeProvider', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    document.documentElement.className = '';
    document.documentElement.style.cssText = '';
    document.body.removeAttribute('data-theme');
    document.body.className = '';
    document.body.style.cssText = '';

    const existingMeta = document.querySelector('meta[name="theme-color"]');
    if (existingMeta) {
      existingMeta.remove();
    }
    const meta = document.createElement('meta');
    meta.setAttribute('name', 'theme-color');
    document.head.appendChild(meta);
  });

  test('applies canonical light and dark theme attributes from context', () => {
    document.documentElement.style.setProperty('--app-meta-theme-color', 'rgb(10, 20, 30)');
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    );

    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(screen.getByTestId('theme-state')).toHaveTextContent('dark:auto:dark');
    expect(document.querySelector('meta[name="theme-color"]')).toHaveAttribute('content', 'rgb(10, 20, 30)');

    fireEvent.click(screen.getByRole('button', { name: 'Light' }));
    expect(document.documentElement).toHaveAttribute('data-theme', 'light');
    expect(document.body).toHaveAttribute('data-theme', 'light');
    expect(localStorage.getItem('drone-dashboard-theme')).toBe('light');

    fireEvent.click(screen.getByRole('button', { name: 'Dark' }));
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(document.body).toHaveAttribute('data-theme', 'dark');
  });
});
