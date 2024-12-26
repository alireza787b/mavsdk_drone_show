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
 * Helper Function:
 * Finds a drone (other than the current one) that already uses `targetPosId`.
 * Returns the matched drone object or null if none found.
 */
function findDroneByPositionId(configData, targetPosId, excludeHwId) {
  return configData.find(
    (d) => d.pos_id === targetPosId && d.hw_id !== excludeHwId
  );
}

/**
 * Subcomponent: Read-only view of a drone card
 */
const DroneReadOnlyView = memo(function DroneReadOnlyView({
  drone,
  gitStatus,
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
  // Determine heartbeat icon based on status
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

  // Determine Wi-Fi icon
  const getWifiIcon = (strength) => {
    if (strength >= 80)
      return (
        <FontAwesomeIcon
          icon={faSignal}
          className="wifi-icon strong"
          title="Strong Signal"
          aria-label="Strong Signal"
        />
      );
    if (strength >= 50)
      return (
        <FontAwesomeIcon
          icon={faSignal}
          className="wifi-icon medium"
          title="Medium Signal"
          aria-label="Medium Signal"
        />
      );
    if (strength > 0)
      return (
        <FontAwesomeIcon
          icon={faSignal}
          className="wifi-icon weak"
          title="Weak Signal"
          aria-label="Weak Signal"
        />
      );
    return (
      <FontAwesomeIcon
        icon={faSignal}
        className="wifi-icon none"
        title="No Signal"
        aria-label="No Signal"
      />
    );
  };

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

      <p>
        <strong>Hardware ID:</strong> {drone.hw_id}
      </p>

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

      {networkInfo ? (
        <div className="network-info" aria-label="Network Information">
          <p>
            <strong>Network Status:</strong> {ssid ? `SSID: ${ssid}` : 'N/A'}
          </p>
          <p>
            <strong>Signal Strength:</strong> {wifiStrength || 'N/A'}{' '}
            {getWifiIcon(wifiStrength)}
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

      <DroneGitStatus gitStatus={gitStatus} droneName={`Drone ${drone.hw_id}`} />

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
 * Subcomponent: Edit Form for Drone Configuration
 * Allows users to modify drone fields, including `pos_id`.
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
  setDroneData,
}) {
  const [showPosChangeDialog, setShowPosChangeDialog] = useState(false);
  const [pendingPosId, setPendingPosId] = useState(null);
  const [isCustomPosId, setIsCustomPosId] = useState(false);
  const [customPosId, setCustomPosId] = useState('');

  // For showing old vs. new in the dialog
  const [oldX, setOldX] = useState(droneData.x);
  const [oldY, setOldY] = useState(droneData.y);
  const [newX, setNewX] = useState(droneData.x);
  const [newY, setNewY] = useState(droneData.y);

  // Local copy of the original pos_id for revert
  const [originalPosId, setOriginalPosId] = useState(droneData.pos_id);

  // Position IDs from configData for the <select>
  const allPosIds = Array.from(new Set(configData.map((d) => d.pos_id)));

  // If current pos_id not in that array (e.g., brand new), include it
  if (!allPosIds.includes(droneData.pos_id)) {
    allPosIds.push(droneData.pos_id);
  }

  // Sort them numerically
  allPosIds.sort((a, b) => {
    const ai = parseInt(a, 10);
    const bi = parseInt(b, 10);
    return ai - bi;
  });

  /**
   * Handler: User changes the Position ID from the <select>
   */
  const handlePosSelectChange = (e) => {
    const chosenPos = e.target.value;

    // If the user re-selects the same pos_id, do nothing
    if (chosenPos === droneData.pos_id) return;

    // Show confirmation dialog comparing old vs. new pos_id
    setPendingPosId(chosenPos);

    // Identify if the chosen pos_id belongs to an existing drone
    const matchedDrone = findDroneByPositionId(configData, chosenPos, droneData.hw_id);

    setOldX(droneData.x);
    setOldY(droneData.y);

    if (matchedDrone) {
      setNewX(matchedDrone.x);
      setNewY(matchedDrone.y);
    } else {
      // If no matched drone, keep x and y unchanged
      setNewX(droneData.x);
      setNewY(droneData.y);
    }

    setShowPosChangeDialog(true);
  };

  /**
   * Handler: Cancel the pos_id change
   */
  const handleCancelPosChange = () => {
    setShowPosChangeDialog(false);
    setPendingPosId(null);
    // Revert the select box to the original pos_id
    onFieldChange({ target: { name: 'pos_id', value: originalPosId } });
  };

  /**
   * Handler: Confirm the pos_id change
   * Updates pos_id and x/y coordinates if matched
   */
  const handleConfirmPosChange = () => {
    if (!pendingPosId) {
      setShowPosChangeDialog(false);
      return;
    }

    // Update pos_id in the droneData state
    onFieldChange({ target: { name: 'pos_id', value: pendingPosId } });

    // Update x, y if matched with another drone
    const matchedDrone = findDroneByPositionId(configData, pendingPosId, droneData.hw_id);
    if (matchedDrone) {
      onFieldChange({ target: { name: 'x', value: matchedDrone.x } });
      onFieldChange({ target: { name: 'y', value: matchedDrone.y } });

      // Update droneData state
      setDroneData((prevData) => ({
        ...prevData,
        pos_id: pendingPosId,
        x: matchedDrone.x,
        y: matchedDrone.y,
      }));
    } else {
      // If no match, ensure only pos_id is updated
      setDroneData((prevData) => ({
        ...prevData,
        pos_id: pendingPosId,
      }));
    }

    setOriginalPosId(pendingPosId); // Finalize the change
    setShowPosChangeDialog(false);
    setPendingPosId(null);
  };

  /**
   * Handler: Generic onChange for input fields
   */
  const handleGenericChange = (e) => {
    onFieldChange(e);
  };

  return (
    <>
      {/* Confirmation Dialog for Position ID Change */}
      {showPosChangeDialog && (
        <div className="confirmation-dialog-backdrop" role="dialog" aria-modal="true">
          <div className="confirmation-dialog">
            <h4>Confirm Position ID Change</h4>
            <p>
              You are changing Position ID from <strong>{originalPosId}</strong> to{' '}
              <strong>{pendingPosId}</strong>.
            </p>
            <p>
              <em>Old (x,y):</em> ({oldX}, {oldY})<br />
              <em>New (x,y):</em> ({newX}, {newY})
            </p>
            <p style={{ marginTop: '1rem' }}>
              Are you sure you want to proceed?
            </p>
            <div className="dialog-buttons">
              <button className="confirm-button" onClick={handleConfirmPosChange}>
                Yes
              </button>
              <button className="cancel-button" onClick={handleCancelPosChange}>
                No
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Hardware ID Selection */}
      <label htmlFor="hw_id-select">
        Hardware ID:
      </label>
      <select
        id="hw_id-select"
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
      {errors.hw_id && (
        <span className="error-message" role="alert">
          {errors.hw_id}
        </span>
      )}

      {/* IP Address Input */}
      <label htmlFor="ip-input">
        IP Address:
      </label>
      <div className="input-with-icon">
        <input
          id="ip-input"
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
      {errors.ip && (
        <span className="error-message" role="alert">
          {errors.ip}
        </span>
      )}
      {ipMismatch && heartbeatIP && (
        <div className="mismatch-message">
          <span>IP mismatch with heartbeat: {heartbeatIP}</span>
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

      {/* MavLink Port Input */}
      <label htmlFor="mavlink_port-input">
        MavLink Port:
      </label>
      <input
        id="mavlink_port-input"
        type="text"
        name="mavlink_port"
        value={droneData.mavlink_port}
        onChange={handleGenericChange}
        placeholder="Enter MavLink Port"
        aria-label="MavLink Port"
      />
      {errors.mavlink_port && (
        <span className="error-message" role="alert">
          {errors.mavlink_port}
        </span>
      )}

      {/* Debug Port Input */}
      <label htmlFor="debug_port-input">
        Debug Port:
      </label>
      <input
        id="debug_port-input"
        type="text"
        name="debug_port"
        value={droneData.debug_port}
        onChange={handleGenericChange}
        placeholder="Enter Debug Port"
        aria-label="Debug Port"
      />
      {errors.debug_port && (
        <span className="error-message" role="alert">
          {errors.debug_port}
        </span>
      )}

      {/* GCS IP Address Input */}
      <label htmlFor="gcs_ip-input">
        GCS IP:
      </label>
      <input
        id="gcs_ip-input"
        type="text"
        name="gcs_ip"
        value={droneData.gcs_ip}
        onChange={handleGenericChange}
        placeholder="Enter GCS IP Address"
        aria-label="GCS IP Address"
      />
      {errors.gcs_ip && (
        <span className="error-message" role="alert">
          {errors.gcs_ip}
        </span>
      )}

      {/* Initial X Coordinate Input */}
      <label htmlFor="x-input">
        Initial X:
      </label>
      <input
        id="x-input"
        type="text"
        name="x"
        value={droneData.x}
        onChange={handleGenericChange}
        placeholder="Enter Initial X Coordinate"
        aria-label="Initial X Coordinate"
      />
      {errors.x && (
        <span className="error-message" role="alert">
          {errors.x}
        </span>
      )}

      {/* Initial Y Coordinate Input */}
      <label htmlFor="y-input">
        Initial Y:
      </label>
      <input
        id="y-input"
        type="text"
        name="y"
        value={droneData.y}
        onChange={handleGenericChange}
        placeholder="Enter Initial Y Coordinate"
        aria-label="Initial Y Coordinate"
      />
      {errors.y && (
        <span className="error-message" role="alert">
          {errors.y}
        </span>
      )}

      {/* Position ID Selection */}
      <label htmlFor="pos_id-select">
        Position ID:
      </label>
      <div className="input-with-icon">
        {isCustomPosId ? (
          // Input field for new Position ID
          <input
            id="custom-pos-id-input"
            type="text"
            name="custom_pos_id"
            value={customPosId}
            placeholder="Enter new Position ID"
            onChange={(e) => {
              const newPosId = e.target.value.trim();
              setCustomPosId(newPosId);

              if (newPosId) {
                // Update droneData for new Position ID with default coordinates
                setDroneData((prevData) => ({
                  ...prevData,
                  pos_id: newPosId,
                  x: '0',
                  y: '0',
                }));
              }
            }}
            aria-label="Custom Position ID"
          />
        ) : (
          // Dropdown for existing Position IDs
          <select
            id="pos_id-select"
            name="pos_id"
            value={droneData.pos_id}
            onChange={handlePosSelectChange}
            aria-label="Select Position ID"
          >
            {allPosIds.map((pid) => (
              <option key={pid} value={pid}>
                {pid}
              </option>
            ))}
          </select>
        )}

        {/* Mismatch warning icon */}
        {posMismatch && (
          <FontAwesomeIcon
            icon={faExclamationCircle}
            className="warning-icon"
            title={`Position ID Mismatch: Heartbeat PosID is ${heartbeatPos}`}
            aria-label={`Position ID Mismatch: Heartbeat PosID is ${heartbeatPos}`}
          />
        )}

        {/* Toggle button to switch between dropdown and input */}
        <div className="toggle-container">
          <label className="switch" htmlFor="toggle-pos-id">
            <input
              id="toggle-pos-id"
              type="checkbox"
              checked={isCustomPosId}
              onChange={() => {
                setIsCustomPosId((prev) => !prev);
                if (!isCustomPosId) {
                  setCustomPosId('');
                }
              }}
              aria-label="Toggle Custom Position ID"
            />
            <span className="slider round"></span>
          </label>
          <span className="toggle-label">
            {isCustomPosId ? 'Enter New Position ID' : 'Select Existing Position ID'}
          </span>
        </div>
      </div>

      {/* Error message for Position ID */}
      {errors.pos_id && (
        <span className="error-message" role="alert">
          {errors.pos_id}
        </span>
      )}

      {/* Mismatch message and Accept button for Position ID */}
      {posMismatch && heartbeatPos && (
        <div className="mismatch-message">
          <span>Position ID mismatch with heartbeat: {heartbeatPos}</span>
          <button
            type="button"
            className="accept-button"
            onClick={onAcceptPos}
            title="Accept Heartbeat Position ID"
            aria-label="Accept Heartbeat Position ID"
          >
            <FontAwesomeIcon icon={faCircle} /> Accept
          </button>
        </div>
      )}

      {/* Save and Cancel Buttons */}
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
 * Main DroneConfigCard Component
 * Displays either the read-only view or the edit form based on the editing state.
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

  const [droneData, setDroneData] = useState({ ...drone });
  const [errors, setErrors] = useState({});

  // Reset local form when entering edit mode
  useEffect(() => {
    if (isEditing) {
      setDroneData({ ...drone });
      setErrors({});
    }
  }, [isEditing, drone]);

  // Calculate heartbeat age in seconds
  const now = Date.now();
  const heartbeatAgeSec =
    heartbeatData && heartbeatData.timestamp
      ? Math.floor((now - new Date(heartbeatData.timestamp).getTime()) / 1000)
      : null;

  // Determine heartbeat status
  let heartbeatStatus = 'No heartbeat';
  if (heartbeatAgeSec !== null) {
    if (heartbeatAgeSec < 20) heartbeatStatus = 'Online (Recent)';
    else if (heartbeatAgeSec < 60) heartbeatStatus = 'Stale (>20s)';
    else heartbeatStatus = 'Offline (>60s)';
  }

  // Detect mismatches between heartbeat data and drone config
  const ipMismatch = heartbeatData
    ? heartbeatData.ip.trim() !== drone.ip.trim()
    : false;
  const posMismatch = heartbeatData
    ? heartbeatData.pos_id.trim() !== drone.pos_id.trim()
    : false;

  // Generate Hardware ID options, ensuring uniqueness
  const allHwIds = new Set(configData.map((d) => d.hw_id));
  const maxHwId = Math.max(0, ...Array.from(allHwIds, (id) => parseInt(id, 10))) + 1;
  const hwIdList = Array.from({ length: maxHwId }, (_, i) =>
    (i + 1).toString()
  ).filter((id) => !allHwIds.has(id) || id === drone.hw_id);

  // Determine additional CSS classes based on drone status
  const cardExtraClass = drone.isNew
    ? ' new-drone'
    : ipMismatch || posMismatch
    ? ' mismatch-drone'
    : '';

  /**
   * Handler: Validate and save changes
   */
  const handleLocalSave = () => {
    // Basic validation
    const validationErrors = {};
    if (!droneData.hw_id || droneData.hw_id.trim() === '') {
      validationErrors.hw_id = 'Hardware ID is required.';
    }
    if (!droneData.ip || droneData.ip.trim() === '') {
      validationErrors.ip = 'IP Address is required.';
    }
    if (!droneData.mavlink_port || droneData.mavlink_port.trim() === '') {
      validationErrors.mavlink_port = 'MavLink Port is required.';
    }
    if (!droneData.debug_port || droneData.debug_port.trim() === '') {
      validationErrors.debug_port = 'Debug Port is required.';
    }
    if (!droneData.gcs_ip || droneData.gcs_ip.trim() === '') {
      validationErrors.gcs_ip = 'GCS IP is required.';
    }
    if (
      !droneData.x ||
      isNaN(parseFloat(droneData.x)) ||
      parseFloat(droneData.x) < 0
    ) {
      validationErrors.x = 'Valid X coordinate is required.';
    }
    if (
      !droneData.y ||
      isNaN(parseFloat(droneData.y)) ||
      parseFloat(droneData.y) < 0
    ) {
      validationErrors.y = 'Valid Y coordinate is required.';
    }
    if (!droneData.pos_id || droneData.pos_id.trim() === '') {
      validationErrors.pos_id = 'Position ID is required.';
    }

    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors);
      return;
    }

    // Invoke the parent handler to save changes
    saveChanges(drone.hw_id, droneData);
  };

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
              setDroneData((prevData) => ({
                ...prevData,
                ip: heartbeatData.ip.trim(),
              }));
            }
          }}
          onAcceptPos={() => {
            if (heartbeatData?.pos_id) {
              setDroneData((prevData) => ({
                ...prevData,
                pos_id: heartbeatData.pos_id.trim(),
                // Optionally, update x and y if provided in heartbeat data
                x: heartbeatData.x ? heartbeatData.x : prevData.x,
                y: heartbeatData.y ? heartbeatData.y : prevData.y,
              }));
            }
          }}
          onSave={handleLocalSave}
          onCancel={() => {
            setEditingDroneId(null);
            setDroneData({ ...drone });
            setErrors({});
          }}
          hwIdOptions={hwIdList}
          configData={configData}
          setDroneData={setDroneData}
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
          gitStatus={drone.gitStatus} // Ensure correct mapping
          onEdit={() => setEditingDroneId(drone.hw_id)}
          onRemove={() => removeDrone(drone.hw_id)}
        />
      )}
    </div>
  );
}

DroneConfigCard.propTypes = {
  drone: PropTypes.shape({
    hw_id: PropTypes.string.isRequired,
    pos_id: PropTypes.string.isRequired,
    ip: PropTypes.string.isRequired,
    mavlink_port: PropTypes.string.isRequired,
    debug_port: PropTypes.string.isRequired,
    gcs_ip: PropTypes.string.isRequired,
    x: PropTypes.string.isRequired,
    y: PropTypes.string.isRequired,
    isNew: PropTypes.bool,
    gitStatus: PropTypes.object,
  }).isRequired,
  gitStatus: PropTypes.object,
  configData: PropTypes.arrayOf(
    PropTypes.shape({
      hw_id: PropTypes.string.isRequired,
      pos_id: PropTypes.string.isRequired,
      // ... other fields
    })
  ).isRequired,
  availableHwIds: PropTypes.arrayOf(PropTypes.string).isRequired,
  editingDroneId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  setEditingDroneId: PropTypes.func.isRequired,
  saveChanges: PropTypes.func.isRequired,
  removeDrone: PropTypes.func.isRequired,
  networkInfo: PropTypes.object,
  heartbeatData: PropTypes.shape({
    ip: PropTypes.string,
    pos_id: PropTypes.string,
    timestamp: PropTypes.string,
    x: PropTypes.number,
    y: PropTypes.number,
  }),
};
