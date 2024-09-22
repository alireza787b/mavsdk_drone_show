// MissionConfig.js

import React, { useState, useEffect, useRef } from 'react';
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
  exportConfig,
  generateKML,
} from '../utilities/missionConfigUtilities';

const MissionConfig = () => {
  const [configData, setConfigData] = useState([]);
  const [editingDroneId, setEditingDroneId] = useState(null);
  const [originLat, setOriginLat] = useState('');
  const [originLon, setOriginLon] = useState('');

  // ... existing useEffect and functions

  const exportToKML = () => {
    if (!originLat || !originLon) {
      alert('Please enter the origin latitude and longitude before exporting to KML.');
      return;
    }

    if (isNaN(originLat) || isNaN(originLon)) {
      alert('Origin latitude and longitude must be valid numbers.');
      return;
    }

    const kmlData = generateKML(configData, originLat, originLon);
    const blob = new Blob([kmlData], { type: 'application/vnd.google-earth.kml+xml' });
    const url = URL.createObjectURL(blob);

    const link = document.createElement('a');
    link.href = url;
    link.download = 'drone_positions.kml';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="mission-config-container">
      <h2>Mission Configuration</h2>
      {/* Reference Point Inputs */}
      <div className="reference-point-inputs">
        <label>
          Origin Latitude:
          <input
            type="text"
            value={originLat}
            onChange={(e) => setOriginLat(e.target.value)}
            placeholder="Enter Origin Latitude"
          />
        </label>
        <label>
          Origin Longitude:
          <input
            type="text"
            value={originLon}
            onChange={(e) => setOriginLon(e.target.value)}
            placeholder="Enter Origin Longitude"
          />
        </label>
      </div>
      <p className="origin-info">
        The origin point is the reference location (latitude and longitude) from which the relative drone positions are calculated. Please enter accurate coordinates to ensure correct placement in Google Earth.
      </p>
      <ControlButtons
        addNewDrone={addNewDrone}
        handleSaveChangesToServer={() => handleSaveChangesToServer(configData, setConfigData)}
        handleRevertChanges={() => handleRevertChanges(setConfigData)}
        handleFileChange={(event) => handleFileChange(event, setConfigData)}
        exportConfig={() => exportConfig(configData)}
      />
      <button className="export-kml no-print" onClick={exportToKML}>
        Export to Google Earth (KML)
      </button>
      <button className="print-mission no-print" onClick={handlePrint}>
        Print Mission Briefing
      </button>
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
        </div>
      </div>
    </div>
  );
};

export default MissionConfig;
