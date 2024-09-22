// app/dashboard/drone-dashboard/src/pages/MissionConfig.js

import React, { useState, useEffect } from 'react';
import axios from 'axios';
import '../styles/MissionConfig.css';
import InitialLaunchPlot from '../components/InitialLaunchPlot';
import DroneConfigCard from '../components/DroneConfigCard';
import ControlButtons from '../components/ControlButtons';
import BriefingExport from '../components/BriefingExport';
import OriginModal from '../components/OriginModal'; // Import the OriginModal
import { getBackendURL } from '../utilities/utilities';
import DronePositionMap from '../components/DronePositionMap'; // Import the DronePositionMap

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
  const [showOriginModal, setShowOriginModal] = useState(false); // New state variable

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
        setOriginLat(response.data.lat);
        setOriginLon(response.data.lon);
      } catch (error) {
        console.error('Error fetching origin data:', error);
      }
    };
    fetchOrigin();
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

    // Validation: Check for duplicate position ID (allow user to proceed if they confirm)
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
    const allSameGcsIp = configData.every((drone) => drone.gcs_ip === configData[0]?.gcs_ip);

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
        handleSaveChangesToServer={() => handleSaveChangesToServer(configData, setConfigData)}
        handleRevertChanges={() => handleRevertChanges(setConfigData)}
        handleFileChange={(event) => handleFileChange(event, setConfigData)}
        exportConfig={() => exportConfig(configData)}
        openOriginModal={() => setShowOriginModal(true)} // Pass the function to open the modal
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
        />
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
            />
          ))}
        </div>
        <div className="initial-launch-plot">
          <InitialLaunchPlot drones={configData} onDroneClick={setEditingDroneId} />
          <DronePositionMap originLat={originLat} originLon={originLon} drones={configData} />
        </div>
      </div>
    </div>
  );
};

export default MissionConfig;
