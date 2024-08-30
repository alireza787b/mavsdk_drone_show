import React, { useState, useEffect } from 'react';
import { ProSidebar, Menu, MenuItem, SubMenu } from 'react-pro-sidebar';
import { FaTachometerAlt, FaGem, FaList, FaGithub, FaBars, FaAngleDoubleRight, FaAngleDoubleLeft } from 'react-icons/fa';
import 'react-pro-sidebar/dist/css/styles.css';
import '../styles/SidebarMenu.css';
import CurrentTime from './CurrentTime';
import GitInfo from './GitInfo';

const SidebarMenu = () => {
  const [collapsed, setCollapsed] = useState(window.innerWidth < 768);

  return (
    <ProSidebar collapsed={collapsed} breakPoint="md">
      <div className="sidebar-header">
        <h3>Swarm Dashboard v0.9</h3>
        <FaBars
          className="toggle-icon"
          onClick={() => setCollapsed(!collapsed)}
        />
      </div>

      <div className="sidebar-content">
        <CurrentTime />

        <Menu iconShape="circle">
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

        <GitInfo />

      </div>

      <div className="sidebar-footer">
        <p>&#169; {new Date().getFullYear()} MAVSDK Drone Show</p>
        <a href="https://linkedin.com/in/alireza787b" target="_blank" rel="noopener noreferrer">
          Linkedin
        </a>
      </div>
    </ProSidebar>
  );
};

export default SidebarMenu;
