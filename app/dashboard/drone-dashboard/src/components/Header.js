import React from 'react';
import '../styles/Header.css';

const Header = ({ toggleTheme, currentTheme }) => {
  return (
    <header className="app-header">
      <h1>Drone Swarm Monitor</h1>
      <button onClick={toggleTheme}>
        {currentTheme === 'day' ? 'Night Mode' : 'Day Mode'}
      </button>
    </header>
  );
};

export default Header;
