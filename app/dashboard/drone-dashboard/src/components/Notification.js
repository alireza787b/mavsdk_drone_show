// src/components/Notification.js
import React, { useEffect } from 'react';
import '../styles/Notification.css';

const Notification = ({ type, message, onClose }) => {
  useEffect(() => {
    const timer = setTimeout(() => {
      onClose();
    }, 5000); // Dismiss after 5 seconds
    return () => clearTimeout(timer);
  }, [onClose]);

  return (
    <div className={`notification ${type}`}>
      <span>{message}</span>
      <button className="notification-close" onClick={onClose}>
        &times;
      </button>
    </div>
  );
};

export default Notification;
