import React, { useState, useEffect } from 'react';
import axios from 'axios';
import '../styles/MissionConfig.css';
import InitialLaunchPlot from '../components/InitialLaunchPlot';
import DroneConfigCard from '../components/DroneConfigCard';
import ControlButtons from '../components/ControlButtons';
import BriefingExport from '../components/BriefingExport';
import OriginModal from '../components/OriginModal';
import { getBackendURL } from '../utilities/utilities';
import DronePositionMap from '../components/DronePositionMap';

import {
  handleSaveChangesToServer,
  handleRevertChanges,
  handleFileChange,
  exportConfig,
} from '../utilities/missionConfigUtilities';

const MissionConfig = () => {
  // State variables
  const [configData, setConfigData] = useState([]);
  const [editingDroneId, setEditingDroneId] = useState(null);
  const [originLat, setOriginLat] = useState('');
  const [originLon, setOriginLon] = useState('');
  const [showOriginModal, setShowOriginModal] = useState(false);
  const [deviationData, setDeviationData] = useState({});
  const [originAvailable, setOriginAvailable] = useState(false);
  const [telemetryData, setTelemetryData] = useState({});
  const [networkInfo, setNetworkInfo] = useState({}); // New state for network info

  // Compute available hardware IDs for new drones
  const allHwIds = new Set(configData.map((drone) => parseInt(drone.hw_id)));
  const maxHwId = Math.max(0, ...Array.from(allHwIds)) + 1;
  const availableHwIds = Array.from({ length: maxHwId }, (_, i) => i + 1).filter(
    (id) => !allHwIds.has(id)
  );

  // Fetch configuration data from the backend when the component mounts
  useEffect(() => {
    const fetchData = async () => {
      const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
      console.log(`Fetching config data from URL: ${backendURL}/get-config-data`);
      try {
        const response = await axios.get(`${backendURL}/get-config-data`);
        console.log('Received config data:', response.data);
        setConfigData(response.data);
      } catch (error) {
        console.error('Error fetching config data:', error);
      }
    };
    fetchData();
  }, []);

  // Fetch origin coordinates from the backend when the component mounts
  useEffect(() => {
    const fetchOrigin = async () => {
      const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
      try {
        const response = await axios.get(`${backendURL}/get-origin`);
        if (response.data.lat && response.data.lon) {
          setOriginLat(response.data.lat);
          setOriginLon(response.data.lon);
          setOriginAvailable(true); // Origin is available
        } else {
          setOriginAvailable(false);
        }
      } catch (error) {
        console.error('Error fetching origin data:', error);
        setOriginAvailable(false);
      }
    };
    fetchOrigin();
  }, []);

  // Fetch deviation data periodically (every 2 seconds)
  useEffect(() => {
    if (!originAvailable) return; // Do not fetch deviations if origin is not set

    const fetchDeviationData = async () => {
      const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
      try {
        const response = await axios.get(`${backendURL}/get-position-deviations`);
        console.log('Received deviation data:', response.data);
        setDeviationData(response.data);
      } catch (error) {
        console.error('Error fetching deviation data from GCS:', error);
      }
    };

    fetchDeviationData();
    const interval = setInterval(fetchDeviationData, 2000); // Fetch every 2 seconds

    return () => clearInterval(interval); // Cleanup on unmount
  }, [originAvailable]);

  // Fetch telemetry data periodically (every 2 seconds)
  useEffect(() => {
    const fetchTelemetryData = async () => {
      const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
      try {
        const response = await axios.get(`${backendURL}/telemetry`);
        console.log('Received telemetry data:', response.data);
        setTelemetryData(response.data);
      } catch (error) {
        console.error('Error fetching telemetry data from GCS:', error);
      }
    };

    fetchTelemetryData();
    const interval = setInterval(fetchTelemetryData, 2000); // Fetch every 2 seconds

    return () => clearInterval(interval); // Cleanup on unmount
  }, []);

  // Fetch network info for each drone
  //TODO: Later on craete endpoing in GCS and ask wifi fom that insead of asking each drone 
  useEffect(() => {
    const fetchNetworkInfo = async () => {
      const backendURL = getBackendURL(process.env.DRONE_APP_FLASK_PORT || '7070');
      try {
        const response = await axios.get(`${backendURL}/network-info`); // Get network info from Flask API
        setNetworkInfo(response.data); // Store network info
      } catch (error) {
        console.error('Error fetching network information:', error);
      }
    };
    fetchNetworkInfo();
    const interval = setInterval(fetchNetworkInfo, 5000); // Fetch network info every 5 seconds
    return () => clearInterval(interval); // Cleanup on unmount
  }, []);

  // Save changes for a specific drone
  const saveChanges = (originalHwId, updatedData) => {
    // Validation: Check for duplicate hardware ID
    if (
      configData.some((d) => d.hw_id === updatedData.hw_id && d.hw_id !== originalHwId)
    ) {
      alert('The selected Hardware ID is already in use. Please choose another one.');
      return;
    }

    // Validation: Check for duplicate position ID
    if (
      configData.some((d) => d.pos_id === updatedData.pos_id && d.hw_id !== originalHwId)
    ) {
      if (
        !window.confirm(
          `Position ID ${updatedData.pos_id} is already assigned to another drone. Do you want to proceed?`
        )
      ) {
        return;
      }
    }

    // Update the configuration data with the changes
    setConfigData((prevConfig) =>
      prevConfig.map((drone) => (drone.hw_id === originalHwId ? updatedData : drone))
    );
    setEditingDroneId(null);
  };

  // Add a new drone to the configuration
  const addNewDrone = () => {
    const newHwId = availableHwIds[0].toString();

    // Determine if all existing drones have the same GCS IP
    const allSameGcsIp = configData.every(
      (drone) => drone.gcs_ip === configData[0]?.gcs_ip
    );

    // Extract the common subnet from the existing IPs
    const commonSubnet =
      configData.length > 0
        ? configData[0].ip.split('.').slice(0, -1).join('.') + '.'
        : '';

    const newDrone = {
      hw_id: newHwId,
      ip: commonSubnet,
      mavlink_port: (14550 + parseInt(newHwId)).toString(),
      debug_port: (13540 + parseInt(newHwId)).toString(),
      gcs_ip: allSameGcsIp ? configData[0].gcs_ip : '',
      x: '0',
      y: '0',
      pos_id: newHwId,
    };

    setConfigData((prevConfig) => [...prevConfig, newDrone]);
  };

  // Remove a drone from the configuration
  const removeDrone = (hw_id) => {
    if (window.confirm(`Are you sure you want to remove Drone ${hw_id}?`)) {
      setConfigData((prevConfig) => prevConfig.filter((drone) => drone.hw_id !== hw_id));
    }
  };

  // Handle origin submission from the modal
  const handleOriginSubmit = (lat, lon) => {
    setOriginLat(lat);
    setOriginLon(lon);
    setShowOriginModal(false);
    // Send origin to backend to store it
    const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
    axios
      .post(`${backendURL}/set-origin`, {
        lat: lat,
        lon: lon,
      })
      .then(() => {
        console.log('Origin saved to backend');
        setOriginAvailable(true);
      })
      .catch((error) => {
        console.error('Error saving origin to backend:', error);
      });
  };

  // Sort the configuration data by hardware ID for consistent display
  const sortedConfigData = [...configData].sort(
    (a, b) => parseInt(a.hw_id) - parseInt(b.hw_id)
  );

  return (
    <div className="mission-config-container">
      <h2>Mission Configuration</h2>

      {/* Control Buttons for Adding, Saving, Importing, and Exporting Configuration */}
      <ControlButtons
        addNewDrone={addNewDrone}
        handleSaveChangesToServer={() =>
          handleSaveChangesToServer(configData, setConfigData)
        }
        handleRevertChanges={() => handleRevertChanges(setConfigData)}
        handleFileChange={(event) => handleFileChange(event, setConfigData)}
        exportConfig={() => exportConfig(configData)}
        openOriginModal={() => setShowOriginModal(true)}
      />

      {/* Briefing Export Component for Exporting to KML and Printing Mission Briefing */}
      <BriefingExport
        configData={configData}
        originLat={originLat}
        originLon={originLon}
        setOriginLat={setOriginLat}
        setOriginLon={setOriginLon}
      />

      {/* Origin Modal */}
      {showOriginModal && (
        <OriginModal
          isOpen={showOriginModal}
          onClose={() => setShowOriginModal(false)}
          onSubmit={handleOriginSubmit}
          telemetryData={telemetryData} // Pass telemetry data
          configData={configData} // Pass config data
        />
      )}

      {/* Show origin warning if not available */}
      {!originAvailable && (
        <div className="origin-warning">
          <p>
            Origin coordinates are not set. Please set the origin to display deviation
            data.
          </p>
        </div>
      )}

      {/* Main Content: Drone Configuration Cards and Initial Launch Plot */}
      <div className="content-flex">
        <div className="drone-cards">
          {sortedConfigData.map((drone) => (
            <DroneConfigCard
              key={drone.hw_id}
              drone={drone}
              configData={configData}
              availableHwIds={availableHwIds}
              editingDroneId={editingDroneId}
              setEditingDroneId={setEditingDroneId}
              saveChanges={saveChanges}
              removeDrone={removeDrone}
              networkInfo={networkInfo} // Pass network info to DroneConfigCard
            />
          ))}
        </div>
        <div className="initial-launch-plot">
          <InitialLaunchPlot
            drones={configData}
            onDroneClick={setEditingDroneId}
            deviationData={deviationData} // Pass deviation data to the plot
          />
          <DronePositionMap
            originLat={originLat}
            originLon={originLon}
            drones={configData}
          />
        </div>
      </div>
    </div>
  );
};

export default MissionConfig;
