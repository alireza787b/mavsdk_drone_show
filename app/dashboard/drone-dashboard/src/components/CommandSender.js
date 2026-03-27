// src/components/CommandSender.js

import React, { useMemo, useReducer, useState } from 'react';
import ReactDOM from 'react-dom';
import PropTypes from 'prop-types';
import MissionTrigger from './MissionTrigger';
import DroneActions from './DroneActions';
import CommandPreflightSummary from './CommandPreflightSummary';
import { toast } from 'react-toastify';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faRocket, faCog } from '@fortawesome/free-solid-svg-icons';
import {
  DRONE_MISSION_TYPES,
  DRONE_ACTION_TYPES,
  getCommandName,
} from '../constants/droneConstants';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
import {
  formatClockOffsetLabel,
  formatCommandAbsoluteTime,
  getFleetReferenceClock,
} from '../utilities/commandScheduling';
import '../styles/CommandSender.css';
import { FIELD_NAMES } from '../constants/fieldMappings';

const CommandSender = ({ drones }) => {
  const [activeTab, setActiveTab] = useState('missionTrigger');
  const [targetMode, setTargetMode] = useState('all'); // 'all' or 'selected'
  const [selectedDrones, setSelectedDrones] = useState([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [currentCommandData, setCurrentCommandData] = useState(null);
  const [confirmationMessage, setConfirmationMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [, forceClockTick] = useReducer((value) => value + 1, 0);

  React.useEffect(() => {
    const interval = setInterval(forceClockTick, 1000);
    return () => clearInterval(interval);
  }, []);

  const browserNowMs = Date.now();
  const fleetClock = useMemo(
    () => getFleetReferenceClock(drones, browserNowMs),
    [browserNowMs, drones],
  );
  const clockOffsetLabel = Math.abs(fleetClock.offsetMs) > 5000
    ? formatClockOffsetLabel(fleetClock.offsetMs)
    : null;
  const selectedLookup = useMemo(
    () => new Set(selectedDrones.map((value) => String(value))),
    [selectedDrones],
  );
  const targetCount = targetMode === 'selected' ? selectedLookup.size : drones.length;
  const targetLabel = targetMode === 'selected'
    ? `${selectedDrones.length} selected drone${selectedDrones.length === 1 ? '' : 's'}`
    : `all ${drones.length} drone${drones.length === 1 ? '' : 's'}`;
  const targetDescriptor = targetMode === 'selected'
    ? `Selected drones: ${selectedDrones.join(', ')}`
    : 'Target scope: all configured drones';

  const renderConfirmationDetails = () => {
    if (!currentCommandData) {
      return null;
    }

    const uiMeta = currentCommandData.uiMeta || {};
    const detailRows = [
      {
        label: 'Targets',
        value: targetLabel,
      },
      {
        label: 'Execution',
        value: uiMeta.triggerSummary || formatCommandAbsoluteTime(currentCommandData.triggerTime),
      },
      ...(clockOffsetLabel
        ? [{
          label: 'Clock note',
          value: `Scheduling uses the GCS-aligned clock. ${clockOffsetLabel}.`,
        }]
        : [{
          label: 'Clock note',
          value: 'Scheduling uses the GCS-aligned clock.',
        }]),
      ...((uiMeta.details || []).map((detail) => ({
        label: detail.label,
        value: detail.value,
      }))),
    ];

    return detailRows.map((detail) => (
      <p key={`${detail.label}-${detail.value}`}>
        <strong>{detail.label}:</strong> {detail.value}
      </p>
    ));
  };

  // Handle new command from child components (MissionTrigger/DroneActions)
  const handleSendCommand = (commandData) => {
    if (targetMode === 'selected') {
      if (selectedDrones.length === 0) {
        toast.error('No drones selected. Please select at least one drone.');
        return;
      }
    }

    const missionName = getCommandName(commandData.missionType);
    setCurrentCommandData({
      ...commandData,
      uiMeta: {
        ...(commandData.uiMeta || {}),
        operatorLabel: missionName,
      },
    });
    setConfirmationMessage(
      `${missionName} will be sent to ${targetLabel}. Confirm this command package before dispatch.`
    );
    setModalOpen(true);
  };

  // Confirm and send the command
  const handleConfirmSendCommand = async () => {
    if (currentCommandData) {
      setModalOpen(false);
      setLoading(true);
      try {
        const commandDataToSend = { ...currentCommandData };
        if (targetMode === 'selected') {
          commandDataToSend.target_drones = selectedDrones;
        }

        await submitCommandWithLifecycleFeedback(commandDataToSend);
      } catch (error) {
        console.error('Error sending command:', error);
        toast.error('Error sending command. Please check console for details.');
      } finally {
        setLoading(false);
        setCurrentCommandData(null);
      }
    }
  };

  // Cancel the command
  const handleCancelSendCommand = () => {
    setModalOpen(false);
    setCurrentCommandData(null);
  };

  // Drone selection functions
  const toggleDroneSelection = (droneId) => {
    setSelectedDrones((prev) =>
      prev.includes(droneId)
        ? prev.filter((id) => id !== droneId)
        : [...prev, droneId]
    );
  };

  const selectAllDrones = () => {
    const allDroneIds = drones.map((drone) => drone[FIELD_NAMES.HW_ID]);
    setSelectedDrones(allDroneIds);
  };

  const deselectAllDrones = () => {
    setSelectedDrones([]);
  };

  return (
    <div className="command-sender-container">
      <h2 className="command-sender-header">Command Control</h2>

      {/* Target Selection UI */}
      <div className="target-selection">
        <div className="target-selection__row">
          <div>
            <label htmlFor="targetMode" style={{ marginRight: '10px' }}>Command Target</label>
            <p className="target-selection__hint">Choose whether this panel addresses the whole fleet or a controlled subset.</p>
          </div>
          <select
            id="targetMode"
            value={targetMode}
            onChange={(e) => setTargetMode(e.target.value)}
          >
            <option value="all">All Drones</option>
            <option value="selected">Select Drones</option>
          </select>
        </div>

        {targetMode === 'selected' && (
          <div className="drone-selection">
            <div className="selection-buttons">
              <button onClick={selectAllDrones}>Select All</button>
              <button onClick={deselectAllDrones}>Deselect All</button>
            </div>
            <div className="drone-grid">
              {drones.map((drone) => (
                <div
                  key={drone[FIELD_NAMES.HW_ID]}
                  className={`drone-item ${
                    selectedDrones.includes(drone[FIELD_NAMES.HW_ID]) ? 'selected' : ''
                  }`}
                  onClick={() => toggleDroneSelection(drone[FIELD_NAMES.HW_ID])}
                >
                  {drone[FIELD_NAMES.HW_ID]}
                </div>
              ))}
            </div>
            <div className="selected-count">
              Selected Drones: {selectedDrones.length}
            </div>
          </div>
        )}
      </div>

      <CommandPreflightSummary
        drones={drones}
        targetMode={targetMode}
        selectedDrones={selectedDrones}
        referenceNowMs={fleetClock.referenceNowMs}
        clockOffsetLabel={clockOffsetLabel}
      />

      {/* Tab Navigation with Expert UI/UX Icons */}
      <div className="tab-bar">
        <button
          className={`tab-button ${activeTab === 'missionTrigger' ? 'active' : ''}`}
          onClick={() => setActiveTab('missionTrigger')}
          title="Mission Trigger - Schedule and execute complex mission operations"
        >
          <FontAwesomeIcon icon={faRocket} className="tab-icon" />
          <span className="tab-text">Mission Trigger</span>
        </button>
        <button
          className={`tab-button ${activeTab === 'actions' ? 'active' : ''}`}
          onClick={() => setActiveTab('actions')}
          title="Actions - Execute immediate flight control and system commands"
        >
          <FontAwesomeIcon icon={faCog} className="tab-icon" />
          <span className="tab-text">Actions</span>
        </button>
      </div>

      {/* Tab Content */}
      <div className="tab-content">
        {activeTab === 'missionTrigger' && (
          <MissionTrigger
            missionTypes={DRONE_MISSION_TYPES}
            onSendCommand={handleSendCommand}
            referenceNowMs={fleetClock.referenceNowMs}
            clockOffsetLabel={clockOffsetLabel}
          />
        )}
        {activeTab === 'actions' && (
          <DroneActions
            actionTypes={DRONE_ACTION_TYPES}
            onSendCommand={handleSendCommand}
            targetCount={targetCount}
          />
        )}
      </div>

      {/* Confirmation Modal - Rendered via Portal for proper viewport centering */}
      {modalOpen && ReactDOM.createPortal(
        <div className="modal-overlay" onClick={handleCancelSendCommand}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>Confirm Command</h3>
            <p>{confirmationMessage}</p>
            <p className="command-confirmation-target-note">{targetDescriptor}</p>
            {currentCommandData && (
              <div className="command-confirmation-details">
                {renderConfirmationDetails()}
              </div>
            )}
            <div className="modal-actions">
              <button className="confirm-button" onClick={handleConfirmSendCommand}>
                Yes
              </button>
              <button className="cancel-button" onClick={handleCancelSendCommand}>
                No
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* Loading Spinner */}
      {loading && (
        <div className="loading-overlay">
          <div className="loading-spinner"></div>
        </div>
      )}
    </div>
  );
};

CommandSender.propTypes = {
  drones: PropTypes.array.isRequired,
};

export default CommandSender;
