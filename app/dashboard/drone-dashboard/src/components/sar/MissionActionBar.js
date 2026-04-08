// src/components/sar/MissionActionBar.js
import React from 'react';
import { FaPlay, FaPause, FaHome, FaArrowDown, FaPauseCircle } from 'react-icons/fa';

const MissionActionBar = ({ onResume, onPause, onAbort, missionState, returnBehavior = 'return_home' }) => {
  if (!missionState || missionState === 'planning' || missionState === 'ready') return null;

  const returnBehaviorMeta = {
    return_home: {
      icon: <FaHome />,
      title: 'End mission and return home',
      label: 'Return home',
    },
    hold_position: {
      icon: <FaPauseCircle />,
      title: 'End mission and hold position',
      label: 'Hold position',
    },
    land_current: {
      icon: <FaArrowDown />,
      title: 'End mission and land at current position',
      label: 'Land current',
    },
  }[returnBehavior] || {
    icon: <FaHome />,
    title: 'End mission and return home',
    label: 'Return home',
  };

  return (
    <div className="qs-action-bar">
      <button
        className="qs-action-btn resume"
        onClick={onResume}
        title="Resume Mission"
        disabled={missionState !== 'paused'}
      >
        <FaPlay />
      </button>
      <button
        className="qs-action-btn pause"
        onClick={onPause}
        title="Pause Mission"
        disabled={missionState !== 'executing'}
      >
        <FaPause />
      </button>
      <button
        className="qs-action-btn end"
        onClick={() => {
          if (window.confirm(`End mission? Drones will ${returnBehaviorMeta.label.toLowerCase()}.`)) {
            onAbort();
          }
        }}
        title={returnBehaviorMeta.title}
      >
        {returnBehaviorMeta.icon}
      </button>
    </div>
  );
};

export default MissionActionBar;
