import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import axios from 'axios';
import '../styles/MissionConfig.css';
import InitialLaunchPlot from '../components/InitialLaunchPlot';
import DroneConfigCard from '../components/DroneConfigCard';
import ControlButtons from '../components/ControlButtons';
import { getBackendURL } from '../utilities/utilities';
import { handleSaveChangesToServer, handleRevertChanges, handleFileChange, exportConfig } from '../utilities/missionConfigUtilities';

const MissionConfig = () => {
  const [configData, setConfigData] = useState([]);
  const [editingDroneId, setEditingDroneId] = useState(null);

  const allHwIds = new Set(configData.map(drone => parseInt(drone.hw_id)));
  const maxHwId = Math.max(0, ...allHwIds) + 1;
  const availableHwIds = Array.from({ length: maxHwId }, (_, i) => i + 1).filter(id => !allHwIds.has(id));

  useEffect(() => {
    const fetchData = async () => {
      const backendURL = getBackendURL();
      try {
        const response = await axios.get(`${backendURL}/get-config-data`);
        setConfigData(response.data);
      } catch (error) {
        console.error("Error fetching config data:", error);
      }
    };
    fetchData();
  }, []);

  const saveChanges = (hw_id, updatedData) => {
    const { hw_id: newHwId } = updatedData;
    if (configData.some(d => d.hw_id === newHwId && d.hw_id !== hw_id)) {
      alert("The selected hardware ID is already in use. Please choose another one.");
      return;
    }
    setConfigData(prevConfig => prevConfig.map(drone => drone.hw_id === hw_id ? updatedData : drone));
    setEditingDroneId(null);
  };

  const addNewDrone = () => {
    const newHwId = availableHwIds[0].toString();
    const allSameGcsIp = configData.every(drone => drone.gcs_ip === configData[0].gcs_ip);
    const commonSubnet = configData.length > 0 ? configData[0].ip.split('.').slice(0, -1).join('.') + '.' : "";

    const newDrone = {
      hw_id: newHwId,
      ip: commonSubnet,
      mavlink_port: (14550 + parseInt(newHwId)).toString(),
      debug_port: (13540 + parseInt(newHwId)).toString(),
      gcs_ip: allSameGcsIp ? configData[0].gcs_ip : "",
      x: "0",
      y: "0",
      pos_id: newHwId
    };

    setConfigData(prevConfig => [...prevConfig, newDrone]);
  };

  const removeDrone = (hw_id) => {
    if (window.confirm(`Are you sure you want to remove Drone ${hw_id}?`)) {
      setConfigData(prevConfig => prevConfig.filter(drone => drone.hw_id !== hw_id));
    }
  };

  const sortedConfigData = [...configData].sort((a, b) => a.hw_id - b.hw_id);

  return (
    <div className="mission-config-container">
      <h2>Mission Configuration</h2>
      <ControlButtons
        addNewDrone={addNewDrone}
        handleSaveChangesToServer={() => handleSaveChangesToServer(configData, setConfigData)}
        handleRevertChanges={() => handleRevertChanges(setConfigData)}
        handleFileChange={(event) => handleFileChange(event, setConfigData)}
        exportConfig={() => exportConfig(configData)}
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
