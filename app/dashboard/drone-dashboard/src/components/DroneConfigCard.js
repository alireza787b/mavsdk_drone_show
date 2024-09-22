import React, { useState } from 'react';
import PropTypes from 'prop-types';
import DroneGitStatus from './DroneGitStatus'; // Import the DroneGitStatus component

const DroneConfigCard = ({
  drone,
  configData,
  availableHwIds,
  editingDroneId,
  setEditingDroneId,
  saveChanges,
  removeDrone,
}) => {
  const isEditing = editingDroneId === drone.hw_id;

  // Use React's useState to manage form inputs
  const [hwId, setHwId] = useState(drone.hw_id);
  const [posId, setPosId] = useState(drone.pos_id);
  const [ip, setIp] = useState(drone.ip);
  const [mavlinkPort, setMavlinkPort] = useState(drone.mavlink_port);
  const [debugPort, setDebugPort] = useState(drone.debug_port);
  const [gcsIp, setGcsIp] = useState(drone.gcs_ip);
  const [x, setX] = useState(drone.x);
  const [y, setY] = useState(drone.y);

  // Compute available Hardware IDs, including the current drone's hw_id
  const allHwIds = new Set(configData.map(d => d.hw_id));
  const maxHwId = Math.max(0, ...Array.from(allHwIds, id => parseInt(id))) + 1;
  const hwIdOptions = Array.from({ length: maxHwId }, (_, i) => (i + 1).toString()).filter(
    id => !allHwIds.has(id) || id === drone.hw_id
  );

  const handleSave = () => {
    // Validation: Check for duplicate hw_id
    if (configData.some(d => d.hw_id === hwId && d.hw_id !== drone.hw_id)) {
      alert('The selected Hardware ID is already in use. Please choose another one.');
      return;
    }

    // Validation: Check for duplicate pos_id and allow user to proceed if they confirm
    if (configData.some(d => d.pos_id === posId && d.hw_id !== drone.hw_id)) {
      if (
        !window.confirm(
          `Position ID ${posId} is already assigned to another drone. Do you want to proceed?`
        )
      ) {
        return;
      }
    }

    // Save changes and exit editing mode
    saveChanges(drone.hw_id, {
      hw_id: hwId,
      pos_id: posId,
      ip: ip,
      mavlink_port: mavlinkPort,
      debug_port: debugPort,
      gcs_ip: gcsIp,
      x: x,
      y: y,
    });
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
            value={hwId}
            onChange={e => setHwId(e.target.value)}
          >
            {hwIdOptions.map(id => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>

          <label htmlFor={`ip-${drone.hw_id}`}>IP Address:</label>
          <input
            type="text"
            id={`ip-${drone.hw_id}`}
            value={ip}
            onChange={e => setIp(e.target.value)}
            placeholder="Enter IP Address"
          />

          <label htmlFor={`mavlink_port-${drone.hw_id}`}>MavLink Port:</label>
          <input
            type="text"
            id={`mavlink_port-${drone.hw_id}`}
            value={mavlinkPort}
            onChange={e => setMavlinkPort(e.target.value)}
            placeholder="Enter MavLink Port"
          />

          <label htmlFor={`debug_port-${drone.hw_id}`}>Debug Port:</label>
          <input
            type="text"
            id={`debug_port-${drone.hw_id}`}
            value={debugPort}
            onChange={e => setDebugPort(e.target.value)}
            placeholder="Enter Debug Port"
          />

          <label htmlFor={`gcs_ip-${drone.hw_id}`}>GCS IP:</label>
          <input
            type="text"
            id={`gcs_ip-${drone.hw_id}`}
            value={gcsIp}
            onChange={e => setGcsIp(e.target.value)}
            placeholder="Enter GCS IP Address"
          />

          <label htmlFor={`x-${drone.hw_id}`}>Initial X:</label>
          <input
            type="text"
            id={`x-${drone.hw_id}`}
            value={x}
            onChange={e => setX(e.target.value)}
            placeholder="Enter Initial X Coordinate"
          />

          <label htmlFor={`y-${drone.hw_id}`}>Initial Y:</label>
          <input
            type="text"
            id={`y-${drone.hw_id}`}
            value={y}
            onChange={e => setY(e.target.value)}
            placeholder="Enter Initial Y Coordinate"
          />

          <label htmlFor={`pos_id-${drone.hw_id}`}>Position ID:</label>
          <input
            type="text"
            id={`pos_id-${drone.hw_id}`}
            value={posId}
            onChange={e => setPosId(e.target.value)}
            placeholder="Enter Position ID"
          />

          <button className="saveDrone" onClick={handleSave}>
            Save
          </button>
          <button className="cancelSaveDrone" onClick={() => setEditingDroneId(null)}>
            Cancel
          </button>
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
          <DroneGitStatus droneID={drone.hw_id} droneName={`Drone ${drone.hw_id}`} />
          <div>
            <button className="edit" onClick={() => setEditingDroneId(drone.hw_id)}>
              Edit
            </button>
            <button className="remove" onClick={() => removeDrone(drone.hw_id)}>
              Remove
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
};

export default DroneConfigCard;
