import React from 'react';

const MissionNotification = ({ message }) => {
  if (!message) return null; // Prevent rendering if there's no message

  return <div className="notification">{message}</div>;
};

export default MissionNotification;


