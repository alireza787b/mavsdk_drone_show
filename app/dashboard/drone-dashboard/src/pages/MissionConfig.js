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
  const maxHwId = Math.max(0, ...Array.from(allHwIds, id => parseInt(id, 10))) + 1;
  const availableHwIds = Array.from({ length: maxHwId }, (_, i) => (i + 1).toString()).filter(
    (id) => !allHwIds.has(id)
  );

  // -----------------------------
  // Fetch config data on mount
  // -----------------------------
  useEffect(() => {
    const fetchData = async () => {
      const backendPort = process.env.REACT_APP_FLASK_PORT || '5000';
      const backendURL = getBackendURL(backendPort);
      try {
        const response = await axios.get(`${backendURL}/get-config-data`);
        // Normalize hw_id to trimmed strings
        const normalizedConfigData = response.data.map((drone) => ({
          ...drone,
          hw_id: String(drone.hw_id).trim(),
          pos_id: drone.pos_id ? String(drone.pos_id).trim() : drone.pos_id,
          gcs_ip: drone.gcs_ip ? drone.gcs_ip.trim() : '',
          ip: drone.ip ? drone.ip.trim() : '',
        }));
        setConfigData(normalizedConfigData);
        console.log('Config Data Fetched and Normalized:', normalizedConfigData); // Debugging
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
      const backendPort = process.env.REACT_APP_FLASK_PORT || '5000';
      const backendURL = getBackendURL(backendPort);
      try {
        const response = await axios.get(`${backendURL}/get-origin`);
        if (response.data.lat && response.data.lon) {
          setOriginLat(response.data.lat);
          setOriginLon(response.data.lon);
          setOriginAvailable(true);
        } else {
          setOriginAvailable(false);
        }
        console.log('Origin Data Fetched:', response.data); // Debugging
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
      const backendPort = process.env.REACT_APP_FLASK_PORT || '5000';
      const backendURL = getBackendURL(backendPort);
      try {
        const response = await axios.get(`${backendURL}/get-position-deviations`);
        setDeviationData(response.data);
        console.log('Deviation Data Fetched:', response.data); // Debugging
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
      const backendPort = process.env.REACT_APP_FLASK_PORT || '5000';
      const backendURL = getBackendURL(backendPort);
      try {
        const response = await axios.get(`${backendURL}/telemetry`);
        setTelemetryData(response.data);
        console.log('Telemetry Data Fetched:', response.data); // Debugging
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
        // Normalize gitStatusData keys to trimmed strings
        const normalizedGitStatusData = {};
        for (const key in response.data) {
          if (response.data.hasOwnProperty(key)) {
            const trimmedKey = String(key).trim();
            normalizedGitStatusData[trimmedKey] = response.data[key];
          }
        }
        setGitStatusData(normalizedGitStatusData);
        console.log('Git Status Data Fetched and Normalized:', normalizedGitStatusData); // Debugging
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
      const backendPort = process.env.REACT_APP_FLASK_PORT || '5000';
      const backendURL = getBackendURL(backendPort);
      try {
        const response = await axios.get(`${backendURL}/get-network-info`);
        setNetworkInfo(response.data);
        console.log('Network Info Fetched:', response.data); // Debugging
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
      const backendPort = process.env.REACT_APP_FLASK_PORT || '5000';
      const backendURL = getBackendURL(backendPort);
      try {
        const response = await axios.get(`${backendURL}/get-heartbeats`);
        setHeartbeats(response.data || {});
        console.log('Heartbeats Data Fetched:', response.data); // Debugging
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
      const trimmedHbHwId = String(hbHwId).trim(); // Normalize hw_id
      if (!configData.some((d) => d.hw_id === trimmedHbHwId)) {
        // It's new
        const hb = heartbeats[hbHwId];
        newDrones.push({
          hw_id: trimmedHbHwId,
          pos_id: hb.pos_id ? String(hb.pos_id).trim() : trimmedHbHwId, // Normalize pos_id
          ip: hb.ip ? hb.ip.trim() : '',
          x: '0',
          y: '0',
          mavlink_port: (14550 + parseInt(trimmedHbHwId, 10)).toString(),
          debug_port: (13540 + parseInt(trimmedHbHwId, 10)).toString(),
          gcs_ip:
            configData.length > 0 ? configData[0].gcs_ip.trim() : '', // Normalize gcs_ip
          isNew: true,
        });
      }
    }

    if (newDrones.length > 0) {
      setConfigData((prev) => [...prev, ...newDrones]);
      console.log('New Drones Added from Heartbeats:', newDrones); // Debugging
    }
  }, [heartbeats, configData]);

  // -----------------------------
  // Save changes for a drone
  // -----------------------------
  const saveChanges = (originalHwId, updatedData) => {
    // Normalize hw_id in updatedData
    const normalizedUpdatedData = {
      ...updatedData,
      hw_id: String(updatedData.hw_id).trim(),
      pos_id: updatedData.pos_id ? String(updatedData.pos_id).trim() : updatedData.pos_id,
      gcs_ip: updatedData.gcs_ip ? updatedData.gcs_ip.trim() : '',
      ip: updatedData.ip ? updatedData.ip.trim() : '',
    };

    // Validation: Check for duplicate hardware ID
    if (
      configData.some((d) => d.hw_id === normalizedUpdatedData.hw_id && d.hw_id !== originalHwId)
    ) {
      alert('The selected Hardware ID is already in use. Please choose another one.');
      return;
    }

    // Validation: Check for duplicate position ID
    if (
      configData.some((d) => d.pos_id === normalizedUpdatedData.pos_id && d.hw_id !== originalHwId)
    ) {
      if (
        !window.confirm(
          `Position ID ${normalizedUpdatedData.pos_id} is already assigned to another drone. Do you want to proceed?`
        )
      ) {
        return;
      }
    }

    // Merge changes and unset isNew
    setConfigData((prevConfig) =>
      prevConfig.map((drone) =>
        drone.hw_id === originalHwId
          ? { ...normalizedUpdatedData, isNew: false }
          : drone
      )
    );
    setEditingDroneId(null);
    console.log(`Drone ${originalHwId} updated to:`, normalizedUpdatedData); // Debugging
  };

  // -----------------------------
  // Add new drone (manual button)
  // -----------------------------
  const addNewDrone = () => {
    const newHwIdRaw = availableHwIds[0]?.toString() || (maxHwId).toString();
    const newHwId = newHwIdRaw.trim(); // Ensure hw_id is a trimmed string
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
      mavlink_port: (14550 + parseInt(newHwId, 10)).toString(),
      debug_port: (13540 + parseInt(newHwId, 10)).toString(),
      gcs_ip: allSameGcsIp ? configData[0].gcs_ip.trim() : '',
      x: '0',
      y: '0',
      pos_id: newHwId,
      isNew: true,
    };

    setConfigData((prevConfig) => [...prevConfig, newDrone]);
    console.log('New Drone Added Manually:', newDrone); // Debugging
  };

  // -----------------------------
  // Remove drone
  // -----------------------------
  const removeDrone = (hw_id) => {
    if (window.confirm(`Are you sure you want to remove Drone ${hw_id}?`)) {
      setConfigData((prevConfig) => prevConfig.filter((drone) => drone.hw_id !== hw_id));
      console.log(`Drone ${hw_id} removed.`); // Debugging
    }
  };

  // -----------------------------
  // Origin modal submission
  // -----------------------------
  const handleOriginSubmit = (lat, lon) => {
    setOriginLat(lat);
    setOriginLon(lon);
    setShowOriginModal(false);
    const backendPort = process.env.REACT_APP_FLASK_PORT || '5000';
    const backendURL = getBackendURL(backendPort);
    axios
      .post(`${backendURL}/set-origin`, {
        lat: lat,
        lon: lon,
      })
      .then(() => {
        setOriginAvailable(true);
        console.log('Origin set successfully:', { lat, lon }); // Debugging
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
    console.log('Config Imported from File'); // Debugging
  };

  // -----------------------------
  // Revert config
  // -----------------------------
  const handleRevertChangesWrapper = () => {
    handleRevertChanges(setConfigData);
    console.log('Config Changes Reverted'); // Debugging
  };

  // -----------------------------
  // Save config to server
  // -----------------------------
  const handleSaveChangesToServerWrapper = () => {
    handleSaveChangesToServer(configData, setConfigData, setLoading);
    console.log('Config Changes Saved to Server'); // Debugging
  };

  // -----------------------------
  // Export config
  // -----------------------------
  const handleExportConfigWrapper = () => {
    exportConfig(configData);
    console.log('Config Exported'); // Debugging
  };

  // Sort config for display
  const sortedConfigData = [...configData].sort(
    (a, b) => parseInt(a.hw_id, 10) - parseInt(b.hw_id, 10)
  );

  // -----------------------------
  // Debugging: Verify Mappings
  // -----------------------------
  useEffect(() => {
    console.log('Verifying Drone to Git Status Mappings:');
    sortedConfigData.forEach((drone) => {
      const hwIdStr = String(drone.hw_id).trim();
      const gitStatus = gitStatusData[hwIdStr] || null;
      console.log(`Drone HW_ID: ${hwIdStr} | Git Status: ${gitStatus ? 'Available' : 'Not Available'}`);
    });
  }, [sortedConfigData, gitStatusData]);

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
          {sortedConfigData.map((drone) => {
            const hwIdStr = String(drone.hw_id).trim(); // Ensure hw_id is a trimmed string
            const gitStatus = gitStatusData[hwIdStr] || null;
            return (
              <DroneConfigCard
                key={hwIdStr}
                drone={drone}
                gitStatus={gitStatus}
                configData={configData}
                availableHwIds={availableHwIds}
                editingDroneId={editingDroneId}
                setEditingDroneId={setEditingDroneId}
                saveChanges={saveChanges}
                removeDrone={removeDrone}
                networkInfo={networkInfo.find((info) => String(info.hw_id).trim() === hwIdStr)}
                heartbeatData={heartbeats[hwIdStr] || null} // Pass the heartbeat data
                positionIdMapping={positionIdMapping} // Pass the mapping
              />
            );
          })}
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
