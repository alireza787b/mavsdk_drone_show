import { useContext, useMemo } from 'react';
import ThemeContext, { THEMES } from '../contexts/ThemeContext';

/**
 * Enhanced theme hook with utilities
 */
export const useTheme = () => {
  const context = useContext(ThemeContext);

  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }

  const {
    theme,
    themePreference,
    systemTheme,
    setTheme,
    toggleTheme,
    cycleTheme,
    getThemeInfo,
    isDark,
    isLight
  } = context;

  // Computed values
  const computedValues = useMemo(() => ({
    // Theme state
    isAuto: themePreference === THEMES.AUTO,
    isSystemDark: systemTheme === THEMES.DARK,

    // CSS class helpers
    themeClass: `theme-${theme}`,
    bodyClass: isDark ? 'dark-mode' : 'light-mode',

    // Color utilities
    getThemeColor: (lightColor, darkColor) => isDark ? darkColor : lightColor,

    // Theme-specific values
    backgroundColor: isDark ? '#1f2128' : '#ffffff',
    textColor: isDark ? '#ffffff' : '#333333',
    borderColor: isDark ? '#3a3f4b' : '#e0e0e0',

    // Accessibility
    preferredColorScheme: isDark ? 'dark' : 'light',

    // Theme icon helper
    getThemeIcon: () => {
      if (themePreference === THEMES.AUTO) {
        return 'fa-circle-half-stroke'; // Auto mode icon
      }
      return isDark ? 'fa-moon' : 'fa-sun';
    },

    // Theme label helper
    getThemeLabel: () => {
      switch (themePreference) {
        case THEMES.AUTO:
          return `Auto (${systemTheme})`;
        case THEMES.DARK:
          return 'Dark';
        case THEMES.LIGHT:
          return 'Light';
        default:
          return 'Unknown';
      }
    }
  }), [theme, themePreference, systemTheme, isDark, isLight]);

  return {
    // Core theme state
    theme,
    themePreference,
    systemTheme,
    isDark,
    isLight,

    // Theme actions
    setTheme,
    toggleTheme,
    cycleTheme,
    getThemeInfo,

    // Computed utilities
    ...computedValues
  };
};

/**
 * Hook for theme-aware styling
 */
export const useThemeStyles = () => {
  const { isDark, getThemeColor } = useTheme();

  return {
    isDark,
    getThemeColor,

    // Common theme-aware styles
    cardStyle: {
      backgroundColor: getThemeColor('#ffffff', '#2a2d3a'),
      color: getThemeColor('#333333', '#ffffff'),
      borderColor: getThemeColor('#e0e0e0', '#3a3f4b')
    },

    buttonStyle: {
      backgroundColor: getThemeColor('#007bff', '#00d4ff'),
      color: getThemeColor('#ffffff', '#000000')
    },

    inputStyle: {
      backgroundColor: getThemeColor('#ffffff', '#3a3f4b'),
      color: getThemeColor('#333333', '#ffffff'),
      borderColor: getThemeColor('#d1d5db', '#4a4f5b')
    }
  };
};

/**
 * Hook for CSS variables
 */
export const useThemeVariables = () => {
  const { isDark } = useTheme();

  return useMemo(() => {
    return isDark ? {
      // Dark theme variables
      '--theme-bg-primary': '#1f2128',
      '--theme-bg-secondary': '#2a2d3a',
      '--theme-bg-tertiary': '#3a3f4b',
      '--theme-text-primary': '#ffffff',
      '--theme-text-secondary': '#a2a5b9',
      '--theme-border-primary': '#3a3f4b',
      '--theme-shadow': '0 4px 6px rgba(0, 0, 0, 0.3)'
    } : {
      // Light theme variables
      '--theme-bg-primary': '#ffffff',
      '--theme-bg-secondary': '#f8f9fa',
      '--theme-bg-tertiary': '#e9ecef',
      '--theme-text-primary': '#333333',
      '--theme-text-secondary': '#6c757d',
      '--theme-border-primary': '#dee2e6',
      '--theme-shadow': '0 4px 6px rgba(0, 0, 0, 0.1)'
    };
  }, [isDark]);
};

export default useTheme;