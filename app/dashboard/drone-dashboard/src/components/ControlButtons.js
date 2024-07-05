import React from 'react';
import PropTypes from 'prop-types';

const ControlButtons = ({ addNewDrone, handleSaveChangesToServer, handleRevertChanges, handleFileChange, exportConfig }) => {
  return (
    <div className="top-buttons">
      <div className="primary-actions">
        <button className="save" onClick={handleSaveChangesToServer}>Save Changes</button>
        <button className="add" onClick={addNewDrone}>
          <span className="icon">➕</span>
          <span className="addCaption">Add New Drone</span>
        </button>
      </div>
      <div className="secondary-actions">
        <label htmlFor="csvInput" className="file-upload-btn">Import CSV</label>
        <input type="file" id="csvInput" onChange={handleFileChange} />
        <button className="export-config" onClick={exportConfig} title="Export current drone configurations to a CSV file">Export Config</button>
        <button className="revert" onClick={handleRevertChanges}>Revert</button>
      </div>
    </div>
  );
};

ControlButtons.propTypes = {
  addNewDrone: PropTypes.func.isRequired,
  handleSaveChangesToServer: PropTypes.func.isRequired,
  handleRevertChanges: PropTypes.func.isRequired,
  handleFileChange: PropTypes.func.isRequired,
  exportConfig: PropTypes.func.isRequired
};

export default ControlButtons;
