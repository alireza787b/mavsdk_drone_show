// src/utilities/theme.js
/**
 * Theme configuration for the Drone Dashboard
 * Provides programmatic access to design tokens
 */

export const theme = {
    // Colors
    colors: {
      primary: '#00d4ff',
      primaryHover: '#00a8cc',
      primaryLight: 'rgba(0, 212, 255, 0.1)',
      primaryBorder: 'rgba(0, 212, 255, 0.2)',
      primaryText: '#000000',
      
      // Backgrounds
      bgPrimary: '#1f2128',
      bgSecondary: '#2a2d3a',
      bgTertiary: '#3a3f4b',
      bgQuaternary: '#4a4f5b',
      bgLight: '#f8f9fa',
      bgOverlay: 'rgba(0, 0, 0, 0.75)',
      
      // Text
      textPrimary: '#ffffff',
      textSecondary: '#a2a5b9',
      textTertiary: '#6c757d',
      textMuted: '#495057',
      textInverse: '#000000',
      
      // Status
      success: '#28a745',
      successLight: 'rgba(40, 167, 69, 0.1)',
      successBorder: 'rgba(40, 167, 69, 0.2)',
      
      warning: '#ffc107',
      warningLight: 'rgba(255, 193, 7, 0.1)',
      warningBorder: 'rgba(255, 193, 7, 0.2)',
      warningText: '#856404',
      
      danger: '#dc3545',
      dangerLight: 'rgba(220, 53, 69, 0.1)',
      dangerBorder: 'rgba(220, 53, 69, 0.2)',
      
      info: '#17a2b8',
      infoLight: 'rgba(23, 162, 184, 0.1)',
      infoBorder: 'rgba(23, 162, 184, 0.2)',
      
      // Borders
      borderPrimary: '#3a3f4b',
      borderSecondary: '#4a4f5b',
      borderLight: '#e0e0e0',
      borderFocus: '#00d4ff',
    },
    
    // Typography
    fonts: {
      primary: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Roboto", "Oxygen", "Ubuntu", "Cantarell", sans-serif',
      mono: '"Monaco", "Courier New", "Consolas", monospace'
    },
    
    fontSizes: {
      xs: '0.75rem',    // 12px
      sm: '0.875rem',   // 14px
      base: '0.9rem',   // 14.4px
      md: '1rem',       // 16px
      lg: '1.125rem',   // 18px
      xl: '1.25rem',    // 20px
      '2xl': '1.5rem',  // 24px
      '3xl': '1.875rem' // 30px
    },
    
    fontWeights: {
      light: 300,
      normal: 400,
      medium: 500,
      semibold: 600,
      bold: 700
    },
    
    lineHeights: {
      tight: 1.2,
      normal: 1.4,
      relaxed: 1.6
    },
    
    // Spacing
    spacing: {
      xs: '0.25rem',   // 4px
      sm: '0.5rem',    // 8px
      md: '0.75rem',   // 12px
      base: '1rem',    // 16px
      lg: '1.5rem',    // 24px
      xl: '2rem',      // 32px
      '2xl': '3rem',   // 48px
      '3xl': '4rem'    // 64px
    },
    
    // Border Radius
    borderRadius: {
      sm: '4px',
      base: '6px',
      md: '8px',
      lg: '12px',
      xl: '16px',
      full: '9999px'
    },
    
    // Shadows
    shadows: {
      sm: '0 1px 2px rgba(0, 0, 0, 0.05)',
      base: '0 2px 4px rgba(0, 0, 0, 0.1)',
      md: '0 4px 6px rgba(0, 0, 0, 0.1)',
      lg: '0 10px 15px rgba(0, 0, 0, 0.1)',
      xl: '0 20px 25px rgba(0, 0, 0, 0.1)',
      '2xl': '0 25px 50px rgba(0, 0, 0, 0.25)',
      
      // Dark theme specific
      darkSm: '0 2px 4px rgba(0, 0, 0, 0.2)',
      darkBase: '0 4px 6px rgba(0, 0, 0, 0.3)',
      darkMd: '0 8px 12px rgba(0, 0, 0, 0.3)',
      darkLg: '0 16px 24px rgba(0, 0, 0, 0.4)'
    },
    
    // Transitions
    transitions: {
      fast: '0.15s ease',
      base: '0.2s ease',
      slow: '0.3s ease',
      all: 'all 0.2s ease'
    },
    
    // Z-Index
    zIndex: {
      dropdown: 1000,
      sticky: 1020,
      fixed: 1030,
      modalBackdrop: 1040,
      modal: 1050,
      popover: 1060,
      tooltip: 1070
    },
    
    // Component Specific
    components: {
      button: {
        heights: {
          sm: '32px',
          base: '40px',
          lg: '48px'
        }
      },
      
      input: {
        heights: {
          sm: '32px',
          base: '40px',
          lg: '48px'
        }
      },
      
      panel: {
        widths: {
          sm: '250px',
          base: '300px',
          lg: '400px'
        }
      },
      
      modal: {
        backdropColor: 'rgba(0, 0, 0, 0.75)',
        maxWidth: '500px',
        borderRadius: '12px'
      },
      
      waypoint: {
        colors: {
          start: '#28a745',
          end: '#dc3545',
          default: '#00d4ff',
          selected: '#ffc107',
          warning: '#ff6b6b'
        }
      },
      
      speed: {
        colors: {
          feasible: '#28a745',
          marginal: '#ffc107',
          impossible: '#dc3545'
        }
      },
      
      toolbar: {
        height: '60px',
        bg: '#1f2128',
        border: '#2a2d3a'
      },
      
      map: {
        instructionBg: 'rgba(0, 0, 0, 0.8)',
        trajectoryLineColor: '#00d4ff',
        trajectoryLineWidth: '4px'
      }
    },
    
    // Breakpoints
    breakpoints: {
      sm: '576px',
      md: '768px',
      lg: '1024px',
      xl: '1200px',
      '2xl': '1400px'
    },
    
    // Animation Easings
    easings: {
      inOutCubic: 'cubic-bezier(0.4, 0, 0.2, 1)',
      outCubic: 'cubic-bezier(0.33, 1, 0.68, 1)',
      inCubic: 'cubic-bezier(0.32, 0, 0.67, 0)',
      bounce: 'cubic-bezier(0.34, 1.56, 0.64, 1)'
    }
  };
  
  /**
   * Utility functions for theme access
   */
  
  /**
   * Get a color from the theme with fallback
   * @param {string} colorPath - Dot notation path to color (e.g., 'colors.primary')
   * @param {string} fallback - Fallback color if path not found
   * @returns {string} Color value
   */
  export const getColor = (colorPath, fallback = '#000000') => {
    const keys = colorPath.split('.');
    let value = theme;
    
    for (const key of keys) {
      if (value && typeof value === 'object' && key in value) {
        value = value[key];
      } else {
        return fallback;
      }
    }
    
    return typeof value === 'string' ? value : fallback;
  };
  
  /**
   * Get spacing value from theme
   * @param {string} size - Size key (xs, sm, base, etc.)
   * @param {string} fallback - Fallback value
   * @returns {string} Spacing value
   */
  export const getSpacing = (size, fallback = '1rem') => {
    return theme.spacing[size] || fallback;
  };
  
  /**
   * Get font size from theme
   * @param {string} size - Size key (xs, sm, base, etc.)
   * @param {string} fallback - Fallback value
   * @returns {string} Font size value
   */
  export const getFontSize = (size, fallback = '0.9rem') => {
    return theme.fontSizes[size] || fallback;
  };
  
  /**
   * Generate responsive media query
   * @param {string} breakpoint - Breakpoint key
   * @returns {string} Media query string
   */
  export const mediaQuery = (breakpoint) => {
    const bp = theme.breakpoints[breakpoint];
    return bp ? `@media (min-width: ${bp})` : '';
  };
  
  /**
   * Get speed status color
   * @param {string} status - Speed status (feasible, marginal, impossible)
   * @returns {string} Color value
   */
  export const getSpeedColor = (status) => {
    return theme.components.speed.colors[status] || theme.colors.textSecondary;
  };
  
  /**
   * Get waypoint color by type
   * @param {string} type - Waypoint type (start, end, default, selected, warning)
   * @returns {string} Color value
   */
  export const getWaypointColor = (type) => {
    return theme.components.waypoint.colors[type] || theme.components.waypoint.colors.default;
  };
  
  /**
   * Create CSS custom properties from theme
   * @returns {object} CSS custom properties object
   */
  export const createCSSVariables = () => {
    const cssVars = {};
    
    // Add color variables
    Object.entries(theme.colors).forEach(([key, value]) => {
      cssVars[`--color-${key.replace(/([A-Z])/g, '-$1').toLowerCase()}`] = value;
    });
    
    // Add spacing variables
    Object.entries(theme.spacing).forEach(([key, value]) => {
      cssVars[`--spacing-${key}`] = value;
    });
    
    // Add font size variables
    Object.entries(theme.fontSizes).forEach(([key, value]) => {
      cssVars[`--font-size-${key}`] = value;
    });
    
    return cssVars;
  };
  
  /**
   * Apply theme to DOM (useful for dynamic theming)
   */
  export const applyThemeToDOM = () => {
    const root = document.documentElement;
    const cssVars = createCSSVariables();
    
    Object.entries(cssVars).forEach(([property, value]) => {
      root.style.setProperty(property, value);
    });
  };
  
  export default theme;