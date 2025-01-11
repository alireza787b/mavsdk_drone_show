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
  faCheckCircle,
  faQuestionCircle,
} from '@fortawesome/free-solid-svg-icons';
import '../styles/DroneConfigCard.css';

/**
 * Finds a drone (other than the current one) that already uses `targetPosId`.
 * Returns the entire matched drone object, or null if none found.
 */
function findDroneByPositionId(configData, targetPosId, excludeHwId) {
  return configData.find(
    (d) => d.pos_id === targetPosId && d.hw_id !== excludeHwId
  );
}

/**
 * Subcomponent: Read-only view of a drone card.
 * Displays mismatch info, a green check icon if all good, etc.
 */
const DroneReadOnlyView = memo(function DroneReadOnlyView({
  drone,
  gitStatus,
  gcsGitStatus,
  isNew,
  ipMismatch,
  posMismatch,
  autoDetectMismatch,
  internalHbPosMismatch,
  heartbeatStatus,
  heartbeatAgeSec,
  heartbeatIP,
  heartbeatPos,
  heartbeatDetectedPos,
  networkInfo,
  onEdit,
  onRemove,
  onAcceptConfigFromAuto,
  onAcceptConfigFromHb,
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
        // "No Heartbeat" or uninitialized
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

  // Wi-Fi icon based on signal strength
  const getWifiIcon = (strength) => {
    if (strength >= 80) {
      return (
        <FontAwesomeIcon
          icon={faSignal}
          className="wifi-icon strong"
          title="Strong Wi-Fi Signal"
          aria-label="Strong Wi-Fi Signal"
        />
      );
    }
    if (strength >= 50) {
      return (
        <FontAwesomeIcon
          icon={faSignal}
          className="wifi-icon medium"
          title="Medium Wi-Fi Signal"
          aria-label="Medium Wi-Fi Signal"
        />
      );
    }
    if (strength > 0) {
      return (
        <FontAwesomeIcon
          icon={faSignal}
          className="wifi-icon weak"
          title="Weak Wi-Fi Signal"
          aria-label="Weak Wi-Fi Signal"
        />
      );
    }
    return (
      <FontAwesomeIcon
        icon={faSignal}
        className="wifi-icon none"
        title="No Wi-Fi Signal"
        aria-label="No Wi-Fi Signal"
      />
    );
  };

  // Safely get network stats
  const wifiStrength = networkInfo?.wifi?.signal_strength_percent;
  const ethernetInterface = networkInfo?.ethernet?.interface;
  const ssid = networkInfo?.wifi?.ssid;

  // Indicate if auto-detection is "unavailable" (i.e. '0')
  const isAutoDetectionUnavailable =
    heartbeatDetectedPos !== undefined && heartbeatDetectedPos === '0';

  // Check if there are *no mismatches at all*
  const isAllGood =
    !ipMismatch &&
    !posMismatch &&
    !autoDetectMismatch &&
    !internalHbPosMismatch &&
    !isNew &&
    !isAutoDetectionUnavailable;

  return (
    <>
      {/* If newly detected (from heartbeats) */}
      {isNew && (
        <div className="new-drone-badge" aria-label="Newly Detected Drone">
          <FontAwesomeIcon icon={faPlusCircle} /> Newly Detected
        </div>
      )}

      {/* Heartbeat Info */}
      <div className="heartbeat-info">
        <strong>Heartbeat:</strong> {getHeartbeatIcon()} {heartbeatStatus}
        {/* Show time since last heartbeat if available */}
        {heartbeatAgeSec !== null && <span> ({heartbeatAgeSec}s ago)</span>}

        {/* 
          If everything is perfect and there's a heartbeat,
          show a green check next to "All Good!"
        */}
        {heartbeatStatus !== 'No heartbeat' && isAllGood && (
          <span className="all-good-indicator" title="All assigned IDs match; no issues.">
            <FontAwesomeIcon icon={faCheckCircle} className="status-icon all-good" />
            All Good
          </span>
        )}
      </div>

      {/* Basic Drone Info */}
      <p>
        <strong>Hardware ID:</strong> {drone.hw_id}{' '}
        <FontAwesomeIcon
          icon={faQuestionCircle}
          className="info-icon"
          title="Hardware ID uniquely identifies the physical drone."
          aria-label="Hardware ID Info"
        />
      </p>

      {/* IP with mismatch check */}
      <p>
        <strong>IP:</strong>{' '}
        <span className={ipMismatch ? 'mismatch-text' : ''}>
          {drone.ip}
          {ipMismatch && heartbeatIP && (
            <FontAwesomeIcon
              icon={faExclamationCircle}
              className="warning-icon"
              title={`IP Mismatch: Actual IP from heartbeat is ${heartbeatIP}`}
              aria-label={`IP Mismatch: Heartbeat IP is ${heartbeatIP}`}
            />
          )}
        </span>
      </p>

      {/* Position ID (Config) with mismatch checks */}
      <p>
        <strong>Position ID:</strong>{' '}
        <span className={posMismatch || autoDetectMismatch ? 'mismatch-text' : ''}>
          {drone.pos_id}
          {/* Heartbeat assigned mismatch icon */}
          {posMismatch && heartbeatPos && (
            <FontAwesomeIcon
              icon={faExclamationCircle}
              className="warning-icon"
              title={`Pos ID mismatch: Heartbeat assigned pos_id is ${heartbeatPos}`}
              aria-label={`Pos ID mismatch: Heartbeat pos_id is ${heartbeatPos}`}
            />
          )}
          {/* Auto-detected mismatch icon */}
          {autoDetectMismatch && heartbeatDetectedPos && (
            <FontAwesomeIcon
              icon={faExclamationCircle}
              className="warning-icon"
              title={`Pos ID mismatch: Auto-detected pos_id is ${heartbeatDetectedPos}`}
              aria-label={`Pos ID mismatch: Auto-detected pos_id is ${heartbeatDetectedPos}`}
            />
          )}
        </span>
      </p>

      {/* Show the heartbeat's assigned pos_id and detected_pos_id explicitly if you want */}
      {heartbeatPos && (
        <p>
          <strong>Heartbeat’s Assigned Pos ID:</strong> {heartbeatPos}
        </p>
      )}

      {/* Mild warning if auto-detected is '0' */}
      {isAutoDetectionUnavailable && (
        <p style={{ color: '#f59e0b' }}>
          <strong>Auto-Detection:</strong> Not available or failed to detect.
        </p>
      )}

      {/* If auto-detected is a valid nonzero ID, display it */}
      {!isAutoDetectionUnavailable &&
        heartbeatDetectedPos !== undefined &&
        heartbeatDetectedPos !== '0' && (
          <p>
            <strong>Heartbeat’s Detected Pos ID:</strong> {heartbeatDetectedPos}
          </p>
        )}

      {/* If there's a mismatch within the heartbeat itself (pos_id vs. detected_pos_id) */}
      {internalHbPosMismatch && (
        <div className="mismatch-message">
          <FontAwesomeIcon
            icon={faExclamationCircle}
            className="warning-icon"
            title="Heartbeat assigned pos_id vs. detected_pos_id mismatch"
            aria-label="Heartbeat assigned pos_id vs. detected_pos_id mismatch"
          />
          <span>
            Heartbeat pos_id (<em>{heartbeatPos}</em>) differs from detected_pos_id (<em>{heartbeatDetectedPos}</em>).
          </span>
          {/* Let the user choose which to adopt for the config */}
          <button
            type="button"
            className="accept-button"
            onClick={() => {
              onAcceptConfigFromAuto?.(heartbeatDetectedPos);
            }}
          >
            Accept Detected
          </button>
          <button
            type="button"
            className="accept-button"
            style={{ backgroundColor: '#059669' }} // green
            onClick={() => {
              onAcceptConfigFromHb?.(heartbeatPos);
            }}
          >
            Accept Assigned
          </button>
        </div>
      )}

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

      {/* Network Info */}
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

      {/* Git Info */}
      <DroneGitStatus
        gitStatus={gitStatus}
        gcsGitStatus={gcsGitStatus}
        droneName={`Drone ${drone.hw_id}`}
      />

      {/* Edit / Remove Buttons */}
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
 * Edit Form: Let the user modify drone fields, including `pos_id`.
 * If the user picks a `pos_id` used by another drone, we'll show old/new (x,y) confirmation.
 */
const DroneEditForm = memo(function DroneEditForm({
  droneData,
  errors,
  ipMismatch,
  posMismatch,
  autoDetectMismatch,
  internalHbPosMismatch,
  heartbeatIP,
  heartbeatPos,
  heartbeatDetectedPos,
  onFieldChange,
  onAcceptIp,
  onAcceptPos,
  onAcceptPosAuto,
  onAcceptPosFromHbVsAuto,
  onSave,
  onCancel,
  hwIdOptions,
  configData,
  setDroneData,
}) {
  // State for the position ID confirmation dialog
  const [showPosChangeDialog, setShowPosChangeDialog] = useState(false);
  const [pendingPosId, setPendingPosId] = useState(null);

  // Toggle for the user to choose "Enter New PosID" or "Select from existing"
  const [isCustomPosId, setIsCustomPosId] = useState(false);
  const [customPosId, setCustomPosId] = useState('');

  // For showing old vs. new in the dialog
  const [oldX, setOldX] = useState(droneData.x);
  const [oldY, setOldY] = useState(droneData.y);
  const [newX, setNewX] = useState(droneData.x);
  const [newY, setNewY] = useState(droneData.y);

  // Keep a separate local copy of the original pos_id to revert if needed
  const [originalPosId, setOriginalPosId] = useState(droneData.pos_id);

  // Position IDs from configData for the dropdown
  const allPosIds = Array.from(new Set(configData.map((d) => d.pos_id)));
  // If current pos_id is not in that array (e.g. brand new), include it
  if (!allPosIds.includes(droneData.pos_id)) {
    allPosIds.push(droneData.pos_id);
  }
  // Sort them numerically for nicer UI
  allPosIds.sort((a, b) => parseInt(a, 10) - parseInt(b, 10));

  /** 
   * Called when user selects a different PosID from the dropdown.
   * We'll open a confirmation dialog if the user is effectively changing the ID.
   */
  const handlePosSelectChange = (e) => {
    const chosenPos = e.target.value;
    if (chosenPos === droneData.pos_id) return; // no change
    setPendingPosId(chosenPos);

    // Find if that pos_id belongs to an existing drone => we can auto-copy x,y
    const matchedDrone = findDroneByPositionId(configData, chosenPos, droneData.hw_id);

    // Save old x,y for the confirmation dialog
    setOldX(droneData.x);
    setOldY(droneData.y);

    if (matchedDrone) {
      setNewX(matchedDrone.x);
      setNewY(matchedDrone.y);
    } else {
      setNewX(droneData.x);
      setNewY(droneData.y);
    }

    setShowPosChangeDialog(true);
  };

  /** User canceled changing the pos_id => revert to the original. */
  const handleCancelPosChange = () => {
    setShowPosChangeDialog(false);
    setPendingPosId(null);
    onFieldChange({ target: { name: 'pos_id', value: originalPosId } });
  };

  /** User confirmed => update droneData.pos_id (and x,y if needed). */
  const handleConfirmPosChange = () => {
    if (!pendingPosId) {
      setShowPosChangeDialog(false);
      return;
    }
    // Update local state
    onFieldChange({ target: { name: 'pos_id', value: pendingPosId } });

    const matchedDrone = findDroneByPositionId(
      configData,
      pendingPosId,
      droneData.hw_id
    );
    if (matchedDrone) {
      onFieldChange({ target: { name: 'x', value: matchedDrone.x } });
      onFieldChange({ target: { name: 'y', value: matchedDrone.y } });

      setDroneData((prevData) => ({
        ...prevData,
        pos_id: pendingPosId,
        x: matchedDrone.x,
        y: matchedDrone.y,
      }));
    } else {
      setDroneData((prevData) => ({
        ...prevData,
        pos_id: pendingPosId,
      }));
    }

    setOriginalPosId(pendingPosId);
    setShowPosChangeDialog(false);
    setPendingPosId(null);
  };

  /** Generic onChange handler for fields other than pos_id */
  const handleGenericChange = (e) => {
    onFieldChange(e);
  };

  return (
    <>
      {/* 
        Confirmation Dialog for pos_id changes
        Shows old vs. new x,y 
      */}
      {showPosChangeDialog && (
        <div className="confirmation-dialog-backdrop">
          <div className="confirmation-dialog" role="dialog" aria-modal="true">
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

      {/* Hardware ID Field */}
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

      {/* IP + Mismatch */}
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

      {/* MavLink Port */}
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
        {errors.mavlink_port && (
          <span className="error-message">{errors.mavlink_port}</span>
        )}
      </label>

      {/* Debug Port */}
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
        {errors.debug_port && (
          <span className="error-message">{errors.debug_port}</span>
        )}
      </label>

      {/* GCS IP */}
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

      {/* X, Y */}
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

      {/* Position ID + Mismatch / Accept Blocks */}
      <label>
        Position ID:
        <div className="input-with-icon">
          {isCustomPosId ? (
            /* Input field for new Position ID */
            <input
              type="text"
              name="custom_pos_id"
              value={customPosId}
              placeholder="Enter new Position ID"
              onChange={(e) => {
                const newPosId = e.target.value;
                setCustomPosId(newPosId);
                // Update droneData to reflect the new pos_id
                setDroneData((prevData) => ({
                  ...prevData,
                  pos_id: newPosId,
                  x: 0,
                  y: 0,
                }));
                alert(`Position ID "${newPosId}" defaults to (0, 0).`);
              }}
              aria-label="Custom Position ID"
            />
          ) : (
            /* Dropdown for existing Position IDs */
            <select
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

          {/* Mismatch icon if assigned mismatch or auto-detect mismatch */}
          {(posMismatch || autoDetectMismatch) && (
            <FontAwesomeIcon
              icon={faExclamationCircle}
              className="warning-icon"
              title={`Pos ID mismatch with Heartbeat or Auto-Detected value`}
              aria-label={`Pos ID mismatch with Heartbeat or Auto-Detected value`}
            />
          )}

          {/* Toggle button to switch between dropdown and input */}
          <div className="toggle-container">
            <label className="switch">
              <input
                type="checkbox"
                checked={isCustomPosId}
                onChange={() => {
                  setIsCustomPosId((prev) => !prev);
                  if (!isCustomPosId) {
                    setCustomPosId('');
                  }
                }}
              />
              <span className="slider round"></span>
            </label>
            <span className="toggle-label">
              {isCustomPosId
                ? 'Enter New Position ID'
                : 'Select Existing Position ID'}
            </span>
          </div>
        </div>

        {errors.pos_id && <span className="error-message">{errors.pos_id}</span>}

        {/* Mismatch with assigned heartbeat pos_id */}
        {posMismatch && heartbeatPos && (
          <div className="mismatch-message">
            Position ID mismatch with heartbeat: {heartbeatPos}
            <button
              type="button"
              className="accept-button"
              onClick={onAcceptPos}
              title="Accept Heartbeat Assigned PosID"
              aria-label="Accept Heartbeat Assigned PosID"
            >
              <FontAwesomeIcon icon={faCircle} /> Accept
            </button>
          </div>
        )}

        {/* Mismatch with auto-detected pos_id */}
        {autoDetectMismatch && heartbeatDetectedPos && (
          <div className="mismatch-message">
            Position ID mismatch with auto-detected: {heartbeatDetectedPos}
            <button
              type="button"
              className="accept-button"
              onClick={onAcceptPosAuto}
              title="Accept Auto-Detected PosID"
              aria-label="Accept Auto-Detected PosID"
            >
              <FontAwesomeIcon icon={faCircle} /> Accept Auto
            </button>
          </div>
        )}

        {/* If heartbeat pos_id also differs from detected_pos_id internally */}
        {internalHbPosMismatch && (
          <div className="mismatch-message">
            Heartbeat pos_id ({heartbeatPos}) vs detected_pos_id ({heartbeatDetectedPos}) differ.
            <button
              type="button"
              className="accept-button"
              onClick={() => onAcceptPosFromHbVsAuto?.('assigned')}
            >
              Accept Assigned
            </button>
            <button
              type="button"
              className="accept-button"
              onClick={() => onAcceptPosFromHbVsAuto?.('detected')}
            >
              Accept Detected
            </button>
          </div>
        )}
      </label>

      {/* Save / Cancel Buttons */}
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
 * Main DroneConfigCard:
 * Decides whether to show the read-only or edit form.
 */
export default function DroneConfigCard({
  drone,
  gitStatus,
  gcsGitStatus,
  configData,
  availableHwIds,
  editingDroneId,
  setEditingDroneId,
  saveChanges,
  removeDrone,
  networkInfo,
  heartbeatData = {}, // Defaults to empty object if not provided
  positionIdMapping,
}) {
  const isEditing = editingDroneId === drone.hw_id;
  const [droneData, setDroneData] = useState({ ...drone });
  const [errors, setErrors] = useState({});

  // Reset local form state when toggling edit mode
  useEffect(() => {
    if (isEditing) {
      setDroneData({ ...drone });
      setErrors({});
    }
  }, [isEditing, drone]);

  // Safely get the heartbeat timestamp
  const timestampVal = heartbeatData?.timestamp;
  const now = Date.now();

  // If no numeric timestamp, assume no heartbeat
  const heartbeatAgeSec =
    typeof timestampVal === 'number'
      ? Math.floor((now - timestampVal) / 1000)
      : null;

  // Compute a heartbeat status string
  let heartbeatStatus = 'No heartbeat';
  if (heartbeatAgeSec !== null) {
    if (heartbeatAgeSec < 20) heartbeatStatus = 'Online (Recent)';
    else if (heartbeatAgeSec < 60) heartbeatStatus = 'Stale (>20s)';
    else heartbeatStatus = 'Offline (>60s)';
  }

  // Mismatch checks:
  const ipMismatch =
    heartbeatData?.ip !== undefined && heartbeatData.ip !== drone.ip;

  const posMismatch =
    heartbeatData?.pos_id !== undefined &&
    heartbeatData.pos_id !== drone.pos_id;

  const hasValidAuto =
    heartbeatData?.detected_pos_id &&
    heartbeatData.detected_pos_id !== '0';

  const autoDetectMismatch =
    hasValidAuto && heartbeatData.detected_pos_id !== drone.pos_id;

  const internalHbPosMismatch =
    heartbeatData?.pos_id !== undefined &&
    hasValidAuto &&
    heartbeatData.pos_id !== heartbeatData.detected_pos_id;

  // Indicate if there's any mismatch or if the drone is newly detected
  const hasAnyMismatch =
    ipMismatch || posMismatch || autoDetectMismatch || drone.isNew;

  // Extra class to highlight mismatch visually
  const cardExtraClass = hasAnyMismatch ? ' mismatch-drone' : '';

  /** Validate and then pass updated data to the parent's saveChanges. */
  const handleLocalSave = () => {
    const validationErrors = {};

    if (!droneData.hw_id) {
      validationErrors.hw_id = 'Hardware ID is required.';
    }
    if (!droneData.ip) {
      validationErrors.ip = 'IP Address is required.';
    }
    if (!droneData.mavlink_port) {
      validationErrors.mavlink_port = 'MavLink Port is required.';
    }
    if (!droneData.debug_port) {
      validationErrors.debug_port = 'Debug Port is required.';
    }
    if (!droneData.gcs_ip) {
      validationErrors.gcs_ip = 'GCS IP is required.';
    }
    if (droneData.x === undefined || isNaN(droneData.x)) {
      validationErrors.x = 'Valid X coordinate is required.';
    }
    if (droneData.y === undefined || isNaN(droneData.y)) {
      validationErrors.y = 'Valid Y coordinate is required.';
    }
    if (!droneData.pos_id) {
      validationErrors.pos_id = 'Position ID is required.';
    }

    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors);
      return;
    }

    // Let parent handle final saving
    saveChanges(drone.hw_id, droneData);
  };

  return (
    <div className={`drone-config-card${cardExtraClass}`}>
      {isEditing ? (
        // Show the Edit Form
        <DroneEditForm
          droneData={droneData}
          errors={errors}
          ipMismatch={ipMismatch}
          posMismatch={posMismatch}
          autoDetectMismatch={autoDetectMismatch}
          internalHbPosMismatch={internalHbPosMismatch}
          heartbeatIP={heartbeatData?.ip}
          heartbeatPos={heartbeatData?.pos_id}
          heartbeatDetectedPos={heartbeatData?.detected_pos_id}
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
          onAcceptPosAuto={() => {
            if (heartbeatData?.detected_pos_id) {
              setDroneData({
                ...droneData,
                pos_id: heartbeatData.detected_pos_id,
              });
            }
          }}
          onAcceptPosFromHbVsAuto={(choice) => {
            if (choice === 'assigned' && heartbeatData?.pos_id) {
              setDroneData({ ...droneData, pos_id: heartbeatData.pos_id });
            } else if (choice === 'detected' && heartbeatData?.detected_pos_id) {
              setDroneData({
                ...droneData,
                pos_id: heartbeatData.detected_pos_id,
              });
            }
          }}
          onSave={handleLocalSave}
          onCancel={() => {
            setEditingDroneId(null);
            setDroneData({ ...drone });
            setErrors({});
          }}
          hwIdOptions={availableHwIds}
          configData={configData}
          setDroneData={setDroneData}
        />
      ) : (
        // Show the Read-Only View
        <DroneReadOnlyView
          drone={drone}
          gitStatus={gitStatus}
          gcsGitStatus={gcsGitStatus}
          isNew={drone.isNew}
          ipMismatch={ipMismatch}
          posMismatch={posMismatch}
          autoDetectMismatch={autoDetectMismatch}
          internalHbPosMismatch={internalHbPosMismatch}
          heartbeatStatus={heartbeatStatus}
          heartbeatAgeSec={heartbeatAgeSec}
          heartbeatIP={heartbeatData?.ip}
          heartbeatPos={heartbeatData?.pos_id}
          heartbeatDetectedPos={heartbeatData?.detected_pos_id}
          networkInfo={networkInfo}
          onEdit={() => setEditingDroneId(drone.hw_id)}
          onRemove={() => removeDrone(drone.hw_id)}
          onAcceptConfigFromAuto={(detectedValue) => {
            // Quick override in read-only mode
            if (!detectedValue || detectedValue === '0') return;
            saveChanges(drone.hw_id, { ...drone, pos_id: detectedValue });
          }}
          onAcceptConfigFromHb={(hbValue) => {
            if (!hbValue) return;
            saveChanges(drone.hw_id, { ...drone, pos_id: hbValue });
          }}
        />
      )}
    </div>
  );
}

DroneConfigCard.propTypes = {
  drone: PropTypes.object.isRequired,
  gitStatus: PropTypes.object,
  gcsGitStatus: PropTypes.object,
  configData: PropTypes.array.isRequired,
  availableHwIds: PropTypes.array.isRequired,
  editingDroneId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  setEditingDroneId: PropTypes.func.isRequired,
  saveChanges: PropTypes.func.isRequired,
  removeDrone: PropTypes.func.isRequired,
  networkInfo: PropTypes.object,
  heartbeatData: PropTypes.object,
  positionIdMapping: PropTypes.object,
};
