import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import DroneGitStatus from './DroneGitStatus';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faEdit, faTrash, faSave, faTimes } from '@fortawesome/free-solid-svg-icons';
import '../styles/DroneConfigCard.css';

/**
 * Subcomponent: Displays the drone data in read-only format,
 * plus heartbeat, mismatch warnings, and network info.
 */
function DroneReadOnlyView({
  drone,
  isNew,
  ipMismatch,
  posMismatch,
  heartbeatStatus,
  heartbeatAgeSec,
  heartbeatIP,
  heartbeatPos,
  networkInfo,
  onEdit,
  onRemove
}) {
  // Colorize text if mismatch
  const ipStyle = ipMismatch ? { color: 'red', fontWeight: 'bold' } : {};
  const posStyle = posMismatch ? { color: 'red', fontWeight: 'bold' } : {};

  // Wi-Fi color helper
  const getWifiStrengthColor = (strength) => {
    if (!strength) return 'inherit';
    if (strength >= 80) return 'green';
    if (strength >= 50) return 'orange';
    return 'red';
  };

  // Extract network data
  const wifiStrength = networkInfo?.wifi?.signal_strength_percent;
  const ethernetInterface = networkInfo?.ethernet?.interface;
  const ssid = networkInfo?.wifi?.ssid;

  return (
    <>
      {/* If it’s a new drone, show a small badge or banner */}
      {isNew && <div className="new-drone-badge">Newly Detected Drone</div>}

      {/* Heartbeat Info */}
      {heartbeatStatus !== 'No heartbeat' && (
        <p>
          <strong>Heartbeat:</strong> {heartbeatStatus} ({heartbeatAgeSec || 0}s ago)
        </p>
      )}
      {heartbeatStatus === 'No heartbeat' && (
        <p style={{ color: 'gray' }}>
          <strong>Heartbeat:</strong> No heartbeat received
        </p>
      )}

      {/* IP */}
      <p>
        <strong>IP:</strong>{' '}
        <span style={ipStyle}>{drone.ip}</span>
        {ipMismatch && heartbeatIP && (
          <em style={{ color: 'red', marginLeft: '6px' }}>
            (Mismatch from {heartbeatIP})
          </em>
        )}
      </p>

      {/* Position ID */}
      <p>
        <strong>Position ID:</strong>{' '}
        <span style={posStyle}>{drone.pos_id}</span>
        {posMismatch && heartbeatPos && (
          <em style={{ color: 'red', marginLeft: '6px' }}>
            (Mismatch from {heartbeatPos})
          </em>
        )}
      </p>

      <p><strong>MavLink Port:</strong> {drone.mavlink_port}</p>
      <p><strong>Debug Port:</strong> {drone.debug_port}</p>
      <p><strong>GCS IP:</strong> {drone.gcs_ip}</p>
      <p>
        <strong>Initial Launch Position:</strong> ({drone.x}, {drone.y})
      </p>

      {/* Network Information Display */}
      {networkInfo ? (
        <div className="network-info">
          <p><strong>Network Status</strong></p>
          <p><strong>SSID:</strong> {ssid || 'N/A'}</p>
          <p style={{ color: getWifiStrengthColor(wifiStrength) }}>
            <strong>Signal Strength:</strong> {wifiStrength || 'N/A'}%
          </p>
          <p><strong>Ethernet:</strong> {ethernetInterface || 'N/A'}</p>
        </div>
      ) : (
        <p>
          <strong>Network Info:</strong> Not available
        </p>
      )}

      {/* Drone Git Status */}
      <DroneGitStatus droneID={drone.hw_id} droneName={`Drone ${drone.hw_id}`} />

      <div className="card-buttons">
        <button className="edit-drone" onClick={onEdit} title="Edit drone configuration">
          <FontAwesomeIcon icon={faEdit} /> Edit
        </button>
        <button className="remove-drone" onClick={onRemove} title="Remove this drone">
          <FontAwesomeIcon icon={faTrash} /> Remove
        </button>
      </div>
    </>
  );
}

/**
 * Subcomponent: Renders editable form fields, plus mismatch acceptance buttons.
 */
function DroneEditForm({
  droneData,
  errors,
  ipMismatch,
  posMismatch,
  heartbeatIP,
  heartbeatPos,
  onFieldChange,
  onAcceptIp,
  onAcceptPos,
  onSave,
  onCancel,
  hwIdOptions
}) {
  return (
    <>
      <label>
        Hardware ID:
        <select
          name="hw_id"
          value={droneData.hw_id}
          onChange={onFieldChange}
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

      <label>
        IP Address:
        <input
          type="text"
          name="ip"
          value={droneData.ip}
          onChange={onFieldChange}
          placeholder="Enter IP Address"
          style={ipMismatch ? { borderColor: 'red' } : {}}
        />
        {errors.ip && <span className="error-message">{errors.ip}</span>}
        {ipMismatch && heartbeatIP && (
          <div className="mismatch-message">
            Mismatch with heartbeat: {heartbeatIP}
            <button type="button" className="accept-button" onClick={onAcceptIp}>
              Accept Heartbeat IP
            </button>
          </div>
        )}
      </label>

      <label>
        MavLink Port:
        <input
          type="text"
          name="mavlink_port"
          value={droneData.mavlink_port}
          onChange={onFieldChange}
          placeholder="Enter MavLink Port"
        />
        {errors.mavlink_port && <span className="error-message">{errors.mavlink_port}</span>}
      </label>

      <label>
        Debug Port:
        <input
          type="text"
          name="debug_port"
          value={droneData.debug_port}
          onChange={onFieldChange}
          placeholder="Enter Debug Port"
        />
        {errors.debug_port && <span className="error-message">{errors.debug_port}</span>}
      </label>

      <label>
        GCS IP:
        <input
          type="text"
          name="gcs_ip"
          value={droneData.gcs_ip}
          onChange={onFieldChange}
          placeholder="Enter GCS IP Address"
        />
        {errors.gcs_ip && <span className="error-message">{errors.gcs_ip}</span>}
      </label>

      <label>
        Initial X:
        <input
          type="text"
          name="x"
          value={droneData.x}
          onChange={onFieldChange}
          placeholder="Enter Initial X Coordinate"
        />
        {errors.x && <span className="error-message">{errors.x}</span>}
      </label>

      <label>
        Initial Y:
        <input
          type="text"
          name="y"
          value={droneData.y}
          onChange={onFieldChange}
          placeholder="Enter Initial Y Coordinate"
        />
        {errors.y && <span className="error-message">{errors.y}</span>}
      </label>

      <label>
        Position ID:
        <input
          type="text"
          name="pos_id"
          value={droneData.pos_id}
          onChange={onFieldChange}
          placeholder="Enter Position ID"
          style={posMismatch ? { borderColor: 'red' } : {}}
        />
        {errors.pos_id && <span className="error-message">{errors.pos_id}</span>}
        {posMismatch && heartbeatPos && (
          <div className="mismatch-message">
            Mismatch with heartbeat: {heartbeatPos}
            <button type="button" className="accept-button" onClick={onAcceptPos}>
              Accept Heartbeat PosID
            </button>
          </div>
        )}
      </label>

      <div className="card-buttons">
        <button className="save-drone" onClick={onSave} title="Save changes">
          <FontAwesomeIcon icon={faSave} /> Save
        </button>
        <button className="cancel-edit" onClick={onCancel} title="Cancel editing">
          <FontAwesomeIcon icon={faTimes} /> Cancel
        </button>
      </div>
    </>
  );
}

/**
 * Main DroneConfigCard: decides whether to show edit form or read-only view.
 */
export default function DroneConfigCard({
  drone,
  configData,
  availableHwIds,
  editingDroneId,
  setEditingDroneId,
  saveChanges,
  removeDrone,
  networkInfo,
  heartbeatData
}) {
  const isEditing = editingDroneId === drone.hw_id;

  // Local states
  const [droneData, setDroneData] = useState({ ...drone });
  const [errors, setErrors] = useState({});

  // Mismatch flags
  const [ipMismatch, setIpMismatch] = useState(false);
  const [posMismatch, setPosMismatch] = useState(false);

  // Heartbeat
  let heartbeatStatus = 'No heartbeat';
  let heartbeatAgeSec = null;
  let heartbeatIP = null;
  let heartbeatPos = null;
  let highlightCard = false;

  // Re-calc mismatch whenever 'drone' or 'heartbeatData' changes
  useEffect(() => {
    if (!heartbeatData) {
      setIpMismatch(false);
      setPosMismatch(false);
      heartbeatStatus = 'No heartbeat';
      return;
    }

    // Extract from heartbeat
    heartbeatIP = heartbeatData.ip;
    heartbeatPos = heartbeatData.pos_id;
    const now = Date.now();
    heartbeatAgeSec = Math.floor((now - heartbeatData.timestamp) / 1000);

    // Determine status
    if (heartbeatAgeSec < 20) {
      heartbeatStatus = 'Online (Recent)';
    } else if (heartbeatAgeSec < 60) {
      heartbeatStatus = 'Stale (>20s)';
    } else {
      heartbeatStatus = 'Offline (>60s)';
    }

    // Check IP mismatch
    if (heartbeatIP && heartbeatIP !== drone.ip) {
      setIpMismatch(true);
      highlightCard = true;
    } else {
      setIpMismatch(false);
    }

    // Check pos_id mismatch
    if (heartbeatPos && heartbeatPos.toString() !== drone.pos_id.toString()) {
      setPosMismatch(true);
      highlightCard = true;
    } else {
      setPosMismatch(false);
    }
  }, [drone, heartbeatData]);

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

  const handleFieldChange = (e) => {
    const { name, value } = e.target;
    setDroneData({ ...droneData, [name]: value });
  };

  const handleAcceptIp = () => {
    if (heartbeatData?.ip) {
      setDroneData({ ...droneData, ip: heartbeatData.ip });
    }
  };

  const handleAcceptPos = () => {
    if (heartbeatData?.pos_id) {
      setDroneData({ ...droneData, pos_id: heartbeatData.pos_id });
    }
  };

  const handleSave = () => {
    if (!validateInputs()) return;
    // pass up to parent
    saveChanges(drone.hw_id, droneData);
  };

  const handleCancel = () => {
    setEditingDroneId(null);
    setDroneData({ ...drone }); // revert changes
  };

  const handleRemove = () => removeDrone(drone.hw_id);

  // Compute hardware ID options
  const allHwIds = new Set(configData.map(d => d.hw_id));
  const maxHwId = Math.max(0, ...Array.from(allHwIds, id => parseInt(id))) + 1;
  const hwIdOptions = Array.from({ length: maxHwId }, (_, i) => (i + 1).toString()).filter(
    id => !allHwIds.has(id) || id === drone.hw_id
  );

  // Extra class
  const cardExtraClass = drone.isNew
    ? ' new-drone'
    : (ipMismatch || posMismatch)
    ? ' mismatch-drone'
    : '';

  return (
    <div className={`drone-config-card${cardExtraClass}`}>
      {isEditing ? (
        <DroneEditForm
          droneData={droneData}
          errors={errors}
          ipMismatch={ipMismatch}
          posMismatch={posMismatch}
          heartbeatIP={heartbeatData?.ip}
          heartbeatPos={heartbeatData?.pos_id}
          onFieldChange={handleFieldChange}
          onAcceptIp={handleAcceptIp}
          onAcceptPos={handleAcceptPos}
          onSave={handleSave}
          onCancel={handleCancel}
          hwIdOptions={hwIdOptions}
        />
      ) : (
        <DroneReadOnlyView
          drone={drone}
          isNew={drone.isNew}
          ipMismatch={ipMismatch}
          posMismatch={posMismatch}
          heartbeatStatus={heartbeatStatus}
          heartbeatAgeSec={heartbeatAgeSec}
          heartbeatIP={heartbeatIP}
          heartbeatPos={heartbeatPos}
          networkInfo={networkInfo}
          onEdit={() => setEditingDroneId(drone.hw_id)}
          onRemove={handleRemove}
        />
      )}
    </div>
  );
}

DroneConfigCard.propTypes = {
  drone: PropTypes.object.isRequired,
  configData: PropTypes.array.isRequired,
  availableHwIds: PropTypes.array.isRequired,
  editingDroneId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  setEditingDroneId: PropTypes.func.isRequired,
  saveChanges: PropTypes.func.isRequired,
  removeDrone: PropTypes.func.isRequired,
  networkInfo: PropTypes.object,
  heartbeatData: PropTypes.object
};
