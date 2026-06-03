// src/components/ControlButtons.js
import React, { useRef } from 'react';
import PropTypes from 'prop-types';
import '../styles/ControlButtons.css';
import {
  FaCodeBranch,
  FaFileCsv,
  FaFileExport,
  FaMapMarkerAlt,
  FaPlus,
  FaSave,
  FaSync,
  FaUndo,
  FaUpload,
} from 'react-icons/fa';
import { CircularProgress } from '@mui/material';

/**
 * ControlButtons
 *
 * Provides top-level actions: Save, Add Drone, Set Origin, Import, Export, Revert,
 * and a Fleet Ops link for node sync.
 * with a consistent UI/UX approach.
 */
const ControlButtons = ({
  addNewDrone,
  handleSaveChangesToServer,
  handleRevertChanges,
  handleFileChange,
  exportConfig,
  exportConfigCSV,
  openOriginModal,
  handleResetToDefault,
  configData,
  setConfigData,
  loading,
  mode = 'full',
}) => {
  const fileInputRef = useRef(null);
  const showPrimaryActions = mode === 'full';

  const triggerFileInput = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  return (
    <div className={`control-buttons ${showPrimaryActions ? '' : 'control-buttons--secondary'}`.trim()}>
      {showPrimaryActions && (
        <div className="primary-actions">
          <button
            className="save"
            onClick={handleSaveChangesToServer}
            data-help="Save configuration and commit to git repository"
            disabled={loading}
          >
            {loading ? (
              <>
                <CircularProgress size={20} color="inherit" />
                &nbsp;Saving & Committing...
              </>
            ) : (
              <>
                <FaSave aria-hidden="true" />
                Save & Commit to Git
              </>
            )}
          </button>

          <a
            className="sync-drones"
            href="/fleet-ops"
            data-help="Open Fleet Ops for drone sync preview, confirmation, and sidecar reconcile"
          >
            <FaCodeBranch aria-hidden="true" />
            Fleet Ops Sync
          </a>

          <button className="add" onClick={addNewDrone} data-help="Add a new drone">
            <FaPlus aria-hidden="true" />
            Add New Drone
          </button>

          <button className="set-origin" onClick={openOriginModal} data-help="Set origin reference">
            <FaMapMarkerAlt aria-hidden="true" />
            Set Origin
          </button>
        </div>
      )}

      {/* Secondary Actions */}
      <div className="secondary-actions">
        {/* Import Config (JSON or CSV) */}
        <button
          className="file-upload-btn"
          onClick={triggerFileInput}
          data-help="Import drone config from JSON or CSV"
        >
          <FaUpload aria-hidden="true" />
          Import
        </button>
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileChange}
          style={{ display: 'none' }}
          accept=".json,.csv"
        />

        {/* Export Config (JSON) */}
        <button
          className="export-config"
          onClick={exportConfig}
          data-help="Export current drone configs to JSON"
        >
          <FaFileExport aria-hidden="true" />
          Export JSON
        </button>

        {/* Export Config (CSV) */}
        {exportConfigCSV && (
          <button
            className="export-config"
            onClick={exportConfigCSV}
            data-help="Export current drone configs to CSV"
          >
            <FaFileCsv aria-hidden="true" />
            Export CSV
          </button>
        )}

        {/* Revert */}
        <button className="revert" onClick={handleRevertChanges} data-help="Revert all unsaved changes">
          <FaUndo aria-hidden="true" />
          Revert
        </button>

        {/* Reset to Default */}
        <button
          className="reset-default"
          onClick={handleResetToDefault}
          data-help="Reset all drones so each one flies its own show slot (Position ID = Hardware ID)"
        >
          <FaSync aria-hidden="true" />
          Reset Slot Assignments
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
  exportConfigCSV: PropTypes.func,
  openOriginModal: PropTypes.func.isRequired,
  handleResetToDefault: PropTypes.func.isRequired,
  configData: PropTypes.array.isRequired,
  setConfigData: PropTypes.func.isRequired,
  loading: PropTypes.bool.isRequired,
  mode: PropTypes.oneOf(['full', 'secondary']),
};

export default ControlButtons;
