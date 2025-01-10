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
import { CircularProgress } from '@mui/material';

/**
 * ControlButtons
 * 
 * Provides top-level actions: Save, Add Drone, Set Origin, Import, Export, Revert
 * with a consistent UI/UX approach.
 */
const ControlButtons = ({
  addNewDrone,
  handleSaveChangesToServer,
  handleRevertChanges,
  handleFileChange,
  exportConfig,
  openOriginModal,
  configData,
  setConfigData,
  loading,
}) => {
  const fileInputRef = useRef(null);

  const triggerFileInput = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  return (
    <div className="control-buttons">
      {/* Primary Actions */}
      <div className="primary-actions">
        {/* Save */}
        <button
          className="save"
          onClick={handleSaveChangesToServer}
          title="Save all changes"
          disabled={loading}
        >
          {loading ? (
            <>
              <CircularProgress size={20} color="inherit" />
              &nbsp;Saving...
            </>
          ) : (
            <>
              <FontAwesomeIcon icon={faSave} />
              Save Changes
            </>
          )}
        </button>

        {/* Add New Drone */}
        <button className="add" onClick={addNewDrone} title="Add a new drone">
          <FontAwesomeIcon icon={faPlus} />
          Add New Drone
        </button>

        {/* Set Origin */}
        <button className="set-origin" onClick={openOriginModal} title="Set Origin Reference">
          <FontAwesomeIcon icon={faMapMarkerAlt} />
          Set Origin
        </button>
      </div>

      {/* Secondary Actions */}
      <div className="secondary-actions">
        {/* Import CSV */}
        <button
          className="file-upload-btn"
          onClick={triggerFileInput}
          title="Import drone config from CSV"
        >
          <FontAwesomeIcon icon={faUpload} />
          Import CSV
        </button>
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileChange}
          style={{ display: 'none' }}
          accept=".csv"
        />

        {/* Export Config */}
        <button
          className="export-config"
          onClick={exportConfig}
          title="Export current drone configs to CSV"
        >
          <FontAwesomeIcon icon={faFileCsv} />
          Export Config
        </button>

        {/* Revert */}
        <button className="revert" onClick={handleRevertChanges} title="Revert all unsaved changes">
          <FontAwesomeIcon icon={faUndo} />
          Revert
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
  configData: PropTypes.array.isRequired,
  setConfigData: PropTypes.func.isRequired,
  loading: PropTypes.bool.isRequired,
};

export default ControlButtons;
