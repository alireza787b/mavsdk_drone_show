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
    bodyClass: `theme-${theme}`,

    // Used by plotting libraries that require explicit runtime colors.
    getThemeColor: (lightColor, darkColor) => isDark ? darkColor : lightColor,

    // Accessibility
    preferredColorScheme: isDark ? 'dark' : 'light',

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
  }), [theme, themePreference, systemTheme, isDark]);

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

export default useTheme;
