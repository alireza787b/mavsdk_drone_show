// src/components/ControlButtons.js

import React, { useRef } from 'react';
import PropTypes from 'prop-types';
import '../styles/ControlButtons.css';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faSave,
  faPlus,
  faUpload,
  faFileCsv,
  faUndo,
  faMapMarkerAlt,
} from '@fortawesome/free-solid-svg-icons';

const ControlButtons = ({
  addNewDrone,
  handleSaveChangesToServer,
  handleRevertChanges,
  handleFileChange,
  exportConfig,
  openOriginModal,
}) => {
  const fileInputRef = useRef(null);

  const triggerFileInput = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  return (
    <div className="control-buttons">
      <div className="primary-actions">
        <button className="save" onClick={handleSaveChangesToServer} title="Save all changes">
          <FontAwesomeIcon icon={faSave} /> Save Changes
        </button>
        <button className="add" onClick={addNewDrone} title="Add a new drone">
          <FontAwesomeIcon icon={faPlus} /> Add New Drone
        </button>
        {/* New Set Origin Reference Button */}
        <button className="set-origin" onClick={openOriginModal} title="Set Origin Reference">
          <FontAwesomeIcon icon={faMapMarkerAlt} /> Set Origin Reference
        </button>
      </div>
      <div className="secondary-actions">
        <button className="file-upload-btn" onClick={triggerFileInput} title="Import drone configuration from CSV">
          <FontAwesomeIcon icon={faUpload} /> Import CSV
        </button>
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileChange}
          style={{ display: 'none' }}
          accept=".csv"
        />
        <button
          className="export-config"
          onClick={exportConfig}
          title="Export current drone configurations to a CSV file"
        >
          <FontAwesomeIcon icon={faFileCsv} /> Export Config
        </button>
        <button className="revert" onClick={handleRevertChanges} title="Revert all unsaved changes">
          <FontAwesomeIcon icon={faUndo} /> Revert
        </button>
      </div>
    </div>
  );
};

ControlButtons.propTypes = {
  addNewDrone: PropTypes.func.isRequired,
  handleSaveChangesToServer: PropTypes.func.isRequired,
  handleRevertChanges: PropTypes.func.isRequired,
  handleFileChange: PropTypes.func.isRequired,
  exportConfig: PropTypes.func.isRequired,
  openOriginModal: PropTypes.func.isRequired,
};

export default ControlButtons;
