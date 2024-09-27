// src/components/DroneActions.js
import React, { useState } from 'react';
import { 
  FaPlaneDeparture, 
  FaPlaneLanding, 
  FaHandHolding, 
  FaVial, 
  FaLightbulb, 
  FaBatteryFull, 
  FaSyncAlt 
} from 'react-icons/fa';
import '../styles/DroneActions.css';

const DroneActions = ({ actionTypes, onSendCommand }) => {
  const [altitude, setAltitude] = useState(10);
  const [modalOpen, setModalOpen] = useState(false);
  const [currentAction, setCurrentAction] = useState(null);

  // Function to handle actions with confirmation
  const handleActionClick = (actionType, confirmationMessage) => {
    setCurrentAction({ actionType, confirmationMessage });
    setModalOpen(true);
  };

  const handleConfirm = () => {
    if (currentAction) {
      const { actionType } = currentAction;

      const commandData = {
        missionType: actionTypes[actionType],
        triggerTime: '0' // Immediate action
      };

      // Additional fields for specific actions
      if (actionType === 'TAKE_OFF') {
        commandData.takeoff_altitude = altitude;
      }

      onSendCommand(commandData);
    }
    setModalOpen(false);
    setCurrentAction(null);
  };

  const handleCancel = () => {
    setModalOpen(false);
    setCurrentAction(null);
  };

  return (
    <div className="drone-actions-container">
      <div className="takeoff-section">
        <label htmlFor="takeoff-altitude">Initial Takeoff Altitude (m):</label>
        <input 
          type="number" 
          id="takeoff-altitude" 
          value={altitude} 
          onChange={(e) => setAltitude(Number(e.target.value))} 
          min="1"
          max="1000"
          className="altitude-input"
        />
        <button 
          className="action-button takeoff-button"
          onClick={() => handleActionClick('TAKE_OFF', `Are you sure you want to send the Takeoff command to all drones? The drones will take off to an altitude of ${altitude}m.`)}
        >
          <FaPlaneDeparture className="action-icon" />
          Takeoff
        </button>
      </div>

      <button 
        className="action-button land-button"
        onClick={() => handleActionClick('LAND', 'Land All: This will land all drones at their current positions. Are you sure you want to proceed?')}
      >
        <FaPlaneLanding className="action-icon" />
        Land All
      </button>

      <button 
        className="action-button hold-button"
        onClick={() => handleActionClick('HOLD', 'Hold Position: This will make all drones hold their current positions. Are you sure you want to proceed?')}
      >
        <FaHandHolding className="action-icon" />
        Hold Position
      </button>

      <button 
        className="action-button test-button"
        onClick={() => handleActionClick('TEST', 'Test Action: Will arm the drones, wait for 3 seconds, then disarm. Are you sure you want to proceed?')}
      >
        <FaVial className="action-icon" />
        Test
      </button>

      <button 
        className="action-button test-led-button"
        onClick={() => handleActionClick('TEST_LED', 'Test Action: Will run the LED controller test script on the ground. Are you sure you want to proceed?')}
      >
        <FaLightbulb className="action-icon" />
        Test Light Show
      </button>

      <button 
        className="action-button disarm-button"
        onClick={() => handleActionClick('DISARM', 'Disarm Drones: This will disarm all drones immediately. Are you sure you want to proceed?')}
      >
        <FaBatteryFull className="action-icon" />
        Disarm Drones
      </button>

      <button 
        className="action-button reboot-button"
        onClick={() => handleActionClick('REBOOT', 'Reboot Drones: This will reboot all drones. Are you sure you want to proceed?')}
      >
        <FaSyncAlt className="action-icon" />
        Reboot Drones
      </button>

      {/* Confirmation Modal */}
      {modalOpen && (
        <div className="modal-overlay">
          <div className="modal-content">
            <h3>Confirm Action</h3>
            <p>{currentAction?.confirmationMessage}</p>
            <div className="modal-actions">
              <button className="confirm-button" onClick={handleConfirm}>Yes</button>
              <button className="cancel-button" onClick={handleCancel}>No</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DroneActions;
