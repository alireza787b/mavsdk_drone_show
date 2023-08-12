import React, { useState, useEffect } from 'react';
import axios from 'axios';
import DroneDetail from './DroneDetail';  // Import the DroneDetail component
import Globe from './Globe';
import '../styles/Overview.css';


const POLLING_RATE_HZ = 2;
const STALE_DATA_THRESHOLD_SECONDS = 5;

const Overview = ({ setSelectedDrone }) => {
  const [drones, setDrones] = useState([]);
  const [missionType, setMissionType] = useState('');
  const [timeDelay, setTimeDelay] = useState('10');
  const [expandedDrone, setExpandedDrone] = useState(null);

  // Function to handle sending the disarm command
  const handleDisarmDrones = () => {
    const commandData = {
      missionType: 'n', // Special mission type for disarm
      triggerTime: '0', // No delay for disarm
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
        triggerTime: Math.floor(triggerTime.getTime() / 1000)
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
          //console.log("Transformed Drones Data:", dronesArray);  // Add this line

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

  const toggleDroneDetails = (drone) => {
    if (expandedDrone && expandedDrone.hw_ID === drone.hw_ID) {
      setExpandedDrone(null);
    } else {
      setExpandedDrone(drone);
    }
  };

  return (
    <div>

<div className="mission-trigger-section">
  <h2>Mission Trigger</h2>
  
  <div className="mission-control">
    <div className="mission-selection">
      <label className="mission-label">
        Mission Type:&nbsp;
        <select 
          value={missionType} 
          onChange={(e) => setMissionType(e.target.value)}
          className="mission-dropdown"
        >
          <option value="">Select</option>
          <option value="s">Smart Swarm</option>
          <option value="d">Drone Show</option>
        </select>
      </label>
    </div>

    <div className="time-delay">
      <label className="delay-label">
        Time Delay (seconds):  &nbsp;
        <input 
          type="number" 
          value={timeDelay} 
          onChange={(e) => setTimeDelay(e.target.value)}
          className="delay-input"
        />
      </label>
    </div>

    <div className="mission-actions">
      <button 
        onClick={handleSendCommand} 
        className="mission-button send-command"
      >
        Send Command
      </button>
      <button 
        onClick={handleDisarmDrones} 
        className="mission-button cancel-mission"
      >
        Cancel Mission
      </button>
    </div>
  </div>

 

</div>


      <h2>Connected Drones</h2>

<div className="drone-list">
{drones.map((drone) => {
    const isStale = (new Date() / 1000 - drone.Update_Time) > STALE_DATA_THRESHOLD_SECONDS;
    const isExpanded = expandedDrone && expandedDrone.hw_ID === drone.hw_ID;

    return (
        <div 
            className={`drone-card ${isExpanded ? 'expanded' : ''}`} 
            key={drone.hw_ID} 
           
        >
                <h3 onClick={() => toggleDroneDetails(drone)}>
                    <span style={{ color: isStale ? 'red' : 'green' }}>●</span>
                    Drone {drone.hw_ID}
                </h3>
                <p>Mission: {drone.Mission}</p>
                <p>State: {drone.State}</p>
                <p>Follow Mode: {drone.Follow_Mode === 0 ? 'LEADER' : `Follows ${drone.Follow_Mode}`}</p>
                <p>Altitude: {drone.Position_Alt.toFixed(1)}m</p>
                <div className="drone-actions">
                    <span onClick={(e) => { e.stopPropagation(); setSelectedDrone(drone); }}>🔗 External View</span>
                </div>
                <div className="details-content">
                {isExpanded && <DroneDetail drone={drone} isAccordionView={true} />}
            </div>
        </div>
    );
})}
</div>


      <Globe drones={drones.map(drone => ({
      hw_ID: drone.hw_ID,
      position: [drone.Position_Lat, drone.Position_Long, drone.Position_Alt],
      state: drone.State,
      follow_mode: drone.Follow_Mode,
      altitude: drone.Position_Alt
    }))} />

    </div>
  );
};


export default Overview;
