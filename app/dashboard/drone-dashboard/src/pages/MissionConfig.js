// app/dashboard/drone-dashboard/src/pages/MissionConfig.js

import React, { useState, useEffect } from 'react';
import axios from 'axios';
import '../styles/MissionConfig.css';
import InitialLaunchPlot from '../components/InitialLaunchPlot';
import DroneConfigCard from '../components/DroneConfigCard';
import ControlButtons from '../components/ControlButtons';
import { getBackendURL } from '../utilities/utilities';
import { 
  handleSaveChangesToServer, 
  handleRevertChanges, 
  handleFileChange, 
  exportConfig 
} from '../utilities/missionConfigUtilities';

const MissionConfig = () => {
  // State to hold the configuration data for drones
  const [configData, setConfigData] = useState([]);
  
  // State to track which drone is currently being edited
  const [editingDroneId, setEditingDroneId] = useState(null);

  // Calculate available Hardware IDs
  const allHwIds = new Set(configData.map(drone => parseInt(drone.hw_id)));
  const maxHwId = configData.length > 0 ? Math.max(...allHwIds) + 1 : 1;
  const availableHwIds = Array.from({ length: maxHwId }, (_, i) => i + 1).filter(id => !allHwIds.has(id));

  // Loading states for various operations
  const [isSaving, setIsSaving] = useState(false);
  const [isReverting, setIsReverting] = useState(false);
  const [isExporting, setIsExporting] = useState(false);

  // Fetch configuration data when the component mounts
  useEffect(() => {
    const fetchData = async () => {
      const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
      console.log(`Fetching config data from URL: ${backendURL}/get-config-data`);
      try {
        const response = await axios.get(`${backendURL}/get-config-data`);
        setConfigData(response.data);
      } catch (error) {
        console.error("Error fetching config data:", error);
        alert("Failed to fetch configuration data. Please try again later.");
      }
    };
    fetchData();
  }, []);

  /**
   * Function to save changes made to a drone's configuration
   * @param {string} hw_id - The original Hardware ID of the drone
   * @param {object} updatedData - The updated drone data
   */
  const saveChanges = (hw_id, updatedData) => {
    const { hw_id: newHwId, pos_id: newPosId } = updatedData;

    // Validation: Check if the newHwId is already assigned to a different drone
    if (configData.some(drone => drone.hw_id === newHwId && drone.hw_id !== hw_id)) {
      alert(`Hardware ID ${newHwId} is already in use. Please choose another.`);
      return;
    }

    // Validation: Check if the newPosId is already assigned to a different drone
    if (configData.some(drone => drone.pos_id === newPosId && drone.hw_id !== hw_id)) {
      alert(`Position ID ${newPosId} is already assigned to another drone. Please choose another.`);
      return;
    }

    // Update configData
    setConfigData(prevConfig => prevConfig.map(drone => 
      drone.hw_id === hw_id ? { ...updatedData, hw_id: newHwId, pos_id: newPosId } : drone
    ));

    // Exit editing mode
    setEditingDroneId(null);
  };

  /**
   * Function to add a new drone to the configuration
   */
  const addNewDrone = () => {
    if (availableHwIds.length === 0) {
      alert("No available Hardware IDs to assign. Please remove an existing drone before adding a new one.");
      return;
    }

    const newHwId = availableHwIds[0].toString();
    const allSameGcsIp = configData.length > 0 && configData.every(drone => drone.gcs_ip === configData[0].gcs_ip);
    const commonSubnet = configData.length > 0 ? configData[0].ip.split('.').slice(0, -1).join('.') + '.' : "100.84.0.";

    // Assign the next available pos_id
    const existingPosIds = new Set(configData.map(drone => parseInt(drone.pos_id)));
    let newPosId = 1;
    while (existingPosIds.has(newPosId)) {
      newPosId += 1;
    }

    const newDrone = {
      hw_id: newHwId,
      pos_id: newPosId.toString(),
      ip: commonSubnet,
      mavlink_port: (14550 + parseInt(newHwId)).toString(),
      debug_port: (13540 + parseInt(newHwId)).toString(),
      gcs_ip: allSameGcsIp ? configData[0].gcs_ip : "100.84.222.4",
      x: "0",
      y: "0"
    };

    // Update configData with the new drone
    setConfigData(prevConfig => [...prevConfig, newDrone]);
  };

  /**
   * Function to remove a drone from the configuration
   * @param {string} hw_id - The Hardware ID of the drone to remove
   */
  const removeDrone = (hw_id) => {
    if (window.confirm(`Are you sure you want to remove Drone ${hw_id}?`)) {
      // Remove the drone from configData
      setConfigData(prevConfig => prevConfig.filter(drone => drone.hw_id !== hw_id));
    }
  };

  /**
   * Function to handle saving changes to the server
   */
  const handleSaveToServer = async () => {
    setIsSaving(true);
    await handleSaveChangesToServer(configData, setConfigData);
    setIsSaving(false);
  };

  /**
   * Function to handle reverting changes from the server
   */
  const handleRevert = async () => {
    setIsReverting(true);
    await handleRevertChanges(setConfigData);
    setIsReverting(false);
  };

  /**
   * Function to handle file (CSV) import
   * @param {Event} event - The file input change event
   */
  const handleFileImport = (event) => {
    handleFileChange(event, setConfigData);
  };

  /**
   * Function to handle exporting configuration data as CSV
   */
  const handleExport = () => {
    exportConfig(configData);
  };

  // Sort drones based on pos_id for consistent display
  const sortedConfigData = [...configData].sort((a, b) => parseInt(a.pos_id) - parseInt(b.pos_id));

  return (
    <div className="mission-config-container">
      <h2>Mission Configuration</h2>
      <ControlButtons
        addNewDrone={addNewDrone}
        handleSaveChangesToServer={handleSaveToServer}
        handleRevertChanges={handleRevert}
        handleFileChange={handleFileImport}
        exportConfig={handleExport}
        isSaving={isSaving}
        isReverting={isReverting}
        isExporting={isExporting}
      />
      <div className="content-flex">
        <div className="drone-cards">
          {sortedConfigData.map(drone => (
            <DroneConfigCard
              key={drone.hw_id}
              drone={drone}
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
        </div>
      </div>
    </div>
  );
};

MissionConfig.propTypes = {
  // No props are currently being used, but this is a placeholder for future use
};

export default MissionConfig;
