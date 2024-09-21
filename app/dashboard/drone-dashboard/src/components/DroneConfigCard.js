// app/dashboard/drone-dashboard/src/components/DroneConfigCard.jsx

import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import DroneGitStatus from './DroneGitStatus'; // Import the DroneGitStatus component

const DroneConfigCard = ({
  drone,
  availableHwIds,
  editingDroneId,
  setEditingDroneId,
  saveChanges,
  removeDrone,
}) => {
  const isEditing = editingDroneId === drone.hw_id;

  // Initialize state for form inputs when editing begins
  const [formData, setFormData] = useState({
    hw_id: drone.hw_id,
    ip: drone.ip,
    mavlink_port: drone.mavlink_port,
    debug_port: drone.debug_port,
    gcs_ip: drone.gcs_ip,
    x: drone.x,
    y: drone.y,
    pos_id: drone.pos_id,
  });

  // Update formData when drone prop changes or editing starts
  useEffect(() => {
    if (isEditing) {
      setFormData({
        hw_id: drone.hw_id,
        ip: drone.ip,
        mavlink_port: drone.mavlink_port,
        debug_port: drone.debug_port,
        gcs_ip: drone.gcs_ip,
        x: drone.x,
        y: drone.y,
        pos_id: drone.pos_id,
      });
    }
  }, [isEditing, drone]);

  // Handle input changes
  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData({ ...formData, [name]: value });
  };

  // Handle Save button click
  const handleSave = () => {
    // Basic validation (can be expanded)
    for (const key in formData) {
      if (formData[key].trim() === '') {
        alert(`Please fill out the ${key.replace('_', ' ')} field.`);
        return;
      }
    }

    saveChanges(drone.hw_id, formData);
    setEditingDroneId(null);
  };

  return (
    <div className="drone-config-card droneCard" data-hw-id={drone.hw_id}>
      <h4>Drone {drone.hw_id}</h4>
      <hr />
      {isEditing ? (
        <>
          <label htmlFor={`hw_id-${drone.hw_id}`}>Hardware ID:</label>
          <select
            id={`hw_id-${drone.hw_id}`}
            name="hw_id"
            value={formData.hw_id}
            onChange={handleInputChange}
          >
            {availableHwIds.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>

          <label htmlFor={`ip-${drone.hw_id}`}>IP Address:</label>
          <input
            type="text"
            id={`ip-${drone.hw_id}`}
            name="ip"
            value={formData.ip}
            onChange={handleInputChange}
            placeholder="Enter IP Address"
          />

          <label htmlFor={`mavlink_port-${drone.hw_id}`}>MavLink Port:</label>
          <input
            type="text"
            id={`mavlink_port-${drone.hw_id}`}
            name="mavlink_port"
            value={formData.mavlink_port}
            onChange={handleInputChange}
            placeholder="Enter MavLink Port"
          />

          <label htmlFor={`debug_port-${drone.hw_id}`}>Debug Port:</label>
          <input
            type="text"
            id={`debug_port-${drone.hw_id}`}
            name="debug_port"
            value={formData.debug_port}
            onChange={handleInputChange}
            placeholder="Enter Debug Port"
          />

          <label htmlFor={`gcs_ip-${drone.hw_id}`}>GCS IP:</label>
          <input
            type="text"
            id={`gcs_ip-${drone.hw_id}`}
            name="gcs_ip"
            value={formData.gcs_ip}
            onChange={handleInputChange}
            placeholder="Enter GCS IP Address"
          />

          <label htmlFor={`x-${drone.hw_id}`}>Initial X:</label>
          <input
            type="text"
            id={`x-${drone.hw_id}`}
            name="x"
            value={formData.x}
            onChange={handleInputChange}
            placeholder="Enter Initial X Coordinate"
          />

          <label htmlFor={`y-${drone.hw_id}`}>Initial Y:</label>
          <input
            type="text"
            id={`y-${drone.hw_id}`}
            name="y"
            value={formData.y}
            onChange={handleInputChange}
            placeholder="Enter Initial Y Coordinate"
          />

          <label htmlFor={`pos_id-${drone.hw_id}`}>Position ID:</label>
          <input
            type="text"
            id={`pos_id-${drone.hw_id}`}
            name="pos_id"
            value={formData.pos_id}
            onChange={handleInputChange}
            placeholder="Enter Position ID"
          />

          <div className="action-buttons">
            <button className="btn save" onClick={handleSave}>
              Save
            </button>
            <button
              className="btn cancel"
              onClick={() => setEditingDroneId(null)}
            >
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <p><strong>IP:</strong> {drone.ip}</p>
          <p><strong>MavLink Port:</strong> {drone.mavlink_port}</p>
          <p><strong>Debug Port:</strong> {drone.debug_port}</p>
          <p><strong>GCS IP:</strong> {drone.gcs_ip}</p>
          <p><strong>Initial Launch Position:</strong> ({drone.x}, {drone.y})</p>
          <p><strong>Position ID:</strong> {drone.pos_id}</p>
          <DroneGitStatus droneID={drone.hw_id} droneName={`Drone ${drone.hw_id}`} />
          <div className="action-buttons">
            <button className="btn edit" onClick={() => setEditingDroneId(drone.hw_id)}>Edit</button>
            <button className="btn remove" onClick={() => removeDrone(drone.hw_id)}>Remove</button>
          </div>
        </>
      )}
    </div>
  );
};

DroneConfigCard.propTypes = {
  drone: PropTypes.object.isRequired,
  availableHwIds: PropTypes.array.isRequired,
  editingDroneId: PropTypes.string,
  setEditingDroneId: PropTypes.func.isRequired,
  saveChanges: PropTypes.func.isRequired,
  removeDrone: PropTypes.func.isRequired,
};

export default DroneConfigCard;
