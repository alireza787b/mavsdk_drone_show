import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';

// Theme types
export const THEMES = {
  LIGHT: 'light',
  DARK: 'dark',
  AUTO: 'auto'
};

// Create theme context
const ThemeContext = createContext();

// Custom hook for using theme
export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};

// Utility functions
const getSystemTheme = () => {
  if (typeof window !== 'undefined') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? THEMES.DARK : THEMES.LIGHT;
  }
  return THEMES.DARK; // Default fallback
};

const getStoredTheme = () => {
  if (typeof window !== 'undefined') {
    return localStorage.getItem('drone-dashboard-theme') || THEMES.AUTO;
  }
  return THEMES.AUTO;
};

const setStoredTheme = (theme) => {
  if (typeof window !== 'undefined') {
    localStorage.setItem('drone-dashboard-theme', theme);
  }
};

// Apply theme to document
const applyTheme = (theme) => {
  if (typeof document !== 'undefined') {
    const root = document.documentElement;

    // Remove existing theme classes
    root.classList.remove('theme-light', 'theme-dark');

    // Add new theme class
    root.classList.add(`theme-${theme}`);

    // Set data attribute for CSS selectors
    root.setAttribute('data-theme', theme);

    // Update meta theme-color for mobile browsers
    const metaThemeColor = document.querySelector('meta[name="theme-color"]');
    if (metaThemeColor) {
      metaThemeColor.setAttribute('content',
        theme === THEMES.DARK ? '#1f2128' : '#ffffff'
      );
    }
  }
};

export const ThemeProvider = ({ children }) => {
  const [themePreference, setThemePreference] = useState(getStoredTheme);
  const [systemTheme, setSystemTheme] = useState(getSystemTheme);

  // Calculate effective theme
  const effectiveTheme = themePreference === THEMES.AUTO ? systemTheme : themePreference;

  // Listen for system theme changes
  useEffect(() => {
    if (typeof window === 'undefined') return;

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = (e) => {
      setSystemTheme(e.matches ? THEMES.DARK : THEMES.LIGHT);
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  // Apply theme when it changes
  useEffect(() => {
    applyTheme(effectiveTheme);
  }, [effectiveTheme]);

  // Theme setter with persistence
  const setTheme = useCallback((newTheme) => {
    if (Object.values(THEMES).includes(newTheme)) {
      setThemePreference(newTheme);
      setStoredTheme(newTheme);
    }
  }, []);

  // Toggle between light and dark (skipping auto)
  const toggleTheme = useCallback(() => {
    const newTheme = effectiveTheme === THEMES.DARK ? THEMES.LIGHT : THEMES.DARK;
    setTheme(newTheme);
  }, [effectiveTheme, setTheme]);

  // Cycle through all themes including auto
  const cycleTheme = useCallback(() => {
    const themes = [THEMES.LIGHT, THEMES.DARK, THEMES.AUTO];
    const currentIndex = themes.indexOf(themePreference);
    const nextIndex = (currentIndex + 1) % themes.length;
    setTheme(themes[nextIndex]);
  }, [themePreference, setTheme]);

  // Get theme info
  const getThemeInfo = useCallback(() => {
    return {
      preference: themePreference,
      effective: effectiveTheme,
      system: systemTheme,
      isAuto: themePreference === THEMES.AUTO,
      isDark: effectiveTheme === THEMES.DARK,
      isLight: effectiveTheme === THEMES.LIGHT
    };
  }, [themePreference, effectiveTheme, systemTheme]);

  const value = {
    theme: effectiveTheme,
    themePreference,
    systemTheme,
    setTheme,
    toggleTheme,
    cycleTheme,
    getThemeInfo,
    // Legacy compatibility
    isDark: effectiveTheme === THEMES.DARK,
    isLight: effectiveTheme === THEMES.LIGHT
  };

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
};

export default ThemeContext;