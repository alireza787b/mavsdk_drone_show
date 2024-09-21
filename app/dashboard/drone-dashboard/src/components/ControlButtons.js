// app/dashboard/drone-dashboard/src/components/ControlButtons.jsx

import React, { useRef } from 'react';
import PropTypes from 'prop-types';
import '../styles/MissionConfig.css'; // Utilize existing CSS styles

const ControlButtons = ({
  addNewDrone,
  handleSaveChangesToServer,
  handleRevertChanges,
  handleFileChange,
  exportConfig,
  isSaving,
  isReverting,
  isExporting
}) => {
  const fileInputRef = useRef(null);

  /**
   * Trigger the file input dialog when the import button is clicked
   */
  const handleImportClick = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  /**
   * Handle file selection and reset input value
   */
  const handleFileChangeWrapper = (event) => {
    handleFileChange(event);
    // Reset the input value to allow the same file to be uploaded again if needed
    event.target.value = null;
  };

  return (
    <div className="top-buttons">
      <div className="primary-actions">
        <button
          className="btn save"
          onClick={handleSaveChangesToServer}
          disabled={isSaving}
          aria-label="Save Changes"
        >
          {isSaving ? 'Saving...' : 'Save Changes'}
        </button>
        <button
          className="btn add"
          onClick={addNewDrone}
          aria-label="Add New Drone"
        >
          <span className="icon" aria-hidden="true">➕</span>
          <span className="addCaption">Add New Drone</span>
        </button>
      </div>
      <div className="secondary-actions">
        <button
          className="btn import-btn"
          onClick={handleImportClick}
          aria-label="Import Configuration CSV"
        >
          Import CSV
        </button>
        <input
          type="file"
          id="csvInput"
          ref={fileInputRef}
          onChange={handleFileChangeWrapper}
          accept=".csv"
          style={{ display: 'none' }}
        />
        <button
          className="btn export-config"
          onClick={exportConfig}
          disabled={isExporting}
          aria-label="Export Configuration as CSV"
          title="Export current drone configurations to a CSV file"
        >
          {isExporting ? 'Exporting...' : 'Export Config'}
        </button>
        <button
          className="btn revert"
          onClick={handleRevertChanges}
          disabled={isReverting}
          aria-label="Revert Changes"
        >
          {isReverting ? 'Reverting...' : 'Revert'}
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
  isSaving: PropTypes.bool,
  isReverting: PropTypes.bool,
  isExporting: PropTypes.bool
};

ControlButtons.defaultProps = {
  isSaving: false,
  isReverting: false,
  isExporting: false
};

export default ControlButtons;
