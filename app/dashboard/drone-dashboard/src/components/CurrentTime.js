// CurrentTime.js
import React, { useState, useEffect } from 'react';
import { FaCalendar, FaClock, FaDatabase } from 'react-icons/fa';
import '../styles/CurrentTime.css';

const CurrentTime = () => {
  const [currentTime, setCurrentTime] = useState(new Date());

  const updateTime = () => {
    setCurrentTime(new Date());
  };

  useEffect(() => {
    const timeInterval = setInterval(updateTime, 1000);
    return () => {
      clearInterval(timeInterval);
    };
  }, []);

  return (
    <div className="current-time">
      <div className="current-time-item">
        <FaCalendar data-tip="Date" data-for="tooltip-date" />
        {currentTime.toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' })}
      </div>

      <div className="current-time-item">
        <FaClock data-tip="Time" data-for="tooltip-time" />
        {currentTime.toLocaleTimeString('en-US', { hour12: false })}
      </div>

      <div className="current-time-item">
        <FaDatabase data-tip="Unix Timestamp" data-for="tooltip-unix" />
        {Math.floor(currentTime / 1000)}
      </div>
    </div>
  );
};

export default CurrentTime;
