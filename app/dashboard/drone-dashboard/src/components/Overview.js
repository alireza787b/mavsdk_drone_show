import React, { useState, useEffect } from 'react';
import axios from 'axios';

const POLLING_RATE_HZ = 2; // Frequency of checking for new data (in Hz)
const STALE_DATA_THRESHOLD_SECONDS = 5; // Threshold for considering data stale (in seconds)

const Overview = ({ setSelectedDrone }) => {
  const [drones, setDrones] = useState([]);
  const [missionType, setMissionType] = useState(''); // State for selected mission type
  const [timeDelay, setTimeDelay] = useState('10'); // Initialize with default value of 10 seconds

  // Function to handle sending the disarm command
  const handleDisarmDrones = () => {
    const commandData = {
      missionType: 'n', // Special mission type for disarm
      timeDelay: '0', // No delay for disarm
    };

    // Send the disarm command to the server
    axios.post('http://127.0.0.1:5000/send_command', commandData)
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
        triggerTime: floor(triggerTime.getTime() / 1000)
      };

      // Send the command data to the server
      axios.post('http://127.0.0.1:5000/send_command', commandData)
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

  // Function to fetch data
  useEffect(() => {
    const url = 'http://127.0.0.1:5000/telemetry';

    const fetchData = () => {
      axios.get(url)
        .then((response) => {
          const dronesArray = Object.keys(response.data).map((hw_ID) => ({
            hw_ID,
            ...response.data[hw_ID],
          }));
          setDrones(dronesArray);
        })
        .catch((error) => {
          console.error('Network Error:', error);
        });
    };

    // Initial fetch
    fetchData();

    // Set up polling
    const pollingInterval = setInterval(fetchData, 1000 / POLLING_RATE_HZ);

    // Clean up interval when component unmounts
    return () => {
      clearInterval(pollingInterval);
    };
  }, []);

  return (
    <div>
      <h1>Connected Drones</h1>
      <div>
        <label>
          Mission Type:
          <select value={missionType} onChange={(e) => setMissionType(e.target.value)}>
            <option value="">Select</option>
            <option value="s">Smart Swarm</option>
            <option value="d">Drone Show</option>
          </select>
        </label>
        <label>
          Time Delay (seconds):
          <input type="number" value={timeDelay} onChange={(e) => setTimeDelay(e.target.value)} />
        </label>
        <button onClick={handleSendCommand}>Send Command</button>
        <button onClick={handleDisarmDrones}>Disarm Drones</button> {/* Button to disarm */}
      </div>
      <ul>
        {drones.map((drone) => {
          // Determine if the data is stale
          const isStale = (new Date() / 1000 - drone.Update_Time) > STALE_DATA_THRESHOLD_SECONDS;

          return (
            <div className="drone-item" key={drone.hw_ID} onClick={() => setSelectedDrone(drone)}>
              <li>
                <span style={{ color: isStale ? 'red' : 'green' }}>●</span> {/* Indicator */}
                HW_ID: {drone.hw_ID}, Mission: {drone.Mission}, State: {drone.State}, Follow Mode: {drone.Follow_Mode === 0 ? 'LEADER' : `Follows ${drone.Follow_Mode}`}, Altitude: {drone.Position_Alt.toFixed(1)}
              </li>
            </div>
          );
        })}
      </ul>
    </div>
  );
};

export default Overview;
