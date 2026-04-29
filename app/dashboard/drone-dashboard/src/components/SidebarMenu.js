//app/dashboard/drone-dashboard/src/components/SidebarMenu.js
import React, { useState } from 'react';
import { createPortal } from 'react-dom';
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
  FaKey,
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
  onChangePassword = null,
}) => {
  const themeState = useTheme() || {};
  const gitInfoState = useGcsGitInfo() || {};
  const { isDark = false } = themeOverride || themeState;
  const gitInfo = gitInfoOverride || gitInfoState;
  const [localCollapsed, setLocalCollapsed] = useState(getInitialCollapsed);
  const [activeTooltip, setActiveTooltip] = useState(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const [passwordPanelOpen, setPasswordPanelOpen] = useState(false);
  const [passwordForm, setPasswordForm] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
  });
  const [profileNotice, setProfileNotice] = useState(null);
  const [profileBusy, setProfileBusy] = useState(false);

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

  const resetPasswordForm = () => {
    setPasswordForm({ currentPassword: '', newPassword: '', confirmPassword: '' });
  };

  const closeProfile = () => {
    setProfileOpen(false);
    setPasswordPanelOpen(false);
    setProfileNotice(null);
    resetPasswordForm();
  };

  const handleProfileToggle = () => {
    if (profileOpen) {
      closeProfile();
      return;
    }
    setProfileNotice(null);
    setPasswordPanelOpen(false);
    setProfileOpen(true);
  };

  const handleProfileLinkNavigate = () => {
    closeProfile();
    if (mobile && onNavigate) {
      onNavigate();
    }
  };

  const handlePasswordChange = async (event) => {
    event.preventDefault();
    setProfileNotice(null);
    if (!onChangePassword) {
      setProfileNotice({ tone: 'danger', message: 'Password change is unavailable in this session.' });
      return;
    }
    if (passwordForm.newPassword !== passwordForm.confirmPassword) {
      setProfileNotice({ tone: 'danger', message: 'New password confirmation does not match.' });
      return;
    }
    setProfileBusy(true);
    try {
      await onChangePassword({
        currentPassword: passwordForm.currentPassword,
        newPassword: passwordForm.newPassword,
      });
      resetPasswordForm();
      setPasswordPanelOpen(false);
      setProfileNotice({ tone: 'good', message: 'Password updated.' });
    } catch (error) {
      setProfileNotice({
        tone: 'danger',
        message: error?.response?.data?.detail || error?.message || 'Password update failed.',
      });
    } finally {
      setProfileBusy(false);
    }
  };

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

  const profilePopoverContent = (
    <div className="auth-profile-layer">
      <button
        type="button"
        className="auth-profile-popover-backdrop"
        onClick={closeProfile}
        aria-label="Close profile"
      />
      <div className="auth-profile-popover" role="dialog" aria-label="Signed-in user profile">
        <button
          type="button"
          className="auth-profile-popover__close"
          onClick={closeProfile}
          aria-label="Close profile"
        >
          ×
        </button>
        <div className="auth-profile-popover__header">
          <FaUserShield aria-hidden="true" />
          <div>
            <strong>{currentUserLabel}</strong>
            <span>{currentUserRole}</span>
          </div>
        </div>
        {profileNotice && (
          <p className={`auth-profile-popover__notice auth-profile-popover__notice--${profileNotice.tone}`}>
            {profileNotice.message}
          </p>
        )}
        <div className="auth-profile-popover__links">
          {onChangePassword && (
            <button
              type="button"
              onClick={() => {
                setProfileNotice(null);
                setPasswordPanelOpen((current) => !current);
                if (passwordPanelOpen) {
                  resetPasswordForm();
                }
              }}
              aria-expanded={passwordPanelOpen}
            >
              <FaKey aria-hidden="true" />
              <span>{passwordPanelOpen ? 'Cancel' : 'Change password'}</span>
            </button>
          )}
          <Link to="/runtime-admin" onClick={handleProfileLinkNavigate}>Security</Link>
          <Link to="/logs" onClick={handleProfileLinkNavigate}>Logs</Link>
          {onLogout && (
            <button
              type="button"
              onClick={() => {
                closeProfile();
                onLogout();
              }}
            >
              <FaSignOutAlt aria-hidden="true" />
              <span>Log out</span>
            </button>
          )}
        </div>
        {passwordPanelOpen && (
          <form className="auth-profile-popover__form" onSubmit={handlePasswordChange}>
            <label>
              <span>Current</span>
              <input
                type="password"
                value={passwordForm.currentPassword}
                onChange={(event) => setPasswordForm((current) => ({ ...current, currentPassword: event.target.value }))}
                autoComplete="current-password"
                required
              />
            </label>
            <label>
              <span>New</span>
              <input
                type="password"
                value={passwordForm.newPassword}
                onChange={(event) => setPasswordForm((current) => ({ ...current, newPassword: event.target.value }))}
                autoComplete="new-password"
                required
              />
            </label>
            <label>
              <span>Confirm</span>
              <input
                type="password"
                value={passwordForm.confirmPassword}
                onChange={(event) => setPasswordForm((current) => ({ ...current, confirmPassword: event.target.value }))}
                autoComplete="new-password"
                required
              />
            </label>
            <button type="submit" disabled={profileBusy}>
              {profileBusy ? 'Updating…' : 'Save password'}
            </button>
          </form>
        )}
      </div>
    </div>
  );

  const profilePopover = profileOpen
    ? (typeof document === 'undefined' ? profilePopoverContent : createPortal(profilePopoverContent, document.body))
    : null;

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
              <div className="auth-user-pill">
                <button
                  type="button"
                  className="auth-user-profile-trigger"
                  onClick={handleProfileToggle}
                  aria-expanded={profileOpen}
                  aria-label={`Open profile for ${currentUserLabel} (${currentUserRole})`}
                >
                  <FaUserShield aria-hidden="true" />
                  <span>{currentUserLabel}</span>
                  <strong>{currentUserRole}</strong>
                </button>
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
                {profilePopover}
              </div>
            ) : (
              <>
                <button
                  type="button"
                  className="auth-user-icon"
                  aria-label={`Open profile for ${currentUserLabel}`}
                  onMouseEnter={() => handleTooltip(`Signed in: ${currentUserLabel}`)}
                  onClick={handleProfileToggle}
                  aria-expanded={profileOpen}
                >
                  <FaUserShield aria-hidden="true" />
                  {activeTooltip === `Signed in: ${currentUserLabel}` && (
                    <span className="nav-tooltip">{currentUserLabel}</span>
                  )}
                </button>
                {profilePopover}
              </>
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
              <div className="sidebar-brand-footer">
                <span>© {new Date().getFullYear()} MDS · {VERSION_DISPLAY}</span>
                <a
                  href="https://joomtalk.ir/"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Alireza Ghaderi
                </a>
              </div>
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
                href="https://joomtalk.ir/"
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Open Alireza Ghaderi personal page"
                onMouseEnter={() => handleTooltip('Alireza')}
              >
                <FaSatelliteDish aria-hidden="true" />
                {activeTooltip === 'Alireza' && (
                  <span className="nav-tooltip">Alireza</span>
                )}
              </a>
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
              <a
                href="https://linkedin.com/in/alireza787b"
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Open LinkedIn profile"
                onMouseEnter={() => handleTooltip('LinkedIn')}
              >
                <FaLinkedin aria-hidden="true" />
                {activeTooltip === 'LinkedIn' && (
                  <span className="nav-tooltip">LinkedIn</span>
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
