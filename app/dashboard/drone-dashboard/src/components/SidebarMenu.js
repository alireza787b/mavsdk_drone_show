import React, { useState } from 'react';
import { Sidebar, Menu, MenuItem } from 'react-pro-sidebar';
import { FaTachometerAlt, FaGem, FaList, FaGithub, FaBars } from 'react-icons/fa';
import 'react-pro-sidebar/dist/styles.css';
import '../styles/SidebarMenu.css';
import CurrentTime from './CurrentTime';
import GitInfo from './GitInfo';

const themes = {
  dark: {
    sidebar: {
      backgroundColor: '#1f2128',
      color: '#a2a5b9',
    },
    menu: {
      icon: '#59d0ff',
      hover: {
        backgroundColor: '#00458b',
        color: '#b6c8d9',
      }
    }
  }
};

const SidebarMenu = () => {
  const [theme] = useState('dark');
  const [collapsed, setCollapsed] = useState(window.innerWidth < 768);

  const menuItemStyles = {
    icon: {
      color: themes[theme].menu.icon,
    },
    hover: {
      backgroundColor: themes[theme].menu.hover.backgroundColor,
      color: themes[theme].menu.hover.color
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <Sidebar
        collapsed={collapsed}
        backgroundColor={themes[theme].sidebar.backgroundColor}
        color={themes[theme].sidebar.color}
        collapsedWidth={"80px"}
        className='sidebar'
      >
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          <div className="sidebar-header">
            <h3>Swarm Dashboard v0.9</h3>
            <FaBars
              className="toggle-icon"
              onClick={() => setCollapsed(!collapsed)}
            />
          </div>

          <div className="sidebar-content">
            <CurrentTime />
            <Menu menuItemStyles={menuItemStyles}>
              <MenuItem icon={<FaTachometerAlt />}>
                Dashboard
              </MenuItem>
              <MenuItem icon={<FaGem />}>
                Mission Config
              </MenuItem>
              <MenuItem icon={<FaList />}>
                Swarm Design
              </MenuItem>
              <MenuItem icon={<FaGithub />}>
                Manage Drone Show
              </MenuItem>
            </Menu>
          </div>

          <div className="sidebar-footer">
            <GitInfo />
            <p>&#169; {new Date().getFullYear()} MAVSDK Drone Show</p>
            <a href="https://linkedin.com/in/alireza787b" target="_blank" rel="noopener noreferrer">
              Linkedin
            </a>
          </div>
        </div>
      </Sidebar>
    </div>
  );
};

export default SidebarMenu;
