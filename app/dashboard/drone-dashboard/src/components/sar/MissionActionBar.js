// src/components/sar/MissionActionBar.js
import React, { useState } from 'react';
import { FaMapMarkedAlt, FaPause, FaHome, FaArrowDown, FaPauseCircle } from 'react-icons/fa';
import { ConfirmDialog } from '../ui';

const MissionActionBar = ({
  onReplan,
  onPause,
  onAbort,
  missionState,
  controlAvailability = null,
  returnBehavior = 'return_home',
}) => {
  const [showAbortConfirm, setShowAbortConfirm] = useState(false);

  if (!missionState || missionState === 'planning' || missionState === 'ready') return null;

  const pauseEnabled = controlAvailability?.pause_enabled ?? (missionState === 'executing');
  const replanEnabled = controlAvailability?.replan_enabled ?? (missionState === 'paused');
  const abortEnabled = controlAvailability?.abort_enabled ?? true;

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
    <>
      <div className="qs-action-bar">
        <button
          className="qs-action-btn resume"
          onClick={onReplan}
          aria-label={controlAvailability?.replan_reason || 'Create a follow-up package from current aircraft state'}
          disabled={!replanEnabled}
        >
          <FaMapMarkedAlt />
        </button>
        <button
          className="qs-action-btn pause"
          onClick={onPause}
          aria-label={controlAvailability?.pause_reason || 'Hold mission'}
          disabled={!pauseEnabled}
        >
          <FaPause />
        </button>
        <button
          className="qs-action-btn end"
          onClick={() => setShowAbortConfirm(true)}
          aria-label={returnBehaviorMeta.title}
          disabled={!abortEnabled}
        >
          {returnBehaviorMeta.icon}
        </button>
      </div>
      <ConfirmDialog
        open={showAbortConfirm}
        title="End QuickScout Mission"
        message={(
          <span>
            Confirm mission end. Assigned drones will {returnBehaviorMeta.label.toLowerCase()}.
          </span>
        )}
        tone="danger"
        confirmLabel="End Mission"
        onCancel={() => setShowAbortConfirm(false)}
        onConfirm={() => {
          setShowAbortConfirm(false);
          onAbort?.();
        }}
      />
    </>
  );
};

export default MissionActionBar;
