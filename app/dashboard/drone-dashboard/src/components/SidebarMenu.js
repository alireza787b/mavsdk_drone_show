//app/dashboard/drone-dashboard/src/components/SidebarMenu.js
import React, { useState } from 'react';
import { NavLink } from 'react-router-dom';
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
} from 'react-icons/fa';
import { useTheme } from '../hooks/useTheme';
import ThemeToggle from './ThemeToggle';
import '../styles/SidebarMenu.css';
import CurrentTime from './CurrentTime';
import GitInfo from './GitInfo';
import useGcsGitInfo from '../hooks/useGcsGitInfo';
import useGcsRuntimeStatus from '../hooks/useGcsRuntimeStatus';
import { VERSION_DISPLAY } from '../version';

const SidebarMenu = ({ collapsed, mobile = false, mobileOpen = false, onNavigate, onToggle }) => {
  const { isDark } = useTheme();
  const gitInfo = useGcsGitInfo();
  const runtimeStatus = useGcsRuntimeStatus();
  // Use props if provided, otherwise fall back to local state for backwards compatibility
  const [localCollapsed, setLocalCollapsed] = useState(window.innerWidth < 768);
  const [activeTooltip, setActiveTooltip] = useState(null);

  const isCollapsed = mobile ? false : (collapsed !== undefined ? collapsed : localCollapsed);
  const handleToggle = onToggle || setLocalCollapsed;

  const menuSections = [
    {
      label: 'General',
      items: [
        { to: '/', icon: FaTachometerAlt, label: 'Dashboard' },
        { to: '/mission-config', icon: FaCog, label: 'Mission Config' },
        { to: '/fleet-enrollment', icon: FaUserCheck, label: 'Fleet Enrollment' },
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
        { to: '/runtime-admin', icon: FaServer, label: 'Runtime Admin' },
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
                <span className={`sidebar-mode-pill sidebar-mode-pill--${runtimeStatus.mode}`}>
                  {runtimeStatus.modeLabel}
                </span>
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
                  data-tooltip={item.label}
                >
                  <IconComponent className="nav-icon" />
                  {!isCollapsed && <span className="nav-label">{item.label}</span>}

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
            <div
              className="git-info-icon"
              title="Git Status"
              onMouseEnter={() => handleTooltip('Git Status')}
            >
              <FaCodeBranch />
              {activeTooltip === 'Git Status' && (
                <div className="nav-tooltip">Git Status</div>
              )}
            </div>
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
            <div
              className="time-icon-collapsed"
              title="Current Time"
              onMouseEnter={() => handleTooltip('Time')}
            >
              <FaClock />
              {activeTooltip === 'Time' && (
                <div className="nav-tooltip"><CurrentTime /></div>
              )}
            </div>
          )}
        </div>

        {/* Social Links */}
        <div className="footer-item social-links">
          {!isCollapsed ? (
            <div className="social-expanded">
              <span className="copyright">© {new Date().getFullYear()} MDS by Alireza787b</span>
              <div className="social-icons">
                <a href="https://github.com/alireza787b/mavsdk_drone_show" target="_blank" rel="noopener noreferrer">
                  <FaGithub />
                </a>
                <a href="https://linkedin.com/in/alireza787b" target="_blank" rel="noopener noreferrer">
                  <FaLinkedin />
                </a>
              </div>
            </div>
          ) : (
            <div className="social-collapsed">
              <a
                href="https://github.com/alireza787b/mavsdk_drone_show"
                target="_blank"
                rel="noopener noreferrer"
                title="GitHub Repository"
                onMouseEnter={() => handleTooltip('GitHub')}
              >
                <FaGithub />
                {activeTooltip === 'GitHub' && (
                  <div className="nav-tooltip">GitHub</div>
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
