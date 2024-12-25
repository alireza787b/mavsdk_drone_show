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
 * Finds a drone (other than the current one) that already uses `targetPosId`.
 * Returns the entire matched drone object, or null if none found.
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
        return <FontAwesomeIcon icon={faCircle} className="status-icon online" title="Online (Recent)" aria-label="Online (Recent)" />;
      case 'Stale (>20s)':
        return <FontAwesomeIcon icon={faExclamationTriangle} className="status-icon stale" title="Stale (>20s)" aria-label="Stale (>20s)" />;
      case 'Offline (>60s)':
        return <FontAwesomeIcon icon={faTimesCircle} className="status-icon offline" title="Offline (>60s)" aria-label="Offline (>60s)" />;
      default:
        return <FontAwesomeIcon icon={faCircle} className="status-icon no-heartbeat" title="No Heartbeat" aria-label="No Heartbeat" />;
    }
  };

  // Determine Wi-Fi icon
  const getWifiIcon = (strength) => {
    if (strength >= 80) return <FontAwesomeIcon icon={faSignal} className="wifi-icon strong" title="Strong Signal" aria-label="Strong Signal" />;
    if (strength >= 50) return <FontAwesomeIcon icon={faSignal} className="wifi-icon medium" title="Medium Signal" aria-label="Medium Signal" />;
    if (strength > 0) return <FontAwesomeIcon icon={faSignal} className="wifi-icon weak" title="Weak Signal" aria-label="Weak Signal" />;
    return <FontAwesomeIcon icon={faSignal} className="wifi-icon none" title="No Signal" aria-label="No Signal" />;
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

      {networkInfo ? (
        <div className="network-info" aria-label="Network Information">
          <p><strong>Network Status:</strong> {ssid ? `SSID: ${ssid}` : 'N/A'}</p>
          <p>
            <strong>Signal Strength:</strong> {wifiStrength || 'N/A'} {getWifiIcon(wifiStrength)}
          </p>
          <p><strong>Ethernet:</strong> {ethernetInterface || 'N/A'}</p>
        </div>
      ) : (
        <p><strong>Network Info:</strong> Not available</p>
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
 * Edit Form: Let the user modify drone fields, including `pos_id`.
 * If the user picks a `pos_id` used by another drone, we'll show old/new (x,y) confirmation.
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


  // For showing old vs. new in the dialog
  const [oldX, setOldX] = useState(droneData.x);
  const [oldY, setOldY] = useState(droneData.y);
  const [newX, setNewX] = useState(droneData.x);
  const [newY, setNewY] = useState(droneData.y);

  // We keep a separate local copy of the original pos_id for revert
  const [originalPosId, setOriginalPosId] = useState(droneData.pos_id);

  // Position IDs from configData for the <select>
  const allPosIds = Array.from(new Set(configData.map((d) => d.pos_id)));

  // If current pos_id not in that array (e.g. brand new), include it
  if (!allPosIds.includes(droneData.pos_id)) {
    allPosIds.push(droneData.pos_id);
  }

  // Sort them for nicer UI
  allPosIds.sort((a, b) => {
    const ai = parseInt(a, 10);
    const bi = parseInt(b, 10);
    return ai - bi;
  });

  /** Handler: user changed the Position ID from the <select> */
  const handlePosSelectChange = (e) => {
    const chosenPos = e.target.value;

    // If the user re-selects the same pos_id, do nothing
    if (chosenPos === droneData.pos_id) return;

    // We'll show them a confirmation dialog, comparing old vs. new
    setPendingPosId(chosenPos);

    // Identify if that pos_id belongs to an existing drone
    const matchedDrone = findDroneByPositionId(configData, chosenPos, droneData.hw_id);

    setOldX(droneData.x);
    setOldY(droneData.y);

    if (matchedDrone) {
      setNewX(matchedDrone.x);
      setNewY(matchedDrone.y);
    } else {
      // If no matched drone, we won't auto-update x,y. They remain the same
      setNewX(droneData.x);
      setNewY(droneData.y);
    }

    setShowPosChangeDialog(true);
  };

  /** Cancel the pos_id change => revert select box to old pos_id */
  const handleCancelPosChange = () => {
    setShowPosChangeDialog(false);
    setPendingPosId(null);
    // revert the select box
    onFieldChange({ target: { name: 'pos_id', value: originalPosId } });
  };

  /** Confirm the pos_id change => auto-update local droneData.x,y if matched */
  /** Confirm the pos_id change => auto-update local droneData.x,y if matched */
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

    // Ensure the local droneData state is updated
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

  

  /** Generic onChange handler for other fields */
  const handleGenericChange = (e) => {
    onFieldChange(e);
  };

  return (
    <>
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
        <select
        name="pos_id"
        value={droneData.pos_id} // This should now reflect the updated value
        onChange={handlePosSelectChange}
        aria-label="Position ID"
      >
        {allPosIds.map((pid) => (
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
 * Main DroneConfigCard:
 * - Shows read-only or edit form
 * - Uses `saveChanges` from parent to update configData in memory (not server)
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
  const [showDuplicatePosDialog, setShowDuplicatePosDialog] = useState(false);

  // Reset local form on entering edit mode
  useEffect(() => {
    if (isEditing) {
      setDroneData({ ...drone });
      setErrors({});
    }
  }, [isEditing, drone]);

  // Calculate heartbeat info
  const now = Date.now();
  const heartbeatAgeSec = heartbeatData ? Math.floor((now - heartbeatData.timestamp) / 1000) : null;
  let heartbeatStatus = 'No heartbeat';
  if (heartbeatAgeSec !== null) {
    if (heartbeatAgeSec < 20) heartbeatStatus = 'Online (Recent)';
    else if (heartbeatAgeSec < 60) heartbeatStatus = 'Stale (>20s)';
    else heartbeatStatus = 'Offline (>60s)';
  }

  // Mismatch detection
  const ipMismatch = heartbeatData ? heartbeatData.ip !== drone.ip : false;
  const posMismatch = heartbeatData ? heartbeatData.pos_id !== drone.pos_id : false;

  // Build hardware ID <select> from parent's availableHwIds
  const allHwIds = new Set(configData.map((d) => d.hw_id));
  const maxHwId = Math.max(0, ...Array.from(allHwIds, (id) => parseInt(id, 10))) + 1;
  const hwIdList = Array.from({ length: maxHwId }, (_, i) => (i + 1).toString()).filter(
    (id) => !allHwIds.has(id) || id === drone.hw_id
  );

  // Card styling for new/mismatch
  const cardExtraClass = drone.isNew
    ? ' new-drone'
    : (ipMismatch || posMismatch)
    ? ' mismatch-drone'
    : '';

  /** Validate and then pass updated data to parent's `saveChanges` */
  const handleLocalSave = () => {
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

    // Let parent handle final insertion into configData
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
              setDroneData({ ...droneData, ip: heartbeatData.ip });
            }
          }}
          onAcceptPos={() => {
            if (heartbeatData?.pos_id) {
              setDroneData({ ...droneData, pos_id: heartbeatData.pos_id });
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
          onEdit={() => setEditingDroneId(drone.hw_id)}
          onRemove={() => removeDrone(drone.hw_id)}
        />
      )}
    </div>
  );
}

DroneConfigCard.propTypes = {
  drone: PropTypes.object.isRequired,
  gitStatus: PropTypes.object,
  configData: PropTypes.array.isRequired,
  availableHwIds: PropTypes.array.isRequired,
  editingDroneId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  setEditingDroneId: PropTypes.func.isRequired,
  saveChanges: PropTypes.func.isRequired,
  removeDrone: PropTypes.func.isRequired,
  networkInfo: PropTypes.object,
  heartbeatData: PropTypes.object,
};

