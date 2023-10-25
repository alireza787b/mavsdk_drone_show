import React, { useState, useEffect } from 'react';
import { Sidebar, Menu, MenuItem, SubMenu } from 'react-pro-sidebar';
import { FaTachometerAlt, FaGem, FaList, FaGithub, FaRegLaughWink, FaClock, FaCalendar, FaDatabase } from 'react-icons/fa';
import { Link } from 'react-router-dom';
import '../styles/SidebarMenu.css';
import { FaBars } from 'react-icons/fa';
import CurrentTime from './CurrentTime';

// Theme variables
const themes = {
  light: {
    // Light theme variables 
  },
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
}

// Import other components

const SidebarMenu = () => {

  const [theme, setTheme] = useState('dark');
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
    <div style={{ display: 'flex'}}>
    <Sidebar collapsed={collapsed}
      backgroundColor={themes[theme].sidebar.backgroundColor}
      color={themes[theme].sidebar.color} collapsedWidth={"80px"} className='sidebar'
    >
    <div style={{ display: 'flex', flexDirection: 'column' }}>


      <FaBars className='FaBars-icon' onClick={() => setCollapsed(!collapsed)} />
    <br />

          

    <div className="sidebar-header">
      <h3>Swarm Dashboard v0.8</h3>
    </div>

    <div className="sidebar-time">
    <CurrentTime /> {/* Use the CurrentTime component here for displaying date and time */}

    </div>

    <br />

    {/* Menu */}
    <div className='menu-list'>
    <Menu menuItemStyles={menuItemStyles}>
    <Link to="/"><MenuItem icon={<FaTachometerAlt />}>
       Dashboard
      </MenuItem>
      </Link>
      <Link to="/mission-config">
        <MenuItem icon={<FaGem />}>
       Mission Config
      </MenuItem>
      </Link>
      <Link to="/swarm-design"><MenuItem icon={<FaList />}>
       Swarm Design
      </MenuItem>
      </Link>
      <Link to="/import-drone-show"><MenuItem icon={<FaGithub />}>
       Import Drone Show
      </MenuItem></Link>
    </Menu>
    </div>

    {/* Copyright Footer */}
<div className="developer-info">
  <p>&#169; {new Date().getFullYear()}  <a href="https://github.com/alireza787b/mavsdk_drone_show" target='_blank'>MAVSDK Drone Show</a><br /> All rights reserved.</p>
    <a href='https://linkedin.com/in/alireza787b' target='_blank'>Linkedin</a>
</div>
</div>
</Sidebar>
</div>
  );

}

export default SidebarMenu;
