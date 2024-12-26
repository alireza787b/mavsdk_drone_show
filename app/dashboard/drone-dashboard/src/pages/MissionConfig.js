// src/pages/MissionConfig.js

import React, { useState, useEffect } from 'react';
import axios from 'axios';
import '../styles/MissionConfig.css';
import InitialLaunchPlot from '../components/InitialLaunchPlot';
import DroneConfigCard from '../components/DroneConfigCard';
import ControlButtons from '../components/ControlButtons';
import BriefingExport from '../components/BriefingExport';
import OriginModal from '../components/OriginModal';
import ConfirmationDialog from '../components/ConfirmationDialog'; // Import ConfirmationDialog
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
  const [networkInfo, setNetworkInfo] = useState([]);
  const [gitStatusData, setGitStatusData] = useState({});

  const [loading, setLoading] = useState(false); // Loading state for save operation

  // Heartbeat data from GCS
  const [heartbeats, setHeartbeats] = useState({}); // shape: { "1": { pos_id, ip, timestamp }, "2": {...}, ... }


  // Position ID to Initial Position Mapping
  const positionIdMapping = configData.reduce((acc, drone) => {
    if (drone.pos_id) {
      acc[drone.pos_id] = { x: drone.x, y: drone.y };
    }
    return acc;
  }, {});

  // Compute available hardware IDs for new drones
  const allHwIds = new Set(configData.map((drone) => drone.hw_id));
  const maxHwId = Math.max(0, ...Array.from(allHwIds, id => parseInt(id))) + 1;
  const availableHwIds = Array.from({ length: maxHwId }, (_, i) => (i + 1).toString()).filter(
    (id) => !allHwIds.has(id)
  );

  // -----------------------------
  // Fetch config data on mount
  // -----------------------------
  useEffect(() => {
    const fetchData = async () => {
      const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
      try {
        const response = await axios.get(`${backendURL}/get-config-data`);
        setConfigData(response.data);
      } catch (error) {
        console.error('Error fetching config data:', error);
      }
    };
    fetchData();
  }, []);

  // -----------------------------
  // Fetch origin on mount
  // -----------------------------
  useEffect(() => {
    const fetchOrigin = async () => {
      const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
      try {
        const response = await axios.get(`${backendURL}/get-origin`);
        if (response.data.lat && response.data.lon) {
          setOriginLat(response.data.lat);
          setOriginLon(response.data.lon);
          setOriginAvailable(true);
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

  // -----------------------------
  // Fetch deviation data
  // -----------------------------
  useEffect(() => {
    if (!originAvailable) return;

    const fetchDeviationData = async () => {
      const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
      try {
        const response = await axios.get(`${backendURL}/get-position-deviations`);
        setDeviationData(response.data);
      } catch (error) {
        console.error('Error fetching deviation data:', error);
      }
    };

    fetchDeviationData();
    const interval = setInterval(fetchDeviationData, 2000);
    return () => clearInterval(interval);
  }, [originAvailable]);

  // -----------------------------
  // Fetch telemetry data
  // -----------------------------
  useEffect(() => {
    const fetchTelemetryData = async () => {
      const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
      try {
        const response = await axios.get(`${backendURL}/telemetry`);
        setTelemetryData(response.data);
      } catch (error) {
        console.error('Error fetching telemetry data:', error);
      }
    };

    fetchTelemetryData();
    const interval = setInterval(fetchTelemetryData, 2000);
    return () => clearInterval(interval);
  }, []);

  // -----------------------------
  // Fetch Git status data
  // -----------------------------

  useEffect(() => {
    const fetchGitStatus = async () => {
      const backendPort = process.env.REACT_APP_FLASK_PORT || '5000';
      const backendURL = getBackendURL(backendPort);
      try {
        const response = await axios.get(`${backendURL}/git-status`);
        setGitStatusData(response.data);
        console.log('Git Status Data Fetched:', response.data); // Debugging
      } catch (error) {
        console.error('Error fetching Git status data:', error);
      }
    };
  
    fetchGitStatus();
    const interval = setInterval(fetchGitStatus, 10000); // Poll every 10 seconds
    return () => clearInterval(interval);
  }, []);
  

  // -----------------------------
  // Fetch network info
  // -----------------------------
  useEffect(() => {
    const fetchNetworkInfo = async () => {
      const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
      try {
        const response = await axios.get(`${backendURL}/get-network-info`);
        setNetworkInfo(response.data);
      } catch (error) {
        console.error('Error fetching network information:', error);
      }
    };

    fetchNetworkInfo();
    const interval = setInterval(fetchNetworkInfo, 10000); // Fetch network info every 10 seconds
    return () => clearInterval(interval);
  }, []);

  // -----------------------------
  // Fetch heartbeats
  // -----------------------------
  useEffect(() => {
    const fetchHeartbeats = async () => {
      const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
      try {
        const response = await axios.get(`${backendURL}/get-heartbeats`);
        setHeartbeats(response.data || {});
      } catch (error) {
        console.error('Error fetching heartbeats:', error);
      }
    };

    fetchHeartbeats();
    const interval = setInterval(fetchHeartbeats, 5000); // Poll every 5s
    return () => clearInterval(interval);
  }, []);

  // -----------------------------
  // Detect & Add any "new" drones
  // automatically if we see a heartbeat
  // for hw_id not in config
  // -----------------------------
  useEffect(() => {
    // Get all hw_ids from heartbeats
    const heartbeatHwIds = Object.keys(heartbeats);

    const newDrones = [];
    for (const hbHwId of heartbeatHwIds) {
      if (!configData.some((d) => d.hw_id === hbHwId)) {
        // It's new
        const hb = heartbeats[hbHwId];
        newDrones.push({
          hw_id: hbHwId,
          pos_id: hb.pos_id || hbHwId, // fallback
          ip: hb.ip || '',
          x: '0',
          y: '0',
          mavlink_port: (14550 + parseInt(hbHwId)).toString(),
          debug_port: (13540 + parseInt(hbHwId)).toString(),
          gcs_ip:
            configData.length > 0 ? configData[0].gcs_ip : '', // fallback to first known
          isNew: true,
        });
      }
    }

    if (newDrones.length > 0) {
      setConfigData((prev) => [...prev, ...newDrones]);
    }
  }, [heartbeats, configData]);

  // -----------------------------
  // Save changes for a drone
  // -----------------------------
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

    // Merge changes and unset isNew
    setConfigData((prevConfig) =>
      prevConfig.map((drone) =>
        drone.hw_id === originalHwId ? { ...updatedData, isNew: false } : drone
      )
    );
    setEditingDroneId(null);
  };

  // -----------------------------
  // Add new drone (manual button)
  // -----------------------------
  const addNewDrone = () => {
    const newHwId = availableHwIds[0]?.toString() || (maxHwId).toString();
    if (!newHwId) return;

    const allSameGcsIp = configData.every(
      (drone) => drone.gcs_ip === configData[0]?.gcs_ip
    );
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
      isNew: true,
    };

    setConfigData((prevConfig) => [...prevConfig, newDrone]);
  };

  // -----------------------------
  // Remove drone
  // -----------------------------
  const removeDrone = (hw_id) => {
    if (window.confirm(`Are you sure you want to remove Drone ${hw_id}?`)) {
      setConfigData((prevConfig) => prevConfig.filter((drone) => drone.hw_id !== hw_id));
    }
  };

  // -----------------------------
  // Origin modal submission
  // -----------------------------
  const handleOriginSubmit = (lat, lon) => {
    setOriginLat(lat);
    setOriginLon(lon);
    setShowOriginModal(false);
    const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
    axios
      .post(`${backendURL}/set-origin`, {
        lat: lat,
        lon: lon,
      })
      .then(() => {
        setOriginAvailable(true);
      })
      .catch((error) => {
        console.error('Error saving origin to backend:', error);
      });
  };

  // -----------------------------
  // Import config (file)
  // -----------------------------
  const handleFileChangeWrapper = (event) => {
    handleFileChange(event, setConfigData);
  };

  // -----------------------------
  // Revert config
  // -----------------------------
  const handleRevertChangesWrapper = () => {
    handleRevertChanges(setConfigData);
  };

  // -----------------------------
  // Save config to server
  // -----------------------------
  const handleSaveChangesToServerWrapper = () => {
    handleSaveChangesToServer(configData, setConfigData, setLoading);
  };

  // -----------------------------
  // Export config
  // -----------------------------
  const handleExportConfigWrapper = () => {
    exportConfig(configData);
  };

  // Sort config for display
  const sortedConfigData = [...configData].sort(
    (a, b) => parseInt(a.hw_id) - parseInt(b.hw_id)
  );

  return (
    <div className="mission-config-container">
      <h2>Mission Configuration</h2>

      <ControlButtons
        addNewDrone={addNewDrone}
        handleSaveChangesToServer={handleSaveChangesToServerWrapper}
        handleRevertChanges={handleRevertChangesWrapper}
        handleFileChange={handleFileChangeWrapper}
        exportConfig={handleExportConfigWrapper}
        openOriginModal={() => setShowOriginModal(true)}
        configData={configData}
        setConfigData={setConfigData}
        loading={loading}
      />

      <BriefingExport
        configData={configData}
        originLat={originLat}
        originLon={originLon}
        setOriginLat={setOriginLat}
        setOriginLon={setOriginLon}
      />

      {showOriginModal && (
        <OriginModal
          isOpen={showOriginModal}
          onClose={() => setShowOriginModal(false)}
          onSubmit={handleOriginSubmit}
          telemetryData={telemetryData}
          configData={configData}
        />
      )}

      {!originAvailable && (
        <div className="origin-warning">
          <p>
            Origin coordinates are not set. Please set the origin to display deviation data.
          </p>
        </div>
      )}

      <div className="content-flex">
        <div className="drone-cards">
          {sortedConfigData.map((drone) => (
            <DroneConfigCard
              key={drone.hw_id}
              drone={drone}
              gitStatus={gitStatusData[drone.hw_id] || null}
              configData={configData}
              availableHwIds={availableHwIds}
              editingDroneId={editingDroneId}
              setEditingDroneId={setEditingDroneId}
              saveChanges={saveChanges}
              removeDrone={removeDrone}
              networkInfo={networkInfo.find((info) => info.hw_id === drone.hw_id)}
              heartbeatData={heartbeats[drone.hw_id] || null} // Pass the heartbeat data
              positionIdMapping={positionIdMapping} // Pass the mapping
            />
          ))}
        </div>
        <div className="initial-launch-plot">
          <InitialLaunchPlot
            drones={configData}
            onDroneClick={setEditingDroneId}
            deviationData={deviationData}
          />
          <DronePositionMap originLat={originLat} originLon={originLon} drones={configData} />
        </div>
      </div>
    </div>
  );
};

export default MissionConfig;
