import React, { useState } from 'react';
import { Sidebar, Menu, MenuItem } from 'react-pro-sidebar';
import { FaTachometerAlt, FaGem, FaList, FaGithub, FaBars, FaClock, FaCalendarAlt } from 'react-icons/fa';
import { Link } from 'react-router-dom';
import CurrentTime from './CurrentTime';
import GitInfo from './GitInfo';
import '../styles/SidebarMenu.css';

const SidebarMenu = () => {
  const [collapsed, setCollapsed] = useState(window.innerWidth < 768);

  return (
    <div className="sidebar-wrapper">
      <Sidebar className='sidebar'>
        <FaBars className='FaBars-icon' onClick={() => setCollapsed(!collapsed)} />

        <div className="sidebar-content">
          <div className="sidebar-header">
            <h3>Swarm Dashboard v0.9</h3>
          </div>

          <div className="sidebar-info">
            <div className="sidebar-info-item">
              <FaCalendarAlt className="icon" />
              <CurrentTime format="date" />
            </div>
            <div className="sidebar-info-item">
              <FaClock className="icon" />
              <CurrentTime format="time" />
            </div>
            <div className="sidebar-info-item">
              <FaGithub className="icon" />
              <GitInfo />
            </div>
          </div>

          <div className='menu-list'>
            <Menu>
              <Link to="/"><MenuItem icon={<FaTachometerAlt />}>Dashboard</MenuItem></Link>
              <Link to="/mission-config"><MenuItem icon={<FaGem />}>Mission Config</MenuItem></Link>
              <Link to="/swarm-design"><MenuItem icon={<FaList />}>Swarm Design</MenuItem></Link>
              <Link to="/manage-drone-show"><MenuItem icon={<FaGithub />}>Manage Drone Show</MenuItem></Link>
            </Menu>
          </div>

          <div className="developer-info">
            <p>&#169; {new Date().getFullYear()} <a href="https://github.com/alireza787b/mavsdk_drone_show" target='_blank'>MAVSDK Drone Show</a><br /> All rights reserved.</p>
            <a href='https://linkedin.com/in/alireza787b' target='_blank'>Linkedin</a>
          </div>
        </div>
      </Sidebar>
    </div>
  );
}

export default SidebarMenu;
