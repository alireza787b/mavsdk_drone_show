// src/pages/MissionConfig.js

import React, { useState, useEffect } from 'react';
import '../styles/MissionConfig.css';

// Components
import PositionTabs from '../components/PositionTabs';
import DroneConfigCard from '../components/DroneConfigCard';
import ControlButtons from '../components/ControlButtons';
import MissionLayout from '../components/MissionLayout';
import OriginModal from '../components/OriginModal';
import DronePositionMap from '../components/DronePositionMap';
import axios from 'axios';

// Hooks
import useFetch from '../hooks/useFetch';

// Utilities
import {
  handleSaveChangesToServer,
  handleRevertChanges,
  handleFileChange,
  exportConfig,
} from '../utilities/missionConfigUtilities';
import { toast } from 'react-toastify';
import { getBackendURL } from '../utilities/utilities';

const MissionConfig = () => {
  // -----------------------------------------------------
  // Heading slider: single source of truth
  // -----------------------------------------------------
  const [forwardHeading, setForwardHeading] = useState(0);

  // -----------------------------------------------------
  // State variables
  // -----------------------------------------------------
  const [configData, setConfigData] = useState([]);
  const [editingDroneId, setEditingDroneId] = useState(null);

  // Origin
  const [origin, setOrigin] = useState({ lat: null, lon: null });
  const [originAvailable, setOriginAvailable] = useState(false);
  const [showOriginModal, setShowOriginModal] = useState(false);

  // Deviations
  const [deviationData, setDeviationData] = useState({});

  // Git & Network
  const [networkInfo, setNetworkInfo] = useState([]);
  const [gitStatusData, setGitStatusData] = useState({});
  const [gcsGitStatus, setGcsGitStatus] = useState(null);

  // Heartbeat
  const [heartbeats, setHeartbeats] = useState({});

  // UI & Loading
  const [loading, setLoading] = useState(false);

  // -----------------------------------------------------
  // Data Fetching using custom hooks
  // -----------------------------------------------------
  const { data: configDataFetched } = useFetch('/get-config-data');
  const { data: originDataFetched } = useFetch('/get-origin');
  const { data: deviationDataFetched } = useFetch('/get-position-deviations', originAvailable ? 5000 : null);
  const { data: telemetryDataFetched } = useFetch('/telemetry', 2000);
  const { data: gcsGitStatusFetched } = useFetch('/get-gcs-git-status', 30000);
  const { data: gitStatusDataFetched } = useFetch('/git-status', 20000);
  const { data: networkInfoFetched } = useFetch('/get-network-info', 10000);
  const { data: heartbeatsFetched } = useFetch('/get-heartbeats', 5000);

  // -----------------------------------------------------
  // Derived Data & Helpers
  // -----------------------------------------------------
  const positionIdMapping = configData.reduce((acc, drone) => {
    if (drone.pos_id) {
      acc[drone.pos_id] = { x: drone.x, y: drone.y };
    }
    return acc;
  }, {});

  const allHwIds = new Set(configData.map((drone) => drone.hw_id));
  const maxHwId = Math.max(0, ...Array.from(allHwIds, (id) => parseInt(id, 10))) + 1;
  const availableHwIds = Array.from(
    { length: maxHwId },
    (_, i) => (i + 1).toString()
  ).filter((id) => !allHwIds.has(id));

  // -----------------------------------------------------
  // Effects: Update local state when data is fetched
  // -----------------------------------------------------
  useEffect(() => {
    if (configDataFetched) {
      setConfigData(configDataFetched);
    }
  }, [configDataFetched]);

  useEffect(() => {
    if (
      originDataFetched &&
      originDataFetched.lat !== undefined &&
      originDataFetched.lon !== undefined
    ) {
      setOrigin({
        lat: Number(originDataFetched.lat),
        lon: Number(originDataFetched.lon),
      });
      setOriginAvailable(true);
    } else {
      setOrigin({ lat: null, lon: null });
      setOriginAvailable(false);
    }
  }, [originDataFetched]);

  useEffect(() => {
    if (deviationDataFetched) {
      setDeviationData(deviationDataFetched);
    }
  }, [deviationDataFetched]);

  useEffect(() => {
    if (gcsGitStatusFetched) {
      setGcsGitStatus(gcsGitStatusFetched);
    }
  }, [gcsGitStatusFetched]);

  useEffect(() => {
    if (gitStatusDataFetched) {
      setGitStatusData(gitStatusDataFetched);
    }
  }, [gitStatusDataFetched]);

  useEffect(() => {
    if (networkInfoFetched) {
      setNetworkInfo(networkInfoFetched);
    }
  }, [networkInfoFetched]);

  useEffect(() => {
    if (heartbeatsFetched) {
      setHeartbeats(heartbeatsFetched);
    }
  }, [heartbeatsFetched]);

  // -----------------------------------------------------
  // Detect & add "new" drones by heartbeat
  // -----------------------------------------------------
  useEffect(() => {
    const heartbeatHwIds = Object.keys(heartbeats);

    const newDrones = [];
    for (const hbHwId of heartbeatHwIds) {
      if (!configData.some((d) => d.hw_id === hbHwId)) {
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
      toast.info(`${newDrones.length} new drone(s) detected and added.`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [heartbeats, configData]);

  // -----------------------------------------------------
  // CRUD operations
  // -----------------------------------------------------
  const saveChanges = (originalHwId, updatedData) => {
    if (
      configData.some((d) => d.hw_id === updatedData.hw_id && d.hw_id !== originalHwId)
    ) {
      alert('The selected Hardware ID is already in use. Please choose another one.');
      return;
    }

    setConfigData((prevConfig) =>
      prevConfig.map((drone) =>
        drone.hw_id === originalHwId ? { ...updatedData, isNew: false } : drone
      )
    );
    setEditingDroneId(null);
    toast.success(`Drone ${originalHwId} updated successfully.`);
  };

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
      serial_port: '/dev/ttyS0',  // Default for Raspberry Pi 4
      baudrate: '57600',           // Standard baudrate
      isNew: true,
    };

    setConfigData((prevConfig) => [...prevConfig, newDrone]);
    toast.success(`New drone ${newHwId} added.`);
  };

  const removeDrone = (hw_id) => {
    if (window.confirm(`Are you sure you want to remove Drone ${hw_id}?`)) {
      setConfigData((prevConfig) => prevConfig.filter((drone) => drone.hw_id !== hw_id));
      toast.success(`Drone ${hw_id} removed.`);
    }
  };

  // -----------------------------------------------------
  // Origin Modal submission
  // -----------------------------------------------------
  const handleOriginSubmit = (newOrigin) => {
    setOrigin(newOrigin);
    setShowOriginModal(false);
    setOriginAvailable(true);
    toast.success('Origin set successfully.');

    const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
    axios
      .post(`${backendURL}/set-origin`, newOrigin)
      .then(() => {
        toast.success('Origin saved to server.');
      })
      .catch((error) => {
        console.error('Error saving origin to backend:', error);
        toast.error('Failed to save origin to server.');
      });
  };

  // -----------------------------------------------------
  // Manual refresh for position deviations
  // -----------------------------------------------------
  const handleManualRefresh = () => {
    if (!originAvailable) {
      toast.warning('Origin must be set before fetching position deviations.');
      return;
    }

    const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
    axios
      .get(`${backendURL}/get-position-deviations`)
      .then((response) => {
        setDeviationData(response.data);
      })
      .catch((error) => {
        console.error('Error fetching position deviations:', error);
        toast.error('Failed to refresh position data.');
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
    toast.info('All unsaved changes have been reverted.');
  };

  const handleSaveChangesToServerWrapper = () => {
    handleSaveChangesToServer(configData, setConfigData, setLoading);
    toast.info('Saving changes to server...');
  };

  const handleExportConfigWrapper = () => {
    exportConfig(configData);
    toast.success('Configuration exported successfully.');
  };

  // Sort config data
  const sortedConfigData = [...configData].sort(
    (a, b) => parseInt(a.hw_id, 10) - parseInt(b.hw_id, 10)
  );

  // -----------------------------------------------------
  // Render
  // -----------------------------------------------------
  return (
    <div className="mission-config-container">
      <h2>Mission Configuration</h2>

      {/* Top Control Buttons */}
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

      {!originAvailable && (
        <div className="origin-warning">
          <p>
            <strong>Note:</strong> Origin coordinates are not set. Please set the origin
            to display position deviation data.
          </p>
        </div>
      )}

      {/* Origin Modal */}
      {showOriginModal && (
        <OriginModal
          isOpen={showOriginModal}
          onClose={() => setShowOriginModal(false)}
          onSubmit={handleOriginSubmit}
          telemetryData={telemetryDataFetched || {}}
          configData={configData}
          currentOrigin={origin}
        />
      )}

      <MissionLayout
        configData={configData}
        origin={origin}
        openOriginModal={() => setShowOriginModal(true)}
      />

      {/* Drone Stats Summary */}
      {configData.length > 0 && (
        <div className="drone-stats-summary">
          <div className="stat-item">
            <span className="stat-number">{configData.length}</span>
            <span className="stat-label">Total Drones</span>
          </div>
          <div className="stat-item">
            <span className="stat-number">
              {Object.keys(heartbeats).filter(id => {
                const hb = heartbeats[id];
                const age = hb?.timestamp ? Math.floor((Date.now() - hb.timestamp) / 1000) : null;
                return age !== null && age < 20;
              }).length}
            </span>
            <span className="stat-label">Online</span>
          </div>
          <div className="stat-item">
            <span className="stat-number">
              {configData.filter(drone => drone.isNew).length}
            </span>
            <span className="stat-label">New</span>
          </div>
          <div className="stat-item">
            <span className="stat-number">
              {originAvailable ? '✓' : '✗'}
            </span>
            <span className="stat-label">Origin Set</span>
          </div>
        </div>
      )}

      {/* Heading Controls */}
      <div className="heading-controls">
        <label htmlFor="headingSlider">
          Forward Heading: {forwardHeading}°
        </label>
        <input
          id="headingSlider"
          type="range"
          min={0}
          max={359}
          value={forwardHeading}
          onChange={(e) => setForwardHeading(parseInt(e.target.value, 10))}
        />
        <button
          onClick={() => {
            toast.info(`TODO: Save heading=${forwardHeading}° to server (placeholder).`);
          }}
        >
          Save Heading to Server
        </button>
      </div>

      {/* Main content: Drone Cards & Plots */}
      <div className="content-flex">
        <div className="drone-cards slide-in-left">
          {sortedConfigData.length > 0 ? (
            sortedConfigData.map((drone, index) => (
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
                style={{ animationDelay: `${index * 0.1}s` }}
              />
            ))
          ) : (
            <p>No drones connected. Please add a drone or connect one to proceed.</p>
          )}
        </div>

        <div className="initial-launch-plot slide-in-right">
          <PositionTabs
            drones={configData}
            deviationData={deviationData}
            origin={origin}
            forwardHeading={forwardHeading}
            onDroneClick={setEditingDroneId}
            onRefresh={handleManualRefresh}
          />

          <DronePositionMap
            originLat={origin.lat}
            originLon={origin.lon}
            drones={configData}
            forwardHeading={forwardHeading}
          />
        </div>
      </div>
    </div>
  );
};

export default MissionConfig;
