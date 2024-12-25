// src/components/DroneConfigCard.js

import React, { useState } from 'react';
import PropTypes from 'prop-types';
import DroneGitStatus from './DroneGitStatus';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faEdit, faTrash, faSave, faTimes } from '@fortawesome/free-solid-svg-icons';
import '../styles/DroneConfigCard.css';

const DroneConfigCard = ({
  drone,
  configData,
  availableHwIds,
  editingDroneId,
  setEditingDroneId,
  saveChanges,
  removeDrone,
  networkInfo,
  heartbeatData // new prop
}) => {
  const isEditing = editingDroneId === drone.hw_id;
  const [droneData, setDroneData] = useState({ ...drone });
  const [errors, setErrors] = useState({});

  // Compute available Hardware IDs, including the current drone's hw_id
  const allHwIds = new Set(configData.map(d => d.hw_id));
  const maxHwId = Math.max(0, ...Array.from(allHwIds, id => parseInt(id))) + 1;
  const hwIdOptions = Array.from({ length: maxHwId }, (_, i) => (i + 1).toString()).filter(
    id => !allHwIds.has(id) || id === drone.hw_id
  );

  // Handlers
  const handleChange = (e) => {
    const { name, value } = e.target;
    setDroneData({ ...droneData, [name]: value });
  };

  const validateInputs = () => {
    const e = {};
    if (!droneData.hw_id) e.hw_id = 'Hardware ID is required.';
    if (!droneData.ip) e.ip = 'IP Address is required.';
    if (!droneData.mavlink_port) e.mavlink_port = 'MavLink Port is required.';
    if (!droneData.debug_port) e.debug_port = 'Debug Port is required.';
    if (!droneData.gcs_ip) e.gcs_ip = 'GCS IP is required.';
    if (!droneData.x || isNaN(droneData.x)) e.x = 'Valid X coordinate is required.';
    if (!droneData.y || isNaN(droneData.y)) e.y = 'Valid Y coordinate is required.';
    if (!droneData.pos_id) e.pos_id = 'Position ID is required.';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSave = () => {
    if (!validateInputs()) return;
    // Duplicate checks happen in parent "saveChanges"
    saveChanges(drone.hw_id, droneData);
  };

  // ------------------------------------------------------------------
  // HEARTBEAT MATCHING
  // ------------------------------------------------------------------
  const [ipMismatch, setIpMismatch] = useState(false);
  const [posMismatch, setPosMismatch] = useState(false);

  let heartbeatStatus = 'No heartbeat';
  let heartbeatIP = null;
  let heartbeatPos = null;
  let heartbeatAgeSec = null;
  let highlightCard = false;

  if (heartbeatData) {
    heartbeatIP = heartbeatData.ip;
    heartbeatPos = heartbeatData.pos_id;
    const now = Date.now();
    heartbeatAgeSec = Math.floor((now - heartbeatData.timestamp) / 1000);

    // If < 20s old, say "online," else "stale/offline"
    if (heartbeatAgeSec < 20) {
      heartbeatStatus = 'Online (Recent)';
    } else if (heartbeatAgeSec < 60) {
      heartbeatStatus = 'Stale (>20s)';
    } else {
      heartbeatStatus = 'Offline (>60s)';
    }

    // Mismatch checks
    if (heartbeatIP && heartbeatIP !== drone.ip) {
      setIpMismatch(true);
      highlightCard = true;
    } else {
      setIpMismatch(false);
    }

    if (heartbeatPos && heartbeatPos.toString() !== drone.pos_id.toString()) {
      setPosMismatch(true);
      highlightCard = true;
    } else {
      setPosMismatch(false);
    }
  }

  // Accept heartbeat IP or pos_id
  const acceptIpFromHeartbeat = () => {
    setDroneData({ ...droneData, ip: heartbeatIP });
  };
  const acceptPosFromHeartbeat = () => {
    setDroneData({ ...droneData, pos_id: heartbeatPos });
  };

  // Network info
  const droneNetworkInfo = networkInfo || {};
  const wifiStrength = droneNetworkInfo.wifi?.signal_strength_percent;

  const getWifiStrengthColor = (strength) => {
    if (!strength) return 'inherit';
    if (strength >= 80) return 'green';
    if (strength >= 50) return 'orange';
    return 'red';
  };

  // Card style if new or mismatch
  const cardExtraClass = drone.isNew ? ' new-drone' : highlightCard ? ' mismatch-drone' : '';

  return (
    <div className={`drone-config-card${cardExtraClass}`} data-hw-id={drone.hw_id}>
      {drone.isNew && (
        <div className="new-drone-badge">Newly Detected Drone</div>
      )}

      <h4>Drone {drone.hw_id}</h4>

      {isEditing ? (
        <>
          <label htmlFor={`hw_id-${drone.hw_id}`}>
            Hardware ID:
            <select
              id={`hw_id-${drone.hw_id}`}
              name="hw_id"
              value={droneData.hw_id}
              onChange={handleChange}
              title="Select Hardware ID"
            >
              {hwIdOptions.map(id => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
            {errors.hw_id && <span className="error-message">{errors.hw_id}</span>}
          </label>

          <label htmlFor={`ip-${drone.hw_id}`}>
            IP Address:
            <input
              type="text"
              id={`ip-${drone.hw_id}`}
              name="ip"
              value={droneData.ip}
              onChange={handleChange}
              placeholder="Enter IP Address"
              title="Enter the drone's IP address"
              style={ipMismatch ? { borderColor: 'red' } : {}}
            />
            {errors.ip && <span className="error-message">{errors.ip}</span>}
            {ipMismatch && heartbeatIP && (
              <div className="mismatch-message">
                Mismatch with heartbeat: {heartbeatIP}
                <button
                  type="button"
                  className="accept-button"
                  onClick={acceptIpFromHeartbeat}
                >
                  Accept Heartbeat IP
                </button>
              </div>
            )}
          </label>

          <label htmlFor={`mavlink_port-${drone.hw_id}`}>
            MavLink Port:
            <input
              type="text"
              id={`mavlink_port-${drone.hw_id}`}
              name="mavlink_port"
              value={droneData.mavlink_port}
              onChange={handleChange}
              placeholder="Enter MavLink Port"
              title="Enter the MavLink port number"
            />
            {errors.mavlink_port && <span className="error-message">{errors.mavlink_port}</span>}
          </label>

          <label htmlFor={`debug_port-${drone.hw_id}`}>
            Debug Port:
            <input
              type="text"
              id={`debug_port-${drone.hw_id}`}
              name="debug_port"
              value={droneData.debug_port}
              onChange={handleChange}
              placeholder="Enter Debug Port"
              title="Enter the debug port number"
            />
            {errors.debug_port && <span className="error-message">{errors.debug_port}</span>}
          </label>

          <label htmlFor={`gcs_ip-${drone.hw_id}`}>
            GCS IP:
            <input
              type="text"
              id={`gcs_ip-${drone.hw_id}`}
              name="gcs_ip"
              value={droneData.gcs_ip}
              onChange={handleChange}
              placeholder="Enter GCS IP Address"
              title="Enter the Ground Control Station IP address"
            />
            {errors.gcs_ip && <span className="error-message">{errors.gcs_ip}</span>}
          </label>

          <label htmlFor={`x-${drone.hw_id}`}>
            Initial X:
            <input
              type="text"
              id={`x-${drone.hw_id}`}
              name="x"
              value={droneData.x}
              onChange={handleChange}
              placeholder="Enter Initial X Coordinate"
              title="Enter the initial X coordinate (north)"
            />
            {errors.x && <span className="error-message">{errors.x}</span>}
          </label>

          <label htmlFor={`y-${drone.hw_id}`}>
            Initial Y:
            <input
              type="text"
              id={`y-${drone.hw_id}`}
              name="y"
              value={droneData.y}
              onChange={handleChange}
              placeholder="Enter Initial Y Coordinate"
              title="Enter the initial Y coordinate (east)"
            />
            {errors.y && <span className="error-message">{errors.y}</span>}
          </label>

          <label htmlFor={`pos_id-${drone.hw_id}`}>
            Position ID:
            <input
              type="text"
              id={`pos_id-${drone.hw_id}`}
              name="pos_id"
              value={droneData.pos_id}
              onChange={handleChange}
              placeholder="Enter Position ID"
              title="Enter the position ID"
              style={posMismatch ? { borderColor: 'red' } : {}}
            />
            {errors.pos_id && <span className="error-message">{errors.pos_id}</span>}
            {posMismatch && heartbeatPos && (
              <div className="mismatch-message">
                Mismatch with heartbeat: {heartbeatPos}
                <button
                  type="button"
                  className="accept-button"
                  onClick={acceptPosFromHeartbeat}
                >
                  Accept Heartbeat PosID
                </button>
              </div>
            )}
          </label>

          <div className="card-buttons">
            <button className="save-drone" onClick={handleSave} title="Save changes">
              <FontAwesomeIcon icon={faSave} /> Save
            </button>
            <button
              className="cancel-edit"
              onClick={() => setEditingDroneId(null)}
              title="Cancel editing"
            >
              <FontAwesomeIcon icon={faTimes} /> Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          {/* If not editing, show read-only info */}
          {heartbeatData && (
            <p>
              <strong>Heartbeat:</strong> {heartbeatStatus} ({heartbeatAgeSec || 0}s ago)
            </p>
          )}
          <p>
            <strong>IP:</strong>{' '}
            <span style={ipMismatch ? { color: 'red', fontWeight: 'bold' } : {}}>
              {drone.ip}
            </span>
            {ipMismatch && heartbeatIP && (
              <>
                {' '}
                <em style={{ color: 'red' }}>(Mismatch from {heartbeatIP})</em>
              </>
            )}
          </p>
          <p>
            <strong>Position ID:</strong>{' '}
            <span style={posMismatch ? { color: 'red', fontWeight: 'bold' } : {}}>
              {drone.pos_id}
            </span>
            {posMismatch && heartbeatPos && (
              <>
                {' '}
                <em style={{ color: 'red' }}>(Mismatch from {heartbeatPos})</em>
              </>
            )}
          </p>
          <p><strong>MavLink Port:</strong> {drone.mavlink_port}</p>
          <p><strong>Debug Port:</strong> {drone.debug_port}</p>
          <p><strong>GCS IP:</strong> {drone.gcs_ip}</p>
          <p><strong>Initial Launch Position:</strong> ({drone.x}, {drone.y})</p>

          {/* Network Information Display */}
          {droneNetworkInfo ? (
            <div className="network-info">
              <p><strong>Network Status</strong></p>
              <p><strong>SSID:</strong> {droneNetworkInfo.wifi?.ssid || 'N/A'}</p>
              <p style={{ color: getWifiStrengthColor(wifiStrength) }}>
                <strong>Signal Strength:</strong> {wifiStrength || 'N/A'}%
              </p>
              <p><strong>Ethernet:</strong> {droneNetworkInfo.ethernet?.interface || 'N/A'}</p>
            </div>
          ) : (
            <p><strong>Network Info:</strong> Not available</p>
          )}

          {/* Drone Git Status */}
          <DroneGitStatus droneID={drone.hw_id} droneName={`Drone ${drone.hw_id}`} />

          <div className="card-buttons">
            <button
              className="edit-drone"
              onClick={() => setEditingDroneId(drone.hw_id)}
              title="Edit drone configuration"
            >
              <FontAwesomeIcon icon={faEdit} /> Edit
            </button>
            <button
              className="remove-drone"
              onClick={() => removeDrone(drone.hw_id)}
              title="Remove this drone"
            >
              <FontAwesomeIcon icon={faTrash} /> Remove
            </button>
          </div>
        </>
      )}
    </div>
  );
};

DroneConfigCard.propTypes = {
  drone: PropTypes.object.isRequired,
  configData: PropTypes.array.isRequired,
  availableHwIds: PropTypes.array.isRequired,
  editingDroneId: PropTypes.string,
  setEditingDroneId: PropTypes.func.isRequired,
  saveChanges: PropTypes.func.isRequired,
  removeDrone: PropTypes.func.isRequired,
  networkInfo: PropTypes.object,
  heartbeatData: PropTypes.object
};

export default DroneConfigCard;
