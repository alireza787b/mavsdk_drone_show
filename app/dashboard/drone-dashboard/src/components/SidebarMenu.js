//app/dashboard/drone-dashboard/src/components/SidebarMenu.js
import React, { useState } from 'react';
import { Sidebar, Menu, MenuItem } from 'react-pro-sidebar';
import { FaGlobe, FaHome, FaChartBar, FaCog, FaTachometerAlt, FaGem, FaList, FaGithub, FaBars } from 'react-icons/fa';
import { Link } from 'react-router-dom';
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
    <div className="wrapper">
      <Sidebar
        collapsed={collapsed}
        backgroundColor={themes[theme].sidebar.backgroundColor}
        color={themes[theme].sidebar.color}
        collapsedWidth={"80px"}
        className='sidebar'
      >
        <div className={`sidebar-content ${collapsed ? 'collapsed' : ''}`}>
          <FaBars className='FaBars-icon' onClick={() => setCollapsed(!collapsed)} />
          <br />

          {!collapsed && (
            <>
              <div className="sidebar-header">
                <h3>Swarm Dashboard v0.9</h3>
              </div>

              <div className="sidebar-time">
                <CurrentTime />
              </div>
            </>
          )}

          <br />

          {/* Menu */}
          <div className='menu-list'>
            <Menu menuItemStyles={menuItemStyles}>
              <Link to="/"><MenuItem icon={<FaTachometerAlt />}>
                Dashboard
              </MenuItem></Link>

              {/* New menu item for 3D View */}
              <Link to="/globe-view">
                <MenuItem icon={<FaGlobe />}>
                  Drone 3D View
                </MenuItem>
              </Link>
              
              <Link to="/mission-config">
                <MenuItem icon={<FaGem />}>
                  Mission Config
                </MenuItem>
              </Link>
              
              <Link to="/swarm-design">
                <MenuItem icon={<FaList />}>
                  Swarm Design
                </MenuItem>
              </Link>
              
              <Link to="/manage-drone-show">
                <MenuItem icon={<FaGithub />}>
                  Drone Show Design
                </MenuItem>
              </Link>
              
              <Link to="/custom-show">
                <MenuItem icon={<FaGem />}>
                  Custom Show
                </MenuItem>
              </Link>
            
            </Menu>
          </div>


          {/* Git Information */}
          {!collapsed && <GitInfo />}

          {/* Footer */}
          {!collapsed && (
            <div className="developer-info">
              <p>&#169; {new Date().getFullYear()} <a href="https://github.com/alireza787b/mavsdk_drone_show" target='_blank'>MAVSDK Drone Show</a><br /> All rights reserved.</p>
              <a href='https://linkedin.com/in/alireza787b' target='_blank'>Linkedin</a>
            </div>
          )}
        </div>
      </Sidebar>
    </div>
  );
}

export default SidebarMenu;
