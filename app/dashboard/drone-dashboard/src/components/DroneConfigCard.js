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
  networkInfo // Network information passed down as a prop
}) => {
  const isEditing = editingDroneId === drone.hw_id;

  // Use React's useState to manage form inputs
  const [droneData, setDroneData] = useState({ ...drone });
  const [errors, setErrors] = useState({});

  // Compute available Hardware IDs, including the current drone's hw_id
  const allHwIds = new Set(configData.map(d => d.hw_id));
  const maxHwId = Math.max(0, ...Array.from(allHwIds, id => parseInt(id))) + 1;
  const hwIdOptions = Array.from({ length: maxHwId }, (_, i) => (i + 1).toString()).filter(
    id => !allHwIds.has(id) || id === drone.hw_id
  );

  // Handler for input changes
  const handleChange = (e) => {
    const { name, value } = e.target;
    setDroneData({ ...droneData, [name]: value });
  };

  // Input validation
  const validateInputs = () => {
    const errors = {};
    if (!droneData.hw_id) {
      errors.hw_id = 'Hardware ID is required.';
    }
    if (!droneData.ip) {
      errors.ip = 'IP Address is required.';
    }
    if (!droneData.mavlink_port) {
      errors.mavlink_port = 'MavLink Port is required.';
    }
    if (!droneData.debug_port) {
      errors.debug_port = 'Debug Port is required.';
    }
    if (!droneData.gcs_ip) {
      errors.gcs_ip = 'GCS IP is required.';
    }
    if (!droneData.x || isNaN(droneData.x)) {
      errors.x = 'Valid X coordinate is required.';
    }
    if (!droneData.y || isNaN(droneData.y)) {
      errors.y = 'Valid Y coordinate is required.';
    }
    if (!droneData.pos_id) {
      errors.pos_id = 'Position ID is required.';
    }
    setErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSave = () => {
    if (!validateInputs()) {
      return;
    }

    // Validation: Check for duplicate hw_id
    if (configData.some(d => d.hw_id === droneData.hw_id && d.hw_id !== drone.hw_id)) {
      alert('The selected Hardware ID is already in use. Please choose another one.');
      return;
    }

    // Validation: Check for duplicate pos_id and allow user to proceed if they confirm
    if (configData.some(d => d.pos_id === droneData.pos_id && d.hw_id !== drone.hw_id)) {
      if (
        !window.confirm(
          `Position ID ${droneData.pos_id} is already assigned to another drone. Do you want to proceed?`
        )
      ) {
        return;
      }
    }

    // Save changes and exit editing mode
    saveChanges(drone.hw_id, droneData);
  };

  // Network info for the current drone
  const droneNetworkInfo = networkInfo[drone.hw_id] || null;

  return (
    <div className="drone-config-card" data-hw-id={drone.hw_id}>
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
            />
            {errors.ip && <span className="error-message">{errors.ip}</span>}
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
            />
            {errors.pos_id && <span className="error-message">{errors.pos_id}</span>}
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
          <p>
            <strong>IP:</strong> {drone.ip}
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
          <p>
            <strong>Position ID:</strong> {drone.pos_id}
          </p>

          {/* Network Information Display */}
          {droneNetworkInfo ? (
            <div className="network-info">
              <p><strong>Network SSID:</strong> {droneNetworkInfo.ssid}</p>
              <p><strong>Signal Strength:</strong> {droneNetworkInfo.signal}%</p>
              <p><strong>Connection Type:</strong> {droneNetworkInfo.connection_type}</p>
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
  networkInfo: PropTypes.object, // New prop for network info
};

export default DroneConfigCard;
