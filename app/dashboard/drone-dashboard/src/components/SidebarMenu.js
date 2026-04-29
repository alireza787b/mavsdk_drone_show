//app/dashboard/drone-dashboard/src/components/SidebarMenu.js
import React, { useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import {
  FaGlobe,
  FaTachometerAlt,
  FaCog,
  FaCubes,
  FaRoute,
  FaProjectDiagram,
  FaGithub,
  FaGem,
  FaChevronLeft,
  FaChevronRight,
  FaLinkedin,
  FaClock,
  FaCodeBranch,
  FaSearchLocation,
  FaMagic,
  FaClipboardList,
  FaSatelliteDish,
  FaSlidersH,
  FaUserCheck,
  FaDocker,
  FaServer,
  FaNetworkWired,
  FaSignOutAlt,
  FaUserShield,
} from 'react-icons/fa';
import { useTheme } from '../hooks/useTheme';
import ThemeToggle from './ThemeToggle';
import '../styles/SidebarMenu.css';
import CurrentTime from './CurrentTime';
import GitInfo from './GitInfo';
import RuntimeModeBadge from './RuntimeModeBadge';
import useGcsGitInfo from '../hooks/useGcsGitInfo';
import { VERSION_DISPLAY } from '../version';

const getInitialCollapsed = () => {
  if (typeof window === 'undefined') {
    return false;
  }
  return window.innerWidth < 768;
};

const SidebarMenu = ({
  collapsed,
  mobile = false,
  mobileOpen = false,
  onNavigate,
  onToggle,
  gitInfoOverride = null,
  themeOverride = null,
  runtimeStatus = {
    mode: 'unknown',
    modeLabel: 'UNKNOWN',
    restartRequired: false,
  },
  authStatus = {},
  currentUser = null,
  onLogout = null,
}) => {
  const themeState = useTheme() || {};
  const gitInfoState = useGcsGitInfo() || {};
  const { isDark = false } = themeOverride || themeState;
  const gitInfo = gitInfoOverride || gitInfoState;
  const [localCollapsed, setLocalCollapsed] = useState(getInitialCollapsed);
  const [activeTooltip, setActiveTooltip] = useState(null);

  const isCollapsed = mobile ? false : (collapsed !== undefined ? collapsed : localCollapsed);
  const handleToggle = onToggle || setLocalCollapsed;
  const runningModeLabel = runtimeStatus.modeLabel || 'UNKNOWN';
  const configuredModeLabel = runtimeStatus.configuredModeLabel || runningModeLabel;
  const runtimeAdminTitle = runtimeStatus.restartRequired
    ? `Running ${runningModeLabel}. Configured ${configuredModeLabel}. Restart pending; open GCS Runtime.`
    : `Running ${runningModeLabel}. Open GCS Runtime.`;
  const authEnabled = Boolean(authStatus?.dashboard_auth_enabled);
  const currentUserLabel = currentUser?.username || 'operator';
  const currentUserRole = currentUser?.role || authStatus?.role || 'operator';

  const menuSections = [
    {
      label: 'General',
      items: [
        { to: '/', icon: FaTachometerAlt, label: 'Dashboard' },
        { to: '/mission-config', icon: FaCog, label: 'Mission Config' },
        { to: '/fleet-enrollment', icon: FaUserCheck, label: 'Fleet Enrollment' },
        { to: '/fleet-ops', icon: FaNetworkWired, label: 'Fleet Ops' },
        { to: '/px4-parameters', icon: FaSlidersH, label: 'PX4 Parameters' },
        { to: '/globe-view', icon: FaGlobe, label: '3D Globe View' },
      ],
    },
    {
      label: 'Drone Show',
      items: [
        { to: '/manage-drone-show', icon: FaMagic, label: 'Show Design' },
        { to: '/custom-show', icon: FaGem, label: 'Custom Show' },
      ],
    },
    {
      label: 'Smart Swarm',
      items: [
        { to: '/swarm-design', icon: FaCubes, label: 'Swarm Design' },
        { to: '/trajectory-planning', icon: FaRoute, label: 'Trajectory Planning' },
        { to: '/swarm-trajectory', icon: FaProjectDiagram, label: 'Swarm Trajectory' },
        { to: '/quickscout', icon: FaSearchLocation, label: 'QuickScout' },
      ],
    },
    {
      label: 'System',
      items: [
        {
          to: '/runtime-admin',
          icon: FaServer,
          label: 'GCS Runtime',
          attention: runtimeStatus.restartRequired ? 'Apply' : '',
          attentionTone: runtimeStatus.restartRequired ? 'warning' : 'neutral',
        },
        { to: '/sitl-control', icon: FaDocker, label: 'SITL Control' },
        { to: '/logs', icon: FaClipboardList, label: 'Log Viewer' },
      ],
    },
  ];

  const handleTooltip = (label) => {
    if (isCollapsed) {
      setActiveTooltip(label);
      setTimeout(() => setActiveTooltip(null), 2000);
    }
  };

  return (
    <div className={`modern-sidebar-wrapper ${isCollapsed ? 'collapsed' : 'expanded'} ${mobile ? 'mobile' : 'desktop'} ${mobileOpen ? 'mobile-open' : ''} ${isDark ? 'dark' : 'light'}`}>
      {/* Toggle Button */}
      <button
        className="sidebar-toggle"
        type="button"
        onClick={() => handleToggle(!isCollapsed)}
        aria-label={isCollapsed ? 'Expand navigation sidebar' : 'Collapse navigation sidebar'}
      >
        {isCollapsed ? <FaChevronRight /> : <FaChevronLeft />}
      </button>

      {/* Header Section */}
      <div className="sidebar-header">
        {!isCollapsed ? (
          <div className="header-expanded">
            <div className="brand">
              <span className="brand-icon" aria-hidden="true">
                <FaSatelliteDish />
              </span>
              <div className="brand-text">
                <h3>MDS Control</h3>
                <span className="version">{VERSION_DISPLAY}</span>
                <Link
                  className="sidebar-runtime-link"
                  to="/runtime-admin"
                  onClick={() => {
                    if (mobile && onNavigate) {
                      onNavigate();
                    }
                  }}
                  aria-label={`Open GCS Runtime to review runtime mode. ${runtimeAdminTitle}`}
                >
                  <RuntimeModeBadge
                    mode={runtimeStatus.mode}
                    configuredMode={runtimeStatus.configuredMode}
                    restartRequired={runtimeStatus.restartRequired}
                    compact
                    className="sidebar-runtime-badge"
                  />
                </Link>
                <span className="version-meta version-meta--repo">{gitInfo.repo}</span>
                <span className="version-meta">{gitInfo.runtimeLabel}</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="header-collapsed">
            <span className="brand-icon-collapsed" aria-hidden="true">
              <FaSatelliteDish />
            </span>
            <Link
              className="sidebar-runtime-summary-collapsed"
              to="/runtime-admin"
              onClick={() => {
                if (mobile && onNavigate) {
                  onNavigate();
                }
              }}
              aria-label={`Open GCS Runtime to review runtime mode. ${runtimeAdminTitle}`}
            >
              <RuntimeModeBadge
                mode={runtimeStatus.mode}
                configuredMode={runtimeStatus.configuredMode}
                restartRequired={runtimeStatus.restartRequired}
                compact
                className="sidebar-runtime-badge sidebar-runtime-badge--collapsed"
              />
            </Link>
          </div>
        )}
      </div>

      {/* Navigation Menu */}
      <nav className="sidebar-nav">
        {menuSections.map((section) => (
          <div className="nav-section" key={section.label}>
            {isCollapsed
              ? <div className="section-divider" />
              : <div className="nav-section-header">{section.label}</div>
            }
            {section.items.map((item) => {
              const IconComponent = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) => `nav-item ${isCollapsed ? 'collapsed' : ''} ${isActive ? 'active' : ''}`.trim()}
                  onClick={() => {
                    if (mobile && onNavigate) {
                      onNavigate();
                    }
                  }}
                  onMouseEnter={() => handleTooltip(item.label)}
                  aria-label={isCollapsed ? item.label : undefined}
                  data-tooltip={item.label}
                >
                  <IconComponent className="nav-icon" aria-hidden="true" />
                  {!isCollapsed && <span className="nav-label">{item.label}</span>}
                  {!isCollapsed && item.attention ? (
                    <span className={`nav-indicator nav-indicator--${item.attentionTone || 'neutral'}`}>{item.attention}</span>
                  ) : null}
                  {isCollapsed && item.attention ? (
                    <span className={`nav-indicator-dot nav-indicator-dot--${item.attentionTone || 'neutral'}`} aria-hidden="true" />
                  ) : null}

                  {/* Tooltip for collapsed state */}
                  {isCollapsed && activeTooltip === item.label && (
                    <div className="nav-tooltip">{item.label}</div>
                  )}
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Footer Section */}
      <div className="sidebar-footer">
        {/* Theme Toggle */}
        {authEnabled && (
          <div className="footer-item auth-user-container">
            {!isCollapsed ? (
              <div
                className="auth-user-pill"
                aria-label={`Signed in as ${currentUserLabel} (${currentUserRole})`}
              >
                <FaUserShield aria-hidden="true" />
                <span>{currentUserLabel}</span>
                <strong>{currentUserRole}</strong>
                {onLogout && (
                  <button
                    type="button"
                    onClick={onLogout}
                    aria-label="Log out of MDS dashboard"
                    title="Log out"
                  >
                    <FaSignOutAlt aria-hidden="true" />
                  </button>
                )}
              </div>
            ) : (
              <Link
                to="/runtime-admin"
                className="auth-user-icon"
                aria-label={`Signed in as ${currentUserLabel}. Open runtime security for details.`}
                onMouseEnter={() => handleTooltip(`Signed in: ${currentUserLabel}`)}
                onClick={() => {
                  if (mobile && onNavigate) {
                    onNavigate();
                  }
                }}
              >
                <FaUserShield aria-hidden="true" />
                {activeTooltip === `Signed in: ${currentUserLabel}` && (
                  <span className="nav-tooltip">{currentUserLabel}</span>
                )}
              </Link>
            )}
          </div>
        )}

        {/* Theme Toggle */}
        <div className="footer-item theme-toggle-container">
          <ThemeToggle
            variant={isCollapsed ? "simple" : "segmented"}
            showLabel={!isCollapsed}
            className="sidebar-theme-toggle"
          />
        </div>

        {/* Git Info - Compact */}
        <div className="footer-item git-info-container">
          {!isCollapsed ? (
            <GitInfo collapsed={false} />
          ) : (
            <button
              type="button"
              className="git-info-icon"
              aria-label="Show git status hint"
              onMouseEnter={() => handleTooltip('Git Status')}
            >
              <FaCodeBranch aria-hidden="true" />
              {activeTooltip === 'Git Status' && (
                <span className="nav-tooltip">Git Status</span>
              )}
            </button>
          )}
        </div>

        {/* Time Widget */}
        <div className="footer-item time-widget">
          {!isCollapsed ? (
            <div className="time-display">
              <FaClock className="time-icon" />
              <CurrentTime />
            </div>
          ) : (
            <button
              type="button"
              className="time-icon-collapsed"
              aria-label="Show current time hint"
              onMouseEnter={() => handleTooltip('Time')}
            >
              <FaClock aria-hidden="true" />
              {activeTooltip === 'Time' && (
                <span className="nav-tooltip"><CurrentTime /></span>
              )}
            </button>
          )}
        </div>

        {/* Social Links */}
        <div className="footer-item social-links">
          {!isCollapsed ? (
            <div className="social-expanded">
              <span className="copyright">© {new Date().getFullYear()} MDS by Alireza787b</span>
              <div className="social-icons">
                <a
                  href="https://github.com/alireza787b/mavsdk_drone_show"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Open MDS GitHub repository"
                >
                  <FaGithub aria-hidden="true" />
                </a>
                <a
                  href="https://linkedin.com/in/alireza787b"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Open LinkedIn profile"
                >
                  <FaLinkedin aria-hidden="true" />
                </a>
              </div>
            </div>
          ) : (
            <div className="social-collapsed">
              <a
                href="https://github.com/alireza787b/mavsdk_drone_show"
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Open MDS GitHub repository"
                onMouseEnter={() => handleTooltip('GitHub')}
              >
                <FaGithub aria-hidden="true" />
                {activeTooltip === 'GitHub' && (
                  <span className="nav-tooltip">GitHub</span>
                )}
              </a>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default SidebarMenu;
