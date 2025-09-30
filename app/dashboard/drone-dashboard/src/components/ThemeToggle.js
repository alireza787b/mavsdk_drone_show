import React, { useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faSun,
  faMoon,
  faCircleHalfStroke,
  faChevronDown,
  faCheck
} from '@fortawesome/free-solid-svg-icons';
import { useTheme } from '../hooks/useTheme';
import { THEMES } from '../contexts/ThemeContext';
import '../styles/ThemeToggle.css';

const ThemeToggle = ({ variant = 'button', showLabel = true, className = '' }) => {
  const {
    themePreference,
    getThemeLabel,
    getThemeIcon,
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
      icon: faSun,
      description: 'Light theme'
    },
    {
      value: THEMES.DARK,
      label: 'Dark',
      icon: faMoon,
      description: 'Dark theme'
    },
    {
      value: THEMES.AUTO,
      label: 'Auto',
      icon: faCircleHalfStroke,
      description: 'Follow system preference'
    }
  ];

  const currentThemeOption = themeOptions.find(option => option.value === themePreference);

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
        title={`Switch to ${isDark ? 'light' : 'dark'} theme`}
        aria-label={`Switch to ${isDark ? 'light' : 'dark'} theme`}
      >
        <FontAwesomeIcon
          icon={isDark ? faSun : faMoon}
          className="theme-icon"
        />
      </button>
    );
  }

  // Cycle button variant (cycles through all themes)
  if (variant === 'cycle') {
    return (
      <button
        className={`theme-toggle-cycle ${className}`}
        onClick={cycleTheme}
        title={getThemeLabel()}
        aria-label={`Current theme: ${getThemeLabel()}. Click to cycle themes.`}
      >
        <FontAwesomeIcon
          icon={currentThemeOption?.icon || faCircleHalfStroke}
          className="theme-icon"
        />
        {showLabel && (
          <span className="theme-label">{currentThemeOption?.label}</span>
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
          title="Select theme"
        >
          <FontAwesomeIcon
            icon={currentThemeOption?.icon || faCircleHalfStroke}
            className="theme-icon"
          />
          {showLabel && (
            <span className="theme-label">{currentThemeOption?.label}</span>
          )}
          <FontAwesomeIcon
            icon={faChevronDown}
            className={`dropdown-arrow ${isDropdownOpen ? 'open' : ''}`}
          />
        </button>

        {isDropdownOpen && (
          <div className="theme-dropdown-menu">
            {themeOptions.map((option) => (
              <button
                key={option.value}
                className={`theme-option ${themePreference === option.value ? 'active' : ''}`}
                onClick={() => handleThemeSelect(option.value)}
                title={option.description}
              >
                <FontAwesomeIcon icon={option.icon} className="option-icon" />
                <span className="option-label">{option.label}</span>
                {themePreference === option.value && (
                  <FontAwesomeIcon icon={faCheck} className="check-icon" />
                )}
              </button>
            ))}
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
      title={getThemeLabel()}
      aria-label={`Current theme: ${getThemeLabel()}`}
    >
      <FontAwesomeIcon
        icon={currentThemeOption?.icon || faCircleHalfStroke}
        className="theme-icon"
      />
      {showLabel && (
        <span className="theme-label">{getThemeLabel()}</span>
      )}
    </button>
  );
};

export default ThemeToggle;