import React from 'react';
import PropTypes from 'prop-types';

const DroneConfigCard = ({ drone, availableHwIds, editingDroneId, setEditingDroneId, saveChanges, removeDrone }) => {
  const isEditing = editingDroneId === drone.hw_id;

  return (
    <div className="drone-config-card droneCard" data-hw-id={drone.hw_id}>
      <h4>Drone {drone.hw_id}</h4>
      <hr />
      {isEditing ? (
        <>
          <label htmlFor={`hw_id-${drone.hw_id}`}>Hardware ID:</label>
          <select id={`hw_id-${drone.hw_id}`} defaultValue={drone.hw_id}>
            <option value={drone.hw_id}>{drone.hw_id}</option>
            {availableHwIds.map(id => <option key={id} value={id}>{id}</option>)}
          </select>

          <label htmlFor={`ip-${drone.hw_id}`}>IP Address:</label>
          <input type="text" id={`ip-${drone.hw_id}`} defaultValue={drone.ip} placeholder="Enter IP Address" />

          <label htmlFor={`mavlink_port-${drone.hw_id}`}>MavLink Port:</label>
          <input type="text" id={`mavlink_port-${drone.hw_id}`} defaultValue={drone.mavlink_port} placeholder="Enter MavLink Port" />

          <label htmlFor={`debug_port-${drone.hw_id}`}>Debug Port:</label>
          <input type="text" id={`debug_port-${drone.hw_id}`} defaultValue={drone.debug_port} placeholder="Enter Debug Port" />

          <label htmlFor={`gcs_ip-${drone.hw_id}`}>GCS IP:</label>
          <input type="text" id={`gcs_ip-${drone.hw_id}`} defaultValue={drone.gcs_ip} placeholder="Enter GCS IP Address" />

          <label htmlFor={`x-${drone.hw_id}`}>Initial X:</label>
          <input type="text" id={`x-${drone.hw_id}`} defaultValue={drone.x} placeholder="Enter Initial X Coordinate" />

          <label htmlFor={`y-${drone.hw_id}`}>Initial Y:</label>
          <input type="text" id={`y-${drone.hw_id}`} defaultValue={drone.y} placeholder="Enter Initial Y Coordinate" />

          <label htmlFor={`pos_id-${drone.hw_id}`}>Position ID:</label>
          <input type="text" id={`pos_id-${drone.hw_id}`} defaultValue={drone.pos_id} placeholder="Enter Position ID" />

          <button className='saveDrone' onClick={() => saveChanges(drone.hw_id, {
            hw_id: document.querySelector(`#hw_id-${drone.hw_id}`).value,
            ip: document.querySelector(`#ip-${drone.hw_id}`).value,
            mavlink_port: document.querySelector(`#mavlink_port-${drone.hw_id}`).value,
            debug_port: document.querySelector(`#debug_port-${drone.hw_id}`).value,
            gcs_ip: document.querySelector(`#gcs_ip-${drone.hw_id}`).value,
            x: document.querySelector(`#x-${drone.hw_id}`).value,
            y: document.querySelector(`#y-${drone.hw_id}`).value,
            pos_id: document.querySelector(`#pos_id-${drone.hw_id}`).value
          })}>Save</button>
          <button className='cancelSaveDrone' onClick={() => setEditingDroneId(null)}>Cancel</button>
        </>
      ) : (
        <>
          <p><strong>IP:</strong> {drone.ip}</p>
          <p><strong>MavLink Port:</strong> {drone.mavlink_port}</p>
          <p><strong>Debug Port:</strong> {drone.debug_port}</p>
          <p><strong>GCS IP:</strong> {drone.gcs_ip}</p>
          <p><strong>Initial Launch Position:</strong> ({drone.x}, {drone.y})</p>
          <p><strong>Position ID:</strong> {drone.pos_id}</p>
          <div>
            <button className="edit" onClick={() => setEditingDroneId(drone.hw_id)}>Edit</button>
            <button className="remove" onClick={() => removeDrone(drone.hw_id)}>Remove</button>
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
  removeDrone: PropTypes.func.isRequired
};

export default DroneConfigCard;
