// CurrentTime.js - Clean, minimal time display component
import React, { useState, useEffect } from 'react';
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

  const formatTime = (date) => {
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    });
  };

  const getTimestamp = (date) => {
    return Math.floor(date.getTime() / 1000);
  };

  return (
    <div className="current-time">
      <div className="time-display-main">
        {formatTime(currentTime)}
      </div>
      <div className="timestamp">
        {getTimestamp(currentTime)}
      </div>
    </div>
  );
};

export default CurrentTime;
