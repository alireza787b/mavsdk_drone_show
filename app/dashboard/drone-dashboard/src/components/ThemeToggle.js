import React, { useState } from 'react';
import {
  FaAdjust,
  FaCheck,
  FaChevronDown,
  FaMoon,
  FaSun,
} from 'react-icons/fa';
import { useTheme } from '../hooks/useTheme';
import { THEMES } from '../contexts/ThemeContext';
import '../styles/ThemeToggle.css';

const ThemeToggle = ({ variant = 'button', showLabel = true, className = '' }) => {
  const {
    themePreference,
    getThemeLabel,
    setTheme,
    toggleTheme,
    cycleTheme,
    isDark
  } = useTheme();

  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  const themeOptions = [
    {
      value: THEMES.LIGHT,
      label: 'Light',
      icon: FaSun,
      description: 'Light theme'
    },
    {
      value: THEMES.DARK,
      label: 'Dark',
      icon: FaMoon,
      description: 'Dark theme'
    },
    {
      value: THEMES.AUTO,
      label: 'Auto',
      icon: FaAdjust,
      description: 'Follow system preference'
    }
  ];

  const currentThemeOption = themeOptions.find(option => option.value === themePreference);
  const CurrentThemeIcon = currentThemeOption?.icon || FaAdjust;
  const SimpleThemeIcon = isDark ? FaSun : FaMoon;
  const effectiveThemeLabel = themePreference === THEMES.AUTO
    ? `Auto (${isDark ? 'Dark' : 'Light'})`
    : (currentThemeOption?.label || getThemeLabel());

  const handleThemeSelect = (theme) => {
    setTheme(theme);
    setIsDropdownOpen(false);
  };

  const handleToggleClick = () => {
    if (variant === 'dropdown') {
      setIsDropdownOpen(!isDropdownOpen);
    } else {
      toggleTheme();
    }
  };

  // Simple toggle button variant
  if (variant === 'simple') {
    return (
      <button
        className={`theme-toggle-simple ${className}`}
        onClick={toggleTheme}
        title={`Display theme: ${effectiveThemeLabel}. Switch to ${isDark ? 'light' : 'dark'} theme`}
        aria-label={`Display theme: ${effectiveThemeLabel}. Switch to ${isDark ? 'light' : 'dark'} theme`}
      >
        <SimpleThemeIcon className="theme-icon" />
      </button>
    );
  }

  if (variant === 'segmented') {
    return (
      <div
        className={`theme-toggle-segmented ${className}`}
        role="group"
        aria-label="Display theme selector"
      >
        {themeOptions.map((option) => {
          const OptionIcon = option.icon;
          return (
            <button
              key={option.value}
              type="button"
              className={`theme-segment ${themePreference === option.value ? 'active' : ''}`}
              onClick={() => handleThemeSelect(option.value)}
              title={option.description}
              aria-pressed={themePreference === option.value}
            >
              <OptionIcon className="theme-icon" />
              {showLabel && <span className="theme-label">{option.label}</span>}
            </button>
          );
        })}
      </div>
    );
  }

  // Cycle button variant (cycles through all themes)
  if (variant === 'cycle') {
    return (
      <button
        className={`theme-toggle-cycle ${className}`}
        onClick={cycleTheme}
        title={`Display theme: ${effectiveThemeLabel}`}
        aria-label={`Display theme: ${effectiveThemeLabel}. Click to cycle themes.`}
      >
        <CurrentThemeIcon className="theme-icon" />
        {showLabel && (
          <span className="theme-label">{effectiveThemeLabel}</span>
        )}
      </button>
    );
  }

  // Dropdown variant (full theme selector)
  if (variant === 'dropdown') {
    return (
      <div className={`theme-toggle-dropdown ${className}`}>
        <button
          className="theme-toggle-trigger"
          onClick={handleToggleClick}
          aria-expanded={isDropdownOpen}
          aria-haspopup="true"
          title={`Display theme: ${effectiveThemeLabel}`}
          aria-label={`Display theme: ${effectiveThemeLabel}. Choose light, dark, or automatic theme.`}
        >
          <CurrentThemeIcon className="theme-icon" />
          {showLabel && (
            <span className="theme-label">{effectiveThemeLabel}</span>
          )}
          <FaChevronDown className={`dropdown-arrow ${isDropdownOpen ? 'open' : ''}`} />
        </button>

        {isDropdownOpen && (
          <div className="theme-dropdown-menu">
            {themeOptions.map((option) => {
              const OptionIcon = option.icon;
              return (
                <button
                  key={option.value}
                  className={`theme-option ${themePreference === option.value ? 'active' : ''}`}
                  onClick={() => handleThemeSelect(option.value)}
                  title={option.description}
                >
                  <OptionIcon className="option-icon" />
                  <span className="option-label">{option.label}</span>
                  {themePreference === option.value && (
                    <FaCheck className="check-icon" />
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  // Default button variant
  return (
    <button
      className={`theme-toggle-button ${className}`}
      onClick={handleToggleClick}
      title={`Display theme: ${effectiveThemeLabel}`}
      aria-label={`Display theme: ${effectiveThemeLabel}`}
    >
      <CurrentThemeIcon className="theme-icon" />
      {showLabel && (
        <span className="theme-label">{effectiveThemeLabel}</span>
      )}
    </button>
  );
};

export default ThemeToggle;
