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

/* 
  Utility: Finds a drone (other than the current one) in configData that has the given pos_id.
  Returns its entire drone object if found, otherwise null.
*/
function findDroneByPositionId(configData, targetPosId, excludeHwId) {
  return configData.find(
    (d) => d.pos_id === targetPosId && d.hw_id !== excludeHwId
  );
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
      {isNew && (
        <div className="new-drone-badge" aria-label="Newly Detected Drone">
          <FontAwesomeIcon icon={faPlusCircle} /> Newly Detected
        </div>
      )}

      <div className="heartbeat-info">
        <strong>Heartbeat:</strong> {getHeartbeatIcon()} {heartbeatStatus}
        {heartbeatAgeSec !== null && <span> ({heartbeatAgeSec}s ago)</span>}
      </div>

      <p><strong>Hardware ID:</strong> {drone.hw_id}</p>

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

      <p><strong>MavLink Port:</strong> {drone.mavlink_port}</p>
      <p><strong>Debug Port:</strong> {drone.debug_port}</p>
      <p><strong>GCS IP:</strong> {drone.gcs_ip}</p>
      <p><strong>Initial Launch Position:</strong> ({drone.x}, {drone.y})</p>

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
        <p><strong>Network Info:</strong> Not available</p>
      )}

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
  configData,
}) {
  const [showPosChangeDialog, setShowPosChangeDialog] = useState(false);
  const [pendingPosId, setPendingPosId] = useState(null);
  const [originalPosId, setOriginalPosId] = useState(droneData.pos_id);

  // Gather all existing position IDs from configData for a select dropdown
  const allPosIds = Array.from(new Set(configData.map((d) => d.pos_id)));

  // Handler for changes in the Position ID dropdown
  const handlePositionSelectChange = (e) => {
    const newPosId = e.target.value;
    // If same as original, do nothing
    if (newPosId === originalPosId) return;

    setPendingPosId(newPosId);
    setShowPosChangeDialog(true);
  };

  // Confirm the new position ID selection
  const confirmPositionChange = () => {
    if (!pendingPosId) {
      setShowPosChangeDialog(false);
      return;
    }

    // Find which drone (if any) currently uses this pendingPosId
    const matchedDrone = findDroneByPositionId(configData, pendingPosId, droneData.hw_id);

    // If matchedDrone is found, auto-fill x,y from that drone
    if (matchedDrone) {
      onFieldChange({ target: { name: 'pos_id', value: matchedDrone.pos_id } });
      onFieldChange({ target: { name: 'x', value: matchedDrone.x } });
      onFieldChange({ target: { name: 'y', value: matchedDrone.y } });
    } else {
      // Otherwise, just update pos_id but do not override x,y
      onFieldChange({ target: { name: 'pos_id', value: matchedDrone.pos_id } });
    }

    setOriginalPosId(pendingPosId);
    setPendingPosId(null);
    setShowPosChangeDialog(false);
  };

  // Cancel the new position ID selection
  const cancelPositionChange = () => {
    setShowPosChangeDialog(false);
    setPendingPosId(null);
  };

  // Generic input change handler
  const handleGenericChange = (e) => {
    const { name, value } = e.target;
    onFieldChange({ target: { name, value } });
  };

  return (
    <>
      {/* Confirmation Dialog for Position ID change */}
      {showPosChangeDialog && (
        <div className="confirmation-dialog-backdrop">
          <div className="confirmation-dialog" role="dialog" aria-modal="true">
            <p>
              You are about to change Position ID to <strong>{pendingPosId}</strong>.
              If another drone is using this ID, we will auto-fill this drone's x,y
              to match that drone's initial position. Continue?
            </p>
            <div className="dialog-buttons">
              <button className="confirm-button" onClick={confirmPositionChange}>
                Yes
              </button>
              <button className="cancel-button" onClick={cancelPositionChange}>
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
          onChange={handleGenericChange}
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
            onChange={handleGenericChange}
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
          onChange={handleGenericChange}
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
          onChange={handleGenericChange}
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
          onChange={handleGenericChange}
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
          onChange={handleGenericChange}
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
          onChange={handleGenericChange}
          placeholder="Enter Initial Y Coordinate"
          aria-label="Initial Y Coordinate"
        />
        {errors.y && <span className="error-message">{errors.y}</span>}
      </label>

      <label>
        Position ID:
        <div className="input-with-icon">
          {/* 
            Instead of a free-text input, we use a select 
            with all discovered position IDs plus the current one if not already in the list. 
          */}
          <select
            name="pos_id"
            value={droneData.pos_id}
            onChange={handlePositionSelectChange}
            aria-label="Position ID"
          >
            {/* 
              Combine existing pos_id if it's not in allPosIds 
              (in case it's new or unique). 
            */}
            {allPosIds.includes(droneData.pos_id) ? null : allPosIds.push(droneData.pos_id)}
            {Array.from(new Set(allPosIds)).map((pid) => (
              <option key={pid} value={pid}>
                {pid}
              </option>
            ))}
          </select>

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
  const [finalConfirmationOpen, setFinalConfirmationOpen] = useState(false);

  useEffect(() => {
    if (isEditing) {
      setDroneData({ ...drone });
      setErrors({});
    }
  }, [isEditing, drone]);

  // Heartbeat-based status
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

  // Mismatch checks
  const ipMismatch = heartbeatData ? heartbeatData.ip !== drone.ip : false;
  const posMismatch = heartbeatData ? heartbeatData.pos_id !== drone.pos_id : false;

  // Build hardware ID dropdown options
  const allHwIds = new Set(configData.map((d) => d.hw_id));
  const maxHwId = Math.max(0, ...Array.from(allHwIds, (id) => parseInt(id, 10))) + 1;
  const hwIdOptions = Array.from({ length: maxHwId }, (_, i) => (i + 1).toString()).filter(
    (id) => !allHwIds.has(id) || id === drone.hw_id
  );

  // Additional styling
  const cardExtraClass = drone.isNew
    ? ' new-drone'
    : (ipMismatch || posMismatch)
    ? ' mismatch-drone'
    : '';

  // Final check on save (duplicate pos_id? user confirmation)
  const handleFinalSave = () => {
    // Basic validation
    const validationErrors = {};
    if (!droneData.hw_id) validationErrors.hw_id = 'Hardware ID is required.';
    if (!droneData.ip) validationErrors.ip = 'IP Address is required.';
    if (!droneData.mavlink_port) validationErrors.mavlink_port = 'MavLink Port is required.';
    if (!droneData.debug_port) validationErrors.debug_port = 'Debug Port is required.';
    if (!droneData.gcs_ip) validationErrors.gcs_ip = 'GCS IP is required.';
    if (!droneData.x || isNaN(droneData.x)) validationErrors.x = 'Valid X coordinate is required.';
    if (!droneData.y || isNaN(droneData.y)) validationErrors.y = 'Valid Y coordinate is required.';
    if (!droneData.pos_id) validationErrors.pos_id = 'Position ID is required.';

    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors);
      return;
    }

    // Check if new pos_id duplicates another drone
    const duplicates = configData.filter(
      (d) => d.pos_id === droneData.pos_id && d.hw_id !== droneData.hw_id
    );
    if (duplicates.length > 0) {
      // Open final confirmation
      setFinalConfirmationOpen(true);
    } else {
      // If no duplicates, save directly
      saveChanges(drone.hw_id, droneData);
    }
  };

  // Confirm final override
  const confirmFinalOverride = () => {
    setFinalConfirmationOpen(false);
    saveChanges(drone.hw_id, droneData);
  };

  // Cancel final override
  const cancelFinalOverride = () => {
    setFinalConfirmationOpen(false);
    // Do nothing, user can revise pos_id or other fields
  };

  return (
    <div className={`drone-config-card${cardExtraClass}`}>
      {/* Final Confirmation for Duplicate pos_id */}
      {finalConfirmationOpen && (
        <div className="confirmation-dialog-backdrop">
          <div className="confirmation-dialog" role="dialog" aria-modal="true">
            <p>
              Position ID <strong>{droneData.pos_id}</strong> is already used by another drone.
              Are you sure you want to proceed with this assignment?
            </p>
            <div className="dialog-buttons">
              <button className="confirm-button" onClick={confirmFinalOverride}>
                Yes
              </button>
              <button className="cancel-button" onClick={cancelFinalOverride}>
                No
              </button>
            </div>
          </div>
        </div>
      )}

      {isEditing ? (
        <DroneEditForm
          droneData={droneData}
          errors={errors}
          ipMismatch={ipMismatch}
          posMismatch={posMismatch}
          heartbeatIP={heartbeatData?.ip}
          heartbeatPos={heartbeatData?.pos_id}
          onFieldChange={(e) => {
            // Generic field changes
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
          onSave={handleFinalSave}
          onCancel={() => {
            setEditingDroneId(null);
            setDroneData({ ...drone });
            setErrors({});
          }}
          hwIdOptions={hwIdOptions}
          configData={configData}
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

