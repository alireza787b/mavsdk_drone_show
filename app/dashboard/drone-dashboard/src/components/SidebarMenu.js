//app/dashboard/drone-dashboard/src/components/SidebarMenu.js
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  FaGlobe,
  FaTachometerAlt,
  FaCog,
  FaList,
  FaRoute,
  FaProjectDiagram,
  FaGithub,
  FaGem,
  FaBars,
  FaTimes,
  FaLinkedin,
  FaClock,
  FaCodeBranch
} from 'react-icons/fa';
import { useTheme } from '../hooks/useTheme';
import ThemeToggle from './ThemeToggle';
import '../styles/SidebarMenu.css';
import CurrentTime from './CurrentTime';
import GitInfo from './GitInfo';

const SidebarMenu = ({ collapsed, onToggle }) => {
  const { isDark } = useTheme();
  // Use props if provided, otherwise fall back to local state for backwards compatibility
  const [localCollapsed, setLocalCollapsed] = useState(window.innerWidth < 768);
  const [activeTooltip, setActiveTooltip] = useState(null);

  const isCollapsed = collapsed !== undefined ? collapsed : localCollapsed;
  const handleToggle = onToggle || setLocalCollapsed;

  const menuItems = [
    { to: '/', icon: FaTachometerAlt, label: 'Dashboard', category: 'main' },
    { to: '/mission-config', icon: FaCog, label: 'Mission Config', category: 'main' },
    { to: '/swarm-design', icon: FaList, label: 'Swarm Design', category: 'workflow' },
    { to: '/trajectory-planning', icon: FaRoute, label: 'Trajectory Planning', category: 'workflow' },
    { to: '/swarm-trajectory', icon: FaProjectDiagram, label: 'Swarm Trajectory', category: 'workflow' },
    { to: '/manage-drone-show', icon: FaGithub, label: 'Drone Show Design', category: 'design' },
    { to: '/custom-show', icon: FaGem, label: 'Custom Show', category: 'design' },
    { to: '/globe-view', icon: FaGlobe, label: 'Drone 3D View', category: 'visualization' }
  ];

  const handleTooltip = (label) => {
    if (isCollapsed) {
      setActiveTooltip(label);
      setTimeout(() => setActiveTooltip(null), 2000);
    }
  };

  return (
    <div className={`modern-sidebar-wrapper ${isCollapsed ? 'collapsed' : 'expanded'} ${isDark ? 'dark' : 'light'}`}>
      {/* Toggle Button */}
      <button
        className="sidebar-toggle"
        onClick={() => handleToggle(!isCollapsed)}
        aria-label="Toggle Sidebar"
      >
        {isCollapsed ? <FaBars /> : <FaTimes />}
      </button>

      {/* Header Section */}
      <div className="sidebar-header">
        {!isCollapsed ? (
          <div className="header-expanded">
            <div className="brand">
              <span className="brand-icon">🚁</span>
              <div className="brand-text">
                <h3>Swarm Control</h3>
                <span className="version">v3.0</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="header-collapsed">
            <span className="brand-icon-collapsed">🚁</span>
          </div>
        )}
      </div>

      {/* Navigation Menu */}
      <nav className="sidebar-nav">
        <div className="nav-section">
          {isCollapsed && <div className="section-divider"></div>}
          {menuItems.map((item, index) => {
            const IconComponent = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`nav-item ${isCollapsed ? 'collapsed' : ''}`}
                onMouseEnter={() => handleTooltip(item.label)}
                data-tooltip={item.label}
              >
                <IconComponent className="nav-icon" />
                {!isCollapsed && <span className="nav-label">{item.label}</span>}

                {/* Tooltip for collapsed state */}
                {isCollapsed && activeTooltip === item.label && (
                  <div className="nav-tooltip">{item.label}</div>
                )}
              </Link>
            );
          })}
        </div>
      </nav>

      {/* Footer Section */}
      <div className="sidebar-footer">
        {/* Theme Toggle */}
        <div className="footer-item theme-toggle-container">
          <ThemeToggle
            variant={isCollapsed ? "simple" : "detailed"}
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
                <a href="https://github.com/the-mak-00/mavsdk_drone_show" target="_blank" rel="noopener noreferrer">
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
                href="https://github.com/the-mak-00/mavsdk_drone_show"
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