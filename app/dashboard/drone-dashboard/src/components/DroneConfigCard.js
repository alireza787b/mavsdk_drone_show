// src/components/DroneConfigCard.js

import React, { useState, useEffect, memo } from 'react';
import PropTypes from 'prop-types';
import DroneGitStatus from './DroneGitStatus';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faEdit,
  faTrash,
  faSave,
  faTimes,
  faCircle,
  faExclamationTriangle,
  faTimesCircle,
  faExclamationCircle,
  faPlusCircle,
  faSignal,
} from '@fortawesome/free-solid-svg-icons';
import '../styles/DroneConfigCard.css';

/**
 * Utility: Finds a drone (other than the current one) in configData that has the given pos_id.
 * Returns its x and y coordinates if found, otherwise null.
 */
function getCoordinatesByPositionId(configData, targetPosId, currentHwId) {
  const matchedDrone = configData.find(
    (d) => d.pos_id === targetPosId && d.hw_id !== currentHwId
  );
  if (matchedDrone) {
    return { x: matchedDrone.x, y: matchedDrone.y };
  }
  return null;
}

/**
 * Subcomponent: Displays the drone data in read-only format,
 * including heartbeat, mismatch warnings, and network info.
 */
const DroneReadOnlyView = memo(function DroneReadOnlyView({
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
  onRemove,
}) {
  // Determine heartbeat icon and color based on status
  const getHeartbeatIcon = () => {
    switch (heartbeatStatus) {
      case 'Online (Recent)':
        return (
          <FontAwesomeIcon
            icon={faCircle}
            className="status-icon online"
            title="Online (Recent)"
            aria-label="Online (Recent)"
          />
        );
      case 'Stale (>20s)':
        return (
          <FontAwesomeIcon
            icon={faExclamationTriangle}
            className="status-icon stale"
            title="Stale (>20s)"
            aria-label="Stale (>20s)"
          />
        );
      case 'Offline (>60s)':
        return (
          <FontAwesomeIcon
            icon={faTimesCircle}
            className="status-icon offline"
            title="Offline (>60s)"
            aria-label="Offline (>60s)"
          />
        );
      default:
        return (
          <FontAwesomeIcon
            icon={faCircle}
            className="status-icon no-heartbeat"
            title="No Heartbeat"
            aria-label="No Heartbeat"
          />
        );
    }
  };

  // Wi-Fi signal icon based on strength
  const getWifiIcon = (strength) => {
    if (strength >= 80) {
      return (
        <FontAwesomeIcon
          icon={faSignal}
          className="wifi-icon strong"
          title="Strong Signal"
          aria-label="Strong Signal"
        />
      );
    } else if (strength >= 50) {
      return (
        <FontAwesomeIcon
          icon={faSignal}
          className="wifi-icon medium"
          title="Medium Signal"
          aria-label="Medium Signal"
        />
      );
    } else if (strength > 0) {
      return (
        <FontAwesomeIcon
          icon={faSignal}
          className="wifi-icon weak"
          title="Weak Signal"
          aria-label="Weak Signal"
        />
      );
    } else {
      return (
        <FontAwesomeIcon
          icon={faSignal}
          className="wifi-icon none"
          title="No Signal"
          aria-label="No Signal"
        />
      );
    }
  };

  // Extract network data
  const wifiStrength = networkInfo?.wifi?.signal_strength_percent;
  const ethernetInterface = networkInfo?.ethernet?.interface;
  const ssid = networkInfo?.wifi?.ssid;

  return (
    <>
      {/* If it’s a new drone, show a prominent badge */}
      {isNew && (
        <div className="new-drone-badge" aria-label="Newly Detected Drone">
          <FontAwesomeIcon icon={faPlusCircle} /> Newly Detected
        </div>
      )}

      {/* Heartbeat Info */}
      <div className="heartbeat-info">
        <strong>Heartbeat:</strong> {getHeartbeatIcon()} {heartbeatStatus}
        {heartbeatAgeSec !== null && <span> ({heartbeatAgeSec}s ago)</span>}
      </div>

      <p>
        <strong>Hardware ID:</strong> {drone.hw_id}
      </p>

      {/* IP */}
      <p>
        <strong>IP:</strong>{' '}
        <span className={ipMismatch ? 'mismatch-text' : ''}>
          {drone.ip}
          {ipMismatch && heartbeatIP && (
            <FontAwesomeIcon
              icon={faExclamationCircle}
              className="warning-icon"
              title={`IP Mismatch: Heartbeat IP is ${heartbeatIP}`}
              aria-label={`IP Mismatch: Heartbeat IP is ${heartbeatIP}`}
            />
          )}
        </span>
      </p>

      {/* Position ID */}
      <p>
        <strong>Position ID:</strong>{' '}
        <span className={posMismatch ? 'mismatch-text' : ''}>
          {drone.pos_id}
          {posMismatch && heartbeatPos && (
            <FontAwesomeIcon
              icon={faExclamationCircle}
              className="warning-icon"
              title={`Position ID Mismatch: Heartbeat PosID is ${heartbeatPos}`}
              aria-label={`Position ID Mismatch: Heartbeat PosID is ${heartbeatPos}`}
            />
          )}
        </span>
      </p>

      <p>
        <strong>MavLink Port:</strong> {drone.mavlink_port}
      </p>
      <p>
        <strong>Debug Port:</strong> {drone.debug_port}
      </p>
      <p>
        <strong>GCS IP:</strong> {drone.gcs_ip}
      </p>
      <p>
        <strong>Initial Launch Position:</strong> ({drone.x}, {drone.y})
      </p>

      {/* Network Information Display */}
      {networkInfo ? (
        <div className="network-info" aria-label="Network Information">
          <p>
            <strong>Network Status:</strong> {ssid ? `SSID: ${ssid}` : 'N/A'}
          </p>
          <p>
            <strong>Signal Strength:</strong> {wifiStrength || 'N/A'} {getWifiIcon(wifiStrength)}
          </p>
          <p>
            <strong>Ethernet:</strong> {ethernetInterface || 'N/A'}
          </p>
        </div>
      ) : (
        <p>
          <strong>Network Info:</strong> Not available
        </p>
      )}

      {/* Drone Git Status */}
      <DroneGitStatus droneID={drone.hw_id} droneName={`Drone ${drone.hw_id}`} />

      <div className="card-buttons">
        <button
          className="edit-drone"
          onClick={onEdit}
          title="Edit drone configuration"
          aria-label="Edit drone configuration"
        >
          <FontAwesomeIcon icon={faEdit} /> Edit
        </button>
        <button
          className="remove-drone"
          onClick={onRemove}
          title="Remove this drone"
          aria-label="Remove this drone"
        >
          <FontAwesomeIcon icon={faTrash} /> Remove
        </button>
      </div>
    </>
  );
});

/**
 * Subcomponent: Renders editable form fields, including mismatch acceptance buttons.
 */
const DroneEditForm = memo(function DroneEditForm({
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
  hwIdOptions,
  configData, // We'll need configData to fetch x, y from other drones
}) {
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [pendingPosId, setPendingPosId] = useState(null);
  const [originalPosId, setOriginalPosId] = useState(droneData.pos_id);

  const handlePositionChange = (newPosId) => {
    // If the new pos_id is the same as the original, do nothing
    if (newPosId === originalPosId) return;

    setPendingPosId(newPosId);
    setShowConfirmation(true);
  };

  const handleFieldLocalChange = (e) => {
    const { name, value } = e.target;
    if (name === 'pos_id') {
      // User changed Position ID
      handlePositionChange(value);
    } else {
      onFieldChange(e); // For other fields, delegate to parent
    }
  };

  const handleConfirmPositionChange = () => {
    if (!pendingPosId) {
      setShowConfirmation(false);
      return;
    }

    // Attempt to find coordinates from a drone that has this pendingPosId
    const coords = getCoordinatesByPositionId(configData, pendingPosId, droneData.hw_id);
    // If coords exist, auto-fill x, y
    if (coords) {
      onFieldChange({ target: { name: 'pos_id', value: pendingPosId } });
      onFieldChange({ target: { name: 'x', value: coords.x } });
      onFieldChange({ target: { name: 'y', value: coords.y } });
    } else {
      // If not found, we just set the pos_id. x, y remain manual unless the user adjusts them
      onFieldChange({ target: { name: 'pos_id', value: pendingPosId } });
    }

    setOriginalPosId(pendingPosId);
    setShowConfirmation(false);
    setPendingPosId(null);
  };

  const handleCancelPositionChange = () => {
    setShowConfirmation(false);
    setPendingPosId(null);
  };

  return (
    <>
      {/* Confirmation Dialog */}
      {showConfirmation && (
        <div className="confirmation-dialog-backdrop">
          <div className="confirmation-dialog" role="dialog" aria-modal="true">
            <p>
              Changing the Position ID to <strong>{pendingPosId}</strong> will override the
              current drone's initial position if another drone has that ID. Do you want to
              proceed?
            </p>
            <div className="dialog-buttons">
              <button className="confirm-button" onClick={handleConfirmPositionChange}>
                Yes
              </button>
              <button className="cancel-button" onClick={handleCancelPositionChange}>
                No
              </button>
            </div>
          </div>
        </div>
      )}

      <label>
        Hardware ID:
        <select
          name="hw_id"
          value={droneData.hw_id}
          onChange={onFieldChange}
          title="Select Hardware ID"
          aria-label="Select Hardware ID"
        >
          {hwIdOptions.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
        {errors.hw_id && <span className="error-message">{errors.hw_id}</span>}
      </label>

      <label>
        IP Address:
        <div className="input-with-icon">
          <input
            type="text"
            name="ip"
            value={droneData.ip}
            onChange={onFieldChange}
            placeholder="Enter IP Address"
            style={ipMismatch ? { borderColor: 'red' } : {}}
            aria-label="IP Address"
          />
          {ipMismatch && (
            <FontAwesomeIcon
              icon={faExclamationCircle}
              className="warning-icon"
              title={`IP Mismatch: Heartbeat IP is ${heartbeatIP}`}
              aria-label={`IP Mismatch: Heartbeat IP is ${heartbeatIP}`}
            />
          )}
        </div>
        {errors.ip && <span className="error-message">{errors.ip}</span>}
        {ipMismatch && heartbeatIP && (
          <div className="mismatch-message">
            IP mismatch with heartbeat: {heartbeatIP}
            <button
              type="button"
              className="accept-button"
              onClick={onAcceptIp}
              title="Accept Heartbeat IP"
              aria-label="Accept Heartbeat IP"
            >
              <FontAwesomeIcon icon={faCircle} /> Accept
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
          aria-label="MavLink Port"
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
          aria-label="Debug Port"
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
          aria-label="GCS IP Address"
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
          aria-label="Initial X Coordinate"
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
          aria-label="Initial Y Coordinate"
        />
        {errors.y && <span className="error-message">{errors.y}</span>}
      </label>

      <label>
        Position ID:
        <div className="input-with-icon">
          <input
            type="text"
            name="pos_id"
            value={droneData.pos_id}
            onChange={handleFieldLocalChange}
            placeholder="Enter Position ID"
            style={posMismatch ? { borderColor: 'red' } : {}}
            aria-label="Position ID"
          />
          {posMismatch && (
            <FontAwesomeIcon
              icon={faExclamationCircle}
              className="warning-icon"
              title={`Position ID Mismatch: Heartbeat PosID is ${heartbeatPos}`}
              aria-label={`Position ID Mismatch: Heartbeat PosID is ${heartbeatPos}`}
            />
          )}
        </div>
        {errors.pos_id && <span className="error-message">{errors.pos_id}</span>}
        {posMismatch && heartbeatPos && (
          <div className="mismatch-message">
            Position ID mismatch with heartbeat: {heartbeatPos}
            <button
              type="button"
              className="accept-button"
              onClick={onAcceptPos}
              title="Accept Heartbeat PosID"
              aria-label="Accept Heartbeat PosID"
            >
              <FontAwesomeIcon icon={faCircle} /> Accept
            </button>
          </div>
        )}
      </label>

      <div className="card-buttons">
        <button
          className="save-drone"
          onClick={onSave}
          title="Save changes"
          aria-label="Save changes"
        >
          <FontAwesomeIcon icon={faSave} /> Save
        </button>
        <button
          className="cancel-edit"
          onClick={onCancel}
          title="Cancel editing"
          aria-label="Cancel editing"
        >
          <FontAwesomeIcon icon={faTimes} /> Cancel
        </button>
      </div>
    </>
  );
});

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
  heartbeatData,
}) {
  const isEditing = editingDroneId === drone.hw_id;

  // Local states
  const [droneData, setDroneData] = useState({ ...drone });
  const [errors, setErrors] = useState({});

  // Reset droneData when entering edit mode or when drone prop changes
  useEffect(() => {
    if (isEditing) {
      setDroneData({ ...drone });
      setErrors({});
    }
  }, [isEditing, drone]);

  // Calculate heartbeat age and status
  const now = Date.now();
  const heartbeatAgeSec = heartbeatData ? Math.floor((now - heartbeatData.timestamp) / 1000) : null;

  let heartbeatStatus = 'No heartbeat';
  if (heartbeatAgeSec !== null) {
    if (heartbeatAgeSec < 20) {
      heartbeatStatus = 'Online (Recent)';
    } else if (heartbeatAgeSec < 60) {
      heartbeatStatus = 'Stale (>20s)';
    } else {
      heartbeatStatus = 'Offline (>60s)';
    }
  }

  // Determine mismatches
  const ipMismatch = heartbeatData ? heartbeatData.ip !== drone.ip : false;
  const posMismatch = heartbeatData ? heartbeatData.pos_id !== drone.pos_id : false;

  // Compute hardware ID options
  const allHwIds = new Set(configData.map((d) => d.hw_id));
  const maxHwId = Math.max(0, ...Array.from(allHwIds, (id) => parseInt(id, 10))) + 1;
  const hwIdOptions = Array.from({ length: maxHwId }, (_, i) => (i + 1).toString()).filter(
    (id) => !allHwIds.has(id) || id === drone.hw_id
  );

  // Decide card styling based on mismatch or new drone
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
          onFieldChange={(e) => {
            const { name, value } = e.target;
            setDroneData({ ...droneData, [name]: value });
          }}
          onAcceptIp={() => {
            if (heartbeatData?.ip) {
              setDroneData({ ...droneData, ip: heartbeatData.ip });
            }
          }}
          onAcceptPos={() => {
            if (heartbeatData?.pos_id) {
              setDroneData({ ...droneData, pos_id: heartbeatData.pos_id });
            }
          }}
          onSave={() => {
            // Validate inputs before calling saveChanges
            const validationErrors = {};
            if (!droneData.hw_id) validationErrors.hw_id = 'Hardware ID is required.';
            if (!droneData.ip) validationErrors.ip = 'IP Address is required.';
            if (!droneData.mavlink_port) validationErrors.mavlink_port = 'MavLink Port is required.';
            if (!droneData.debug_port) validationErrors.debug_port = 'Debug Port is required.';
            if (!droneData.gcs_ip) validationErrors.gcs_ip = 'GCS IP is required.';
            if (!droneData.x || isNaN(droneData.x)) validationErrors.x = 'Valid X coordinate is required.';
            if (!droneData.y || isNaN(droneData.y)) validationErrors.y = 'Valid Y coordinate is required.';
            if (!droneData.pos_id) validationErrors.pos_id = 'Position ID is required.';

            setErrors(validationErrors);
            if (Object.keys(validationErrors).length === 0) {
              // All validations pass; save to parent
              saveChanges(drone.hw_id, droneData);
            }
          }}
          onCancel={() => {
            setEditingDroneId(null);
            setDroneData({ ...drone });
            setErrors({});
          }}
          hwIdOptions={hwIdOptions}
          configData={configData} // We'll pass configData here for getCoordinatesByPositionId
        />
      ) : (
        <DroneReadOnlyView
          drone={drone}
          isNew={drone.isNew}
          ipMismatch={ipMismatch}
          posMismatch={posMismatch}
          heartbeatStatus={heartbeatStatus}
          heartbeatAgeSec={heartbeatAgeSec}
          heartbeatIP={heartbeatData?.ip}
          heartbeatPos={heartbeatData?.pos_id}
          networkInfo={networkInfo}
          onEdit={() => setEditingDroneId(drone.hw_id)}
          onRemove={() => removeDrone(drone.hw_id)}
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
  heartbeatData: PropTypes.object,
};
