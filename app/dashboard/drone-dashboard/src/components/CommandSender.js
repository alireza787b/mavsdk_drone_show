import React, { useState } from 'react';
import axios from 'axios';
import '../styles/CommandSender.css';
import { getBackendURL } from '../utilities';

const CommandSender = () => {
  const [missionType, setMissionType] = useState('');
  const [timeDelay, setTimeDelay] = useState('10');
  const [activeTab, setActiveTab] = useState('missionTrigger');
  const [altitude, setAltitude] = useState('10');

    // Function to handle sending the disarm command
    const handleDisarmDrones = () => {
        const commandData = {
          missionType: 'n', // Special mission type for disarm
          triggerTime: '0', // No delay for disarm
        };
    
        // Send the disarm command to the server
        axios.post(`${getBackendURL()}/send_command`, commandData)
        .then((response) => {
            if (response.data.status === 'success') {
              alert('Drones disarmed successfully!');
            } else {
              alert('Error disarming drones: ' + response.data.message);
            }
          })
          .catch((error) => {
            console.error('Error disarming drones:', error);
            alert('Error disarming drones. Please check the console for more details.');
          });
      };
    
      // Function to handle sending the command
      const handleSendCommand = () => {
        if (missionType === '') {
          alert('Please select a mission type.');
          return;
        }
    
        if (timeDelay === '' || timeDelay <= 0) {
          alert('Please enter a valid time delay.');
          return;
        }
    
        // Calculate the trigger time
        const triggerTime = new Date(Date.now() + timeDelay * 1000);
        const triggerTimeLocal = triggerTime.toLocaleString();
        const triggerTimestamp = triggerTime.getTime();
    
        // Prepare the confirmation message
        const missionName = missionType === 's' ? 'Smart Swarm' : missionType === 'd' ? 'Drone Show' : 'None';
        const confirmationMessage = `Are you sure you want to send the ${missionName} command to all drones?
          Trigger time: ${triggerTimeLocal} (Timestamp: ${triggerTimestamp})`;
    
        // Show confirmation dialog
        if (window.confirm(confirmationMessage)) {
          // If confirmed, send the command
          const commandData = {
            missionType: missionType,
            triggerTime: Math.floor(triggerTime.getTime() / 1000)
          };
    
          // Send the command data to the server
          axios.post(`${getBackendURL()}/send_command`, commandData)
          .then((response) => {
              if (response.data.status === 'success') {
                alert('Command sent successfully!');
              } else {
                alert('Error sending command: ' + response.data.message);
              }
            })
            .catch((error) => {
              console.error('Error sending command:', error);
              alert('Error sending command. Please check the console for more details.');
            });
        }
      };
    
// Placeholder function for Test action
const handleTestAction = () => {
    const isConfirmed = window.confirm('Test Action: Will arm the drones, wait for 3 seconds, then disarm. Are you sure you want to proceed?');

    if (isConfirmed) {
        const commandData = {
            missionType: 100,
            triggerTime: '0', // No delay
        };
        console.log("Sending Test commandData:", commandData);
        sendCommandToServer(commandData);
    } else {
        console.log("Test command cancelled.");
    }
};


// Function to handle sending the Takeoff command
const handleTakeoff = () => {
    const actualAltitude = parseInt(altitude, 10);
    const commandData = {
      missionType: 10 + actualAltitude, // 10 for Takeoff and altitude
      triggerTime: '0', // No delay for Takeoff
    };

    // Confirmation dialog
    if (window.confirm(`Are you sure you want to send the Takeoff command to all drones? The drones will take off to an altitude of ${actualAltitude}m.`)) {
        console.log("Sending Takeoff commandData:", commandData);
        sendCommandToServer(commandData);
    } else {
        console.log("Takeoff command cancelled.");
    }
};

  
  
// Function to handle sending the Land All command
const handleLandAll = () => {
    const isConfirmed = window.confirm('Land All: This will land all drones at their current positions. Are you sure you want to proceed?');
  
    if (isConfirmed) {
      const commandData = {
        missionType: 101, // 101 for Land All
        triggerTime: '0', // No delay for Land
      };
  
      console.log("Sending Land All commandData:", commandData);
      sendCommandToServer(commandData);
    } else {
      console.log("Land All command cancelled.");
    }
  };
  
  // Function to handle sending the Hold Position command
  const handleHoldPosition = () => {
    const isConfirmed = window.confirm('Hold Position: This will make all drones hold their current positions. Are you sure you want to proceed?');
  
    if (isConfirmed) {
      const commandData = {
        missionType: 102, // 102 for Hold Position
        triggerTime: '0', // No delay for Hold
      };
  
      console.log("Sending Hold Position commandData:", commandData);
      sendCommandToServer(commandData);
    } else {
      console.log("Hold Position command cancelled.");
    }
  };
  
  
  // Function to send command to the server
  const sendCommandToServer = (commandData) => {
    axios.post(`${getBackendURL()}/send_command`, commandData)
    .then((response) => {
      if (response.data.status === 'success') {
        alert('Command sent successfully!');
      } else {
        alert('Error sending command: ' + response.data.message);
      }
    })
    .catch((error) => {
      console.error('Error sending command:', error);
      alert('Error sending command. Please check the console for more details.');
    });
  };

      return (
        <div className="command-sender">
                  <h1>Command Control</h1>  {/* Added title */}

          <div className="tab-bar">
            <button className={activeTab === 'missionTrigger' ? 'active' : ''} onClick={() => setActiveTab('missionTrigger')}>
              Mission Trigger
            </button>
            <button className={activeTab === 'actions' ? 'active' : ''} onClick={() => setActiveTab('actions')}>
              Actions
            </button>
          </div>
    
          {activeTab === 'missionTrigger' && (
            <div className="mission-trigger-content">
              {/* Your existing Mission Trigger form controls */}
              <div className="mission-control">
                <div className="mission-selection">
                  <label className="mission-label">
                    Mission Type:&nbsp;
                    <select value={missionType} onChange={(e) => setMissionType(e.target.value)} className="mission-dropdown">
                      <option value="">Select</option>
                      <option value="s">Smart Swarm</option>
                      <option value="d">Drone Show</option>
                    </select>
                  </label>
                </div>
                <div className="time-delay">
                  <label className="delay-label">
                    Time Delay (seconds):&nbsp;
                    <input type="number" value={timeDelay} onChange={(e) => setTimeDelay(e.target.value)} className="delay-input" />
                  </label>
                </div>
                <div className="mission-actions">
                  <button onClick={handleSendCommand} className="mission-button send-command">
                    Send Command
                  </button>
                  <button onClick={handleDisarmDrones} className="mission-button cancel-mission">
                    Cancel Mission
                  </button>
                </div>
              </div>
            </div>
          )}
    
    {activeTab === 'actions' && (
  <div className="actions-content">
    <div className="test-section">
      <button className="action-button test-button" onClick={handleTestAction}>Test</button>
    </div>
    <div className="takeoff-section">
      <label>
        Initial Takeoff Altitude (m):&nbsp;
        <input type="number" value={altitude} onChange={(e) => setAltitude(e.target.value)} className="altitude-input" />
      </label>
      <button className="action-button" onClick={handleTakeoff}>Takeoff</button>
    </div>
    <div className="land-all-section">
      <button className="action-button" onClick={handleLandAll}>Land All</button>
    </div>
    <div className="hold-position-section">
      <button className="action-button hold-position" onClick={handleHoldPosition}>Hold Position</button>
    </div>
  </div>
)}
    </div>
  );
};

export default CommandSender;