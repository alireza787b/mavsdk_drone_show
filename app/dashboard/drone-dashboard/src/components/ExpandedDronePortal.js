import React, { useEffect, useRef } from 'react';
import ReactDOM from 'react-dom';
import PropTypes from 'prop-types';
import DroneDetail from './DroneDetail';
import DroneCriticalCommands from './DroneCriticalCommands';
import { FaExclamationTriangle, FaCheckCircle, FaInfoCircle } from 'react-icons/fa';
import { Tooltip } from 'react-tooltip';
import { getFlightModeTitle, getSystemStatusTitle, isSafeMode, isReady, getFlightModeCategory } from '../utilities/flightModeUtils';
import { getDroneShowStateName, isMissionReady, isMissionExecuting } from '../constants/droneStates';
import { getFriendlyMissionName, getMissionStatusClass } from '../utilities/missionUtils';
import { FIELD_NAMES } from '../constants/fieldMappings';
import '../styles/ExpandedDronePortal.css';

const ExpandedDronePortal = ({ drone, isOpen, onClose, originRect }) => {
  const portalRef = useRef(null);

  // Create portal container if it doesn't exist
  useEffect(() => {
    const portalRoot = document.getElementById('expanded-drone-portal-root');
    if (!portalRoot) {
      const newPortalRoot = document.createElement('div');
      newPortalRoot.id = 'expanded-drone-portal-root';
      document.body.appendChild(newPortalRoot);
    }
  }, []);

  // Handle escape key and backdrop click
  useEffect(() => {
    if (!isOpen) return;

    const handleEscape = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    const handleClickOutside = (e) => {
      if (portalRef.current && !portalRef.current.contains(e.target)) {
        onClose();
      }
    };

    document.addEventListener('keydown', handleEscape);
    document.addEventListener('mousedown', handleClickOutside);

    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen, onClose]);

  if (!isOpen || !drone) return null;

  // Calculate status information
  const currentTimeInMs = Date.now();
  const isStale = currentTimeInMs - (drone[FIELD_NAMES.TIMESTAMP] || 0) > 5000;

  const flightModeValue = drone[FIELD_NAMES.FLIGHT_MODE] || 0;
  const baseMode = drone[FIELD_NAMES.BASE_MODE] || 0;
  const actualFlightMode = flightModeValue === 0 && baseMode === 192 ? 262147 : flightModeValue;
  const flightModeTitle = getFlightModeTitle(actualFlightMode);
  const flightModeCategory = getFlightModeCategory(actualFlightMode);
  const systemStatusName = getSystemStatusTitle(drone[FIELD_NAMES.SYSTEM_STATUS] || 0);

  const isArmed = drone[FIELD_NAMES.IS_ARMED] || false;
  const isReadyToArm = drone[FIELD_NAMES.IS_READY_TO_ARM] || false;
  const isInSafeMode = isSafeMode(actualFlightMode);
  const isSystemReady = isReady(drone[FIELD_NAMES.SYSTEM_STATUS] || 0);

  const missionReady = isMissionReady(drone[FIELD_NAMES.STATE]);
  const missionExecuting = isMissionExecuting(drone[FIELD_NAMES.STATE]);
  const missionStateName = getDroneShowStateName(drone[FIELD_NAMES.STATE]);
  const friendlyMissionName = getFriendlyMissionName(drone[FIELD_NAMES.LAST_MISSION]);
  const missionStatusClass = getMissionStatusClass(drone[FIELD_NAMES.LAST_MISSION]);

  const getBatteryStatus = (voltage) => {
    if (voltage === undefined) return { class: '', text: 'N/A' };
    if (voltage >= 15.5) return { class: 'good', text: `${voltage.toFixed(1)}V` };
    if (voltage >= 14.5) return { class: 'warning', text: `${voltage.toFixed(1)}V` };
    return { class: 'critical', text: `${voltage.toFixed(1)}V` };
  };

  const getAltitudeDisplay = (alt) => {
    if (alt === undefined || alt === null) return 'N/A';
    return `${alt.toFixed(1)}m`;
  };

  const batteryStatus = getBatteryStatus(drone[FIELD_NAMES.BATTERY_VOLTAGE]);
  const droneIP = drone[FIELD_NAMES.IP] || (drone[FIELD_NAMES.HW_ID] === '1' ? '127.0.0.1' : 'N/A');

  const portalRoot = document.getElementById('expanded-drone-portal-root');
  if (!portalRoot) return null;

  return ReactDOM.createPortal(
    <div className="expanded-drone-backdrop">
      <div
        ref={portalRef}
        className={`expanded-drone-container ${
          isReadyToArm ? 'ready-to-arm' : 'not-ready-to-arm'
        } ${isArmed ? 'armed' : 'disarmed'} ${
          missionReady ? 'mission-ready' : ''
        } ${missionExecuting ? 'mission-executing' : ''}`}
        style={{
          transformOrigin: originRect ?
            `${originRect.left + originRect.width / 2}px ${originRect.top + originRect.height / 2}px` :
            'center center'
        }}
      >
        {/* Close Button */}
        <button className="close-button" onClick={onClose} aria-label="Close expanded view">
          ×
        </button>

        {/* Header */}
        <header className="expanded-drone-header">
          <div className="drone-header">
            <span className={`status-indicator ${isStale ? 'stale' : 'active'}`} />
            <span>Drone {drone[FIELD_NAMES.HW_ID] || 'Unknown'}</span>
          </div>
        </header>

        {/* Critical Status Badges */}
        <div className="critical-status">
          <span className={`status-badge ${isArmed ? 'armed' : 'disarmed'}`}>
            {isArmed ? 'ARMED' : 'DISARMED'}
          </span>
          <span className={`status-badge ${isReadyToArm ? 'ready' : 'not-ready'}`}>
            {isReadyToArm ? 'READY' : 'NOT READY'}
          </span>
        </div>

        {/* Main Content Grid */}
        <div className="expanded-content-grid">
          {/* Left Column - Data */}
          <div className="data-column">
            <div className="data-grid">
              {/* Flight Mode */}
              <div className="data-item full-width">
                <span className="data-label">Flight Mode</span>
                <span className={`mode-badge ${flightModeCategory}`}>
                  {flightModeTitle}
                </span>
              </div>

              {/* Mission */}
              <div className="data-item">
                <span className="data-label">Mission</span>
                <span className={`mission-badge ${missionStatusClass}`}>
                  {friendlyMissionName}
                </span>
              </div>

              {/* Mission State */}
              <div className="data-item">
                <span className="data-label">State</span>
                <span className={`mission-state-badge ${
                  missionExecuting ? 'executing' : missionReady ? 'ready' : 'idle'
                }`}>
                  {missionStateName}
                </span>
              </div>

              {/* Altitude */}
              <div className="data-item">
                <span className="data-label">Altitude</span>
                <span className="data-value">
                  {getAltitudeDisplay(drone.Position_Alt)}
                </span>
              </div>

              {/* Battery */}
              <div className="data-item">
                <span className="data-label">Battery</span>
                <span className={`battery-value ${batteryStatus.class}`}>
                  {batteryStatus.text}
                </span>
              </div>

              {/* IP Address */}
              <div className="data-item">
                <span className="data-label">IP</span>
                <span className="data-value ip-address">
                  {droneIP}
                </span>
              </div>
            </div>

            {/* Critical Commands */}
            <div className="critical-commands-section">
              <h3>Critical Commands</h3>
              <DroneCriticalCommands droneId={drone.hw_ID} />
            </div>
          </div>

          {/* Right Column - Detailed Information */}
          <div className="detail-column">
            <DroneDetail drone={drone} isAccordionView />
          </div>
        </div>
      </div>
    </div>,
    portalRoot
  );
};

ExpandedDronePortal.propTypes = {
  drone: PropTypes.object,
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  originRect: PropTypes.object,
};

export default ExpandedDronePortal;