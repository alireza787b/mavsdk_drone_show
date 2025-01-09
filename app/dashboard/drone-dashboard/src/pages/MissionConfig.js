// src/pages/MissionConfig.js

import React, { useState, useEffect } from 'react';
import axios from 'axios';
import '../styles/MissionConfig.css';

// Components
import InitialLaunchPlot from '../components/InitialLaunchPlot';
import DroneConfigCard from '../components/DroneConfigCard';
import ControlButtons from '../components/ControlButtons';
import BriefingExport from '../components/BriefingExport';
import OriginModal from '../components/OriginModal';
import ConfirmationDialog from '../components/ConfirmationDialog'; 
import DronePositionMap from '../components/DronePositionMap';

// Utilities
import {
  handleSaveChangesToServer,
  handleRevertChanges,
  handleFileChange,
  exportConfig,
} from '../utilities/missionConfigUtilities';
import { getBackendURL } from '../utilities/utilities';

const MissionConfig = () => {
  // -----------------------------------------------------
  // State variables
  // -----------------------------------------------------
  const [configData, setConfigData] = useState([]);
  const [editingDroneId, setEditingDroneId] = useState(null);

  // Origin
  const [originLat, setOriginLat] = useState('');
  const [originLon, setOriginLon] = useState('');
  const [originAvailable, setOriginAvailable] = useState(false);
  const [showOriginModal, setShowOriginModal] = useState(false);

  // Deviations / Telemetry
  const [deviationData, setDeviationData] = useState({});
  const [telemetryData, setTelemetryData] = useState({});

  // Git & Network
  const [networkInfo, setNetworkInfo] = useState([]);
  const [gitStatusData, setGitStatusData] = useState({});
  const [gcsGitStatus, setGcsGitStatus] = useState(null);

  // Heartbeat
  const [heartbeats, setHeartbeats] = useState({});

  // UI & Loading
  const [loading, setLoading] = useState(false);

  // -----------------------------------------------------
  // Derived Data & Helpers
  // -----------------------------------------------------
  // Create positionIdMapping for quick access in DroneConfigCard
  const positionIdMapping = configData.reduce((acc, drone) => {
    if (drone.pos_id) {
      acc[drone.pos_id] = { x: drone.x, y: drone.y };
    }
    return acc;
  }, {});

  // Available HwIds
  const allHwIds = new Set(configData.map((drone) => drone.hw_id));
  const maxHwId =
    Math.max(0, ...Array.from(allHwIds, (id) => parseInt(id, 10))) + 1;
  const availableHwIds = Array.from(
    { length: maxHwId },
    (_, i) => (i + 1).toString()
  ).filter((id) => !allHwIds.has(id));

  // -----------------------------------------------------
  // Fetch config data on mount
  // -----------------------------------------------------
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

  // -----------------------------------------------------
  // Fetch origin on mount
  // -----------------------------------------------------
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

  // -----------------------------------------------------
  // Fetch deviation data (if origin is available)
  // -----------------------------------------------------
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
    const interval = setInterval(fetchDeviationData, 5000);
    return () => clearInterval(interval);
  }, [originAvailable]);

  // -----------------------------------------------------
  // Fetch telemetry data
  // -----------------------------------------------------
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

  // -----------------------------------------------------
  // Fetch GCS Git status
  // -----------------------------------------------------
  useEffect(() => {
    const fetchGcsGitStatus = async () => {
      const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
      try {
        const response = await axios.get(`${backendURL}/get-gcs-git-status`);
        setGcsGitStatus(response.data);
      } catch (error) {
        console.error('Error fetching GCS Git status:', error);
      }
    };

    fetchGcsGitStatus();
    const interval = setInterval(fetchGcsGitStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  // -----------------------------------------------------
  // Fetch Git status data
  // -----------------------------------------------------
  useEffect(() => {
    const fetchGitStatus = async () => {
      const backendPort = process.env.REACT_APP_FLASK_PORT || '5000';
      const backendURL = getBackendURL(backendPort);
      try {
        const response = await axios.get(`${backendURL}/git-status`);
        setGitStatusData(response.data);
      } catch (error) {
        console.error('Error fetching Git status data:', error);
      }
    };

    fetchGitStatus();
    const interval = setInterval(fetchGitStatus, 20000);
    return () => clearInterval(interval);
  }, []);

  // -----------------------------------------------------
  // Fetch network info
  // -----------------------------------------------------
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
    const interval = setInterval(fetchNetworkInfo, 10000);
    return () => clearInterval(interval);
  }, []);

  // -----------------------------------------------------
  // Fetch heartbeats
  // -----------------------------------------------------
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
    const interval = setInterval(fetchHeartbeats, 5000);
    return () => clearInterval(interval);
  }, []);

  // -----------------------------------------------------
  // Detect & add "new" drones automatically by heartbeat
  // -----------------------------------------------------
  useEffect(() => {
    const heartbeatHwIds = Object.keys(heartbeats);

    const newDrones = [];
    for (const hbHwId of heartbeatHwIds) {
      if (!configData.some((d) => d.hw_id === hbHwId)) {
        // It's new
        const hb = heartbeats[hbHwId];
        newDrones.push({
          hw_id: hbHwId,
          pos_id: hb.pos_id || hbHwId,
          ip: hb.ip || '',
          x: '0',
          y: '0',
          mavlink_port: (14550 + parseInt(hbHwId, 10)).toString(),
          debug_port: (13540 + parseInt(hbHwId, 10)).toString(),
          gcs_ip: configData.length > 0 ? configData[0].gcs_ip : '',
          isNew: true,
        });
      }
    }

    if (newDrones.length > 0) {
      setConfigData((prev) => [...prev, ...newDrones]);
    }
  }, [heartbeats, configData]);

  // -----------------------------------------------------
  // CRUD operations
  // -----------------------------------------------------
  // Save changes for a drone
  const saveChanges = (originalHwId, updatedData) => {
    // Check for duplicate hardware ID
    if (
      configData.some((d) => d.hw_id === updatedData.hw_id && d.hw_id !== originalHwId)
    ) {
      alert('The selected Hardware ID is already in use. Please choose another one.');
      return;
    }

    // Merge changes
    setConfigData((prevConfig) =>
      prevConfig.map((drone) =>
        drone.hw_id === originalHwId ? { ...updatedData, isNew: false } : drone
      )
    );
    setEditingDroneId(null);
  };

  // Add new drone (manual button)
  const addNewDrone = () => {
    const newHwId = availableHwIds[0]?.toString() || maxHwId.toString();
    if (!newHwId) return;

    const allSameGcsIp = configData.every(
      (drone) => drone.gcs_ip === configData[0]?.gcs_ip
    );
    const commonSubnet = configData.length > 0
      ? configData[0].ip.split('.').slice(0, -1).join('.') + '.'
      : '';

    const newDrone = {
      hw_id: newHwId,
      ip: commonSubnet,
      mavlink_port: (14550 + parseInt(newHwId, 10)).toString(),
      debug_port: (13540 + parseInt(newHwId, 10)).toString(),
      gcs_ip: allSameGcsIp ? configData[0].gcs_ip : '',
      x: '0',
      y: '0',
      pos_id: newHwId,
      isNew: true,
    };

    setConfigData((prevConfig) => [...prevConfig, newDrone]);
  };

  // Remove drone
  const removeDrone = (hw_id) => {
    if (window.confirm(`Are you sure you want to remove Drone ${hw_id}?`)) {
      setConfigData((prevConfig) => prevConfig.filter((drone) => drone.hw_id !== hw_id));
    }
  };

  // -----------------------------------------------------
  // Origin Modal submission
  // -----------------------------------------------------
  const handleOriginSubmit = (lat, lon) => {
    setOriginLat(lat);
    setOriginLon(lon);
    setShowOriginModal(false);

    const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
    axios.post(`${backendURL}/set-origin`, { lat, lon })
      .then(() => {
        setOriginAvailable(true);
      })
      .catch((error) => {
        console.error('Error saving origin to backend:', error);
      });
  };

  // -----------------------------------------------------
  // File ops & config save
  // -----------------------------------------------------
  const handleFileChangeWrapper = (e) => {
    handleFileChange(e, setConfigData);
  };

  const handleRevertChangesWrapper = () => {
    handleRevertChanges(setConfigData);
  };

  const handleSaveChangesToServerWrapper = () => {
    handleSaveChangesToServer(configData, setConfigData, setLoading);
  };

  const handleExportConfigWrapper = () => {
    exportConfig(configData);
  };

  // Sort config data for display
  const sortedConfigData = [...configData].sort(
    (a, b) => parseInt(a.hw_id, 10) - parseInt(b.hw_id, 10)
  );

  // -----------------------------------------------------
  // Render
  // -----------------------------------------------------
  return (
    <div className="mission-config-container">
      <h2>Mission Configuration</h2>

      {/* 
        Organized Top Control Buttons 
        (Save, Add, Import/Export, Revert, Set Origin, etc.) 
      */}
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

      {/* 
        Optional: Additional briefing or summary info 
        about the current mission configuration
      */}
      <BriefingExport
        configData={configData}
        originLat={originLat}
        originLon={originLon}
        setOriginLat={setOriginLat}
        setOriginLon={setOriginLon}
      />

      {/* 
        Prompt user to set origin if not available 
      */}
      {!originAvailable && (
        <div className="origin-warning">
          <p>
            <strong>Note:</strong> Origin coordinates are not set. Please set the origin
            to display position deviation data.
          </p>
        </div>
      )}

      {/* 
        Render the Origin modal if needed 
      */}
      {showOriginModal && (
        <OriginModal
          isOpen={showOriginModal}
          onClose={() => setShowOriginModal(false)}
          onSubmit={handleOriginSubmit}
          telemetryData={telemetryData}
          configData={configData}
        />
      )}

      {/* 
        Main content: Drone cards and plots 
      */}
      <div className="content-flex">
        {/* 
          Left column: Drone config cards 
        */}
        <div className="drone-cards">
          {sortedConfigData.map((drone) => (
            <DroneConfigCard
              key={drone.hw_id}
              drone={drone}
              gitStatus={gitStatusData[drone.hw_id] || null}
              gcsGitStatus={gcsGitStatus}
              configData={configData}
              availableHwIds={availableHwIds}
              editingDroneId={editingDroneId}
              setEditingDroneId={setEditingDroneId}
              saveChanges={saveChanges}
              removeDrone={removeDrone}
              networkInfo={networkInfo.find((info) => info.hw_id === drone.hw_id)}
              heartbeatData={heartbeats[drone.hw_id] || null}
              positionIdMapping={positionIdMapping}
            />
          ))}
        </div>

        {/* 
          Right column: Visual plots 
        */}
        <div className="initial-launch-plot">
          <InitialLaunchPlot
            drones={configData}
            onDroneClick={setEditingDroneId}
            deviationData={deviationData}
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
