//app/dashboard/drone-dashboard/src/components/SidebarMenu.js
import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link, NavLink } from 'react-router-dom';
import {
  FaGlobe,
  FaTachometerAlt,
  FaCog,
  FaCubes,
  FaProjectDiagram,
  FaGithub,
  FaGem,
  FaChevronLeft,
  FaChevronRight,
  FaLinkedin,
  FaClock,
  FaInfoCircle,
  FaSearchLocation,
  FaMagic,
  FaClipboardList,
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
import RuntimeModeBadge from './RuntimeModeBadge';
import useGcsGitInfo from '../hooks/useGcsGitInfo';
import { VERSION_DISPLAY } from '../version';
import mdsMark from '../assets/mds-mark.svg';

const getInitialCollapsed = () => {
  if (typeof window === 'undefined') {
    return false;
  }
  return window.innerWidth <= 960;
};

function SystemAbout({ gitInfo, onClose }) {
  const dialogRef = useRef(null);
  useEffect(() => {
    const previous = document.activeElement;
    const dialog = dialogRef.current;
    if (dialog.showModal) dialog.showModal();
    else dialog.setAttribute('open', '');
    dialog.querySelector('button')?.focus();
    return () => { dialog.close?.(); if (previous?.isConnected) previous.focus(); };
  }, []);
  const raw = gitInfo.raw || {};
  return <dialog ref={dialogRef} className="sidebar-system" aria-labelledby="sidebar-system-title"
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <header><div><h2 id="sidebar-system-title">System / About</h2><span>MDS · {VERSION_DISPLAY}</span></div>
      <button type="button" onClick={onClose} aria-label="Close System / About">×</button></header>
    <section aria-label="Repository information"><h3>Repository</h3><dl>
      <dt>Repository</dt><dd>{gitInfo.repo || 'Unavailable'}</dd>
      <dt>Branch</dt><dd>{gitInfo.branch || 'Unavailable'}</dd>
      <dt>Commit</dt><dd>{gitInfo.commit || 'Unavailable'}</dd>
    </dl>
      <details><summary>Commit details</summary><dl>
        <dt>Author</dt><dd>{raw.author_name || 'Unavailable'}</dd>
        <dt>Date</dt><dd>{raw.commit_date || 'Unavailable'}</dd>
        <dt>Message</dt><dd>{raw.commit_message || 'Unavailable'}</dd>
        <dt>Uncommitted changes</dt><dd>{Array.isArray(raw.uncommitted_changes) ? raw.uncommitted_changes.length : 'Unavailable'}</dd>
      </dl></details>
    </section>
    <section aria-label="Browser clock diagnostics"><h3><FaClock aria-hidden="true" /> Browser clock</h3>
      <p>Local time and Unix seconds · not a GCS synchronization check.</p><CurrentTime /></section>
    <footer><span>© {new Date().getFullYear()} MDS</span>
      <a href="https://joomtalk.ir/" target="_blank" rel="noopener noreferrer">Alireza Ghaderi</a>
      <a href="https://github.com/alireza787b/mavsdk_drone_show" target="_blank" rel="noopener noreferrer" aria-label="Open MDS GitHub repository"><FaGithub aria-hidden="true" /> GitHub</a>
      <a href="https://linkedin.com/in/alireza787b" target="_blank" rel="noopener noreferrer" aria-label="Open LinkedIn profile"><FaLinkedin aria-hidden="true" /> LinkedIn</a>
    </footer>
  </dialog>;
}

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
  const [aboutOpen, setAboutOpen] = useState(false);
  const [passwordPanelOpen, setPasswordPanelOpen] = useState(false);
  const [passwordForm, setPasswordForm] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
  });
  const [profileNotice, setProfileNotice] = useState(null);
  const [profileBusy, setProfileBusy] = useState(false);
  const tooltipTimerRef = useRef(null);

  const isCollapsed = mobile ? false : (collapsed !== undefined ? collapsed : localCollapsed);
  const handleToggle = onToggle || setLocalCollapsed;
  const runningModeLabel = runtimeStatus.modeLabel || 'UNKNOWN';
  const configuredModeLabel = runtimeStatus.configuredModeLabel || runningModeLabel;
  const runtimeAdminTitle = runtimeStatus.restartRequired
    ? `Running ${runningModeLabel}. Configured ${configuredModeLabel}. Restart pending; open GCS Runtime.`
    : `Running ${runningModeLabel}. Open GCS Runtime.`;
  const authEnabled = Boolean(authStatus?.dashboard_auth_enabled || authStatus?.api_auth_enabled);
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
      label: 'Operate',
      items: [
        { to: '/', icon: FaTachometerAlt, label: 'Overview' },
        { to: '/mission-config', icon: FaCog, label: 'Mission Config' },
        { to: '/swarm-design', icon: FaCubes, label: 'Smart Swarm' },
        { to: '/drone-show', icon: FaMagic, label: 'Drone Show' },
      ],
    },
    {
      label: 'Plan',
      items: [
        { to: '/quickscout', icon: FaSearchLocation, label: 'QuickScout SAR' },
        { to: '/swarm-trajectory', icon: FaProjectDiagram, label: 'Swarm Trajectory' },
        { to: '/custom-show', icon: FaGem, label: 'Custom CSV Show' },
      ],
    },
    {
      label: 'Fleet',
      items: [
        { to: '/fleet-ops', icon: FaNetworkWired, label: 'Fleet Ops' },
        { to: '/fleet-enrollment', icon: FaUserCheck, label: 'Enrollment' },
        { to: '/px4-parameters', icon: FaSlidersH, label: 'PX4 Params' },
        { to: '/environments', icon: FaKey, label: 'Environment' },
      ],
    },
    {
      label: 'Diagnose',
      items: [
        { to: '/logs', icon: FaClipboardList, label: 'Logs' },
        { to: '/globe-view', icon: FaGlobe, label: 'Globe' },
        {
          to: '/runtime-admin',
          icon: FaServer,
          label: 'Runtime',
          attention: runtimeStatus.restartRequired ? 'Apply' : '',
          attentionTone: runtimeStatus.restartRequired ? 'warning' : 'neutral',
        },
        { to: '/sitl-control', icon: FaDocker, label: 'SITL' },
      ],
    },
    {
      label: 'AI',
      items: [
        { to: '/simurgh', icon: FaUserShield, label: 'Simurgh' },
      ],
    },
  ];

  useEffect(() => () => {
    if (tooltipTimerRef.current) {
      clearTimeout(tooltipTimerRef.current);
    }
  }, []);

  useEffect(() => {
    if (mobile && !mobileOpen) {
      setAboutOpen(false);
      setProfileOpen(false);
      setActiveTooltip(null);
    }
  }, [mobile, mobileOpen]);

  const clearTooltipTimer = () => {
    if (tooltipTimerRef.current) {
      clearTimeout(tooltipTimerRef.current);
      tooltipTimerRef.current = null;
    }
  };

  const handleTooltip = (label, event) => {
    if (!isCollapsed) {
      return;
    }
    clearTooltipTimer();
    const rect = event?.currentTarget?.getBoundingClientRect?.();
    setActiveTooltip({
      label,
      left: rect ? rect.right + 10 : 84,
      top: rect ? rect.top + (rect.height / 2) : 80,
    });
    tooltipTimerRef.current = setTimeout(() => {
      setActiveTooltip((current) => (current?.label === label ? null : current));
      tooltipTimerRef.current = null;
    }, 2000);
  };

  const handleTooltipLeave = () => {
    clearTooltipTimer();
    tooltipTimerRef.current = setTimeout(() => {
      setActiveTooltip(null);
      tooltipTimerRef.current = null;
    }, 120);
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
                placeholder="Current password"
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
                placeholder="New password"
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
                placeholder="Confirm new password"
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

  const navTooltip = isCollapsed && activeTooltip && typeof document !== 'undefined'
    ? createPortal(
      <div
        className="nav-tooltip"
        style={{ left: activeTooltip.left, top: activeTooltip.top }}
        role="tooltip"
      >
        {activeTooltip.label}
      </div>,
      document.body,
    )
    : null;

  return (
    <div aria-hidden={mobile && !mobileOpen ? true : undefined} className={`modern-sidebar-wrapper ${isCollapsed ? 'collapsed' : 'expanded'} ${mobile ? 'mobile' : 'desktop'} ${mobileOpen ? 'mobile-open' : ''} ${isDark ? 'dark' : 'light'}`}>
      {navTooltip}
      {aboutOpen && createPortal(<SystemAbout gitInfo={gitInfo} onClose={() => setAboutOpen(false)} />, document.body)}
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
                <img src={mdsMark} alt="" />
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
              </div>
            </div>
          </div>
        ) : (
          <div className="header-collapsed">
            <span className="brand-icon-collapsed" aria-hidden="true">
              <img src={mdsMark} alt="" />
            </span>
            <span className="version">{VERSION_DISPLAY}</span>
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
      <nav className="sidebar-nav" aria-label="Main navigation">
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
                  onMouseEnter={(event) => handleTooltip(item.label, event)}
                  onMouseOver={(event) => handleTooltip(item.label, event)}
                  onMouseLeave={handleTooltipLeave}
                  onPointerEnter={(event) => handleTooltip(item.label, event)}
                  onPointerOver={(event) => handleTooltip(item.label, event)}
                  onPointerLeave={handleTooltipLeave}
                  onFocus={(event) => handleTooltip(item.label, event)}
                  onBlur={handleTooltipLeave}
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
                  onMouseEnter={(event) => handleTooltip(`Signed in: ${currentUserLabel}`, event)}
                  onMouseLeave={handleTooltipLeave}
                  onClick={handleProfileToggle}
                  aria-expanded={profileOpen}
                >
                  <FaUserShield aria-hidden="true" />
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

        <div className="footer-item">
          <button type="button" className="sidebar-system-trigger" aria-label="System / About" aria-haspopup="dialog" aria-expanded={aboutOpen}
            onClick={() => { closeProfile(); setAboutOpen(true); }}
            onFocus={(event) => handleTooltip('System / About', event)} onBlur={handleTooltipLeave}
            onMouseEnter={(event) => handleTooltip('System / About', event)} onMouseLeave={handleTooltipLeave}>
            <FaInfoCircle aria-hidden="true" />{!isCollapsed && <span>System / About</span>}
          </button>
        </div>
      </div>
    </div>
  );
}

export default SidebarMenu;
