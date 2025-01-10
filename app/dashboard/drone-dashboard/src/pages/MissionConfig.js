// src/pages/MissionConfig.js

import React, { useState, useEffect } from 'react';
import '../styles/MissionConfig.css';

// Components
import InitialLaunchPlot from '../components/InitialLaunchPlot';
import DroneConfigCard from '../components/DroneConfigCard';
import ControlButtons from '../components/ControlButtons';
import MissionLayout from '../components/MissionLayout'; // Renamed Component
import OriginModal from '../components/OriginModal';
import DronePositionMap from '../components/DronePositionMap';

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
  const {
    data: configDataFetched,
    error: configError,
    loading: configLoading,
  } = useFetch('/get-config-data');

  const {
    data: originDataFetched,
    error: originError,
    loading: originLoading,
  } = useFetch('/get-origin');

  const {
    data: deviationDataFetched,
    error: deviationError,
    loading: deviationLoading,
  } = useFetch('/get-position-deviations', originAvailable ? 5000 : null);

  const {
    data: telemetryDataFetched,
    error: telemetryError,
    loading: telemetryLoading,
  } = useFetch('/telemetry', 2000);

  const {
    data: gcsGitStatusFetched,
    error: gcsGitError,
    loading: gcsGitLoading,
  } = useFetch('/get-gcs-git-status', 30000);

  const {
    data: gitStatusDataFetched,
    error: gitStatusError,
    loading: gitStatusLoading,
  } = useFetch('/git-status', 20000);

  const {
    data: networkInfoFetched,
    error: networkInfoError,
    loading: networkInfoLoading,
  } = useFetch('/get-network-info', 10000);

  const {
    data: heartbeatsFetched,
    error: heartbeatsError,
    loading: heartbeatsLoading,
  } = useFetch('/get-heartbeats', 5000);

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
  // Effect: Update state when data is fetched
  // -----------------------------------------------------
  useEffect(() => {
    if (configDataFetched) {
      setConfigData(configDataFetched);
    }
  }, [configDataFetched]);

  useEffect(() => {
    if (originDataFetched && originDataFetched.lat !== undefined && originDataFetched.lon !== undefined) {
      // Ensure lat and lon are numbers
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
      toast.info(`${newDrones.length} new drone(s) detected and added.`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    toast.success(`Drone ${originalHwId} updated successfully.`);
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
    toast.success(`New drone ${newHwId} added.`);
  };

  // Remove drone
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

    // Send the origin to the backend
    const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
    axios.post(`${backendURL}/set-origin`, newOrigin)
      .then(() => {
        toast.success('Origin saved to server.');
      })
      .catch((error) => {
        console.error('Error saving origin to backend:', error);
        toast.error('Failed to save origin to server.');
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
        Control Buttons 
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
          telemetryData={telemetryDataFetched || {}}
          configData={configData}
          currentOrigin={origin} // Passed current origin
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
          {sortedConfigData.length > 0 ? (
            sortedConfigData.map((drone) => (
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
            ))
          ) : (
            <p>No drones connected. Please add a drone or connect one to proceed.</p>
          )}
        </div>

        {/* 
          Right column: Visual plots and additional mission details 
        */}
        <div className="initial-launch-plot">
          {/* 
            Mission Layout Section: Briefing, KML Output, Set Origin, Current Origin
          */}
          <MissionLayout
            configData={configData}
            origin={origin}
            openOriginModal={() => setShowOriginModal(true)}
          />

          <InitialLaunchPlot
            drones={configData}
            onDroneClick={setEditingDroneId}
            deviationData={deviationData}
          />
          <DronePositionMap
            originLat={origin.lat}
            originLon={origin.lon}
            drones={configData}
          />
        </div>
      </div>
    </div>
  );
};

export default MissionConfig;
