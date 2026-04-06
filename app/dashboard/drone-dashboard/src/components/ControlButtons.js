// src/components/ControlButtons.js
import React, { useRef } from 'react';
import PropTypes from 'prop-types';
import '../styles/ControlButtons.css';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faSave,
  faPlus,
  faUpload,
  faFileExport,
  faFileCsv,
  faUndo,
  faMapMarkerAlt,
  faServer,
  faSync,
  faCodeBranch,
} from '@fortawesome/free-solid-svg-icons';
import { CircularProgress } from '@mui/material';
import { useSyncDrones } from '../hooks/useSyncDrones';

/**
 * ControlButtons
 *
 * Provides top-level actions: Save, Add Drone, Set Origin, Configure GCS, Import, Export, Revert, Sync Drones
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
  openGcsConfigModal,
  handleResetToDefault,
  configData,
  setConfigData,
  loading,
  mode = 'full',
}) => {
  const fileInputRef = useRef(null);
  const { syncing, syncDrones: handleSyncDrones } = useSyncDrones();
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
            title="Save configuration and commit to git repository"
            disabled={loading}
          >
            {loading ? (
              <>
                <CircularProgress size={20} color="inherit" />
                &nbsp;Saving & Committing...
              </>
            ) : (
              <>
                <FontAwesomeIcon icon={faSave} />
                Save & Commit to Git
              </>
            )}
          </button>

          <button
            className="sync-drones"
            onClick={handleSyncDrones}
            title="Trigger git pull on all drones to sync with GCS"
            disabled={syncing}
          >
            {syncing ? (
              <>
                <CircularProgress size={20} color="inherit" />
                &nbsp;Syncing...
              </>
            ) : (
              <>
                <FontAwesomeIcon icon={faCodeBranch} />
                Sync Drones
              </>
            )}
          </button>

          <button className="add" onClick={addNewDrone} title="Add a new drone">
            <FontAwesomeIcon icon={faPlus} />
            Add New Drone
          </button>

          <button className="set-origin" onClick={openOriginModal} title="Set Origin Reference">
            <FontAwesomeIcon icon={faMapMarkerAlt} />
            Set Origin
          </button>

          <button className="configure-gcs" onClick={openGcsConfigModal} title="Configure GCS Server IP">
            <FontAwesomeIcon icon={faServer} />
            Configure GCS
          </button>
        </div>
      )}

      {/* Secondary Actions */}
      <div className="secondary-actions">
        {/* Import Config (JSON or CSV) */}
        <button
          className="file-upload-btn"
          onClick={triggerFileInput}
          title="Import drone config from JSON or CSV"
        >
          <FontAwesomeIcon icon={faUpload} />
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
          title="Export current drone configs to JSON"
        >
          <FontAwesomeIcon icon={faFileExport} />
          Export JSON
        </button>

        {/* Export Config (CSV) */}
        {exportConfigCSV && (
          <button
            className="export-config"
            onClick={exportConfigCSV}
            title="Export current drone configs to CSV (legacy)"
          >
            <FontAwesomeIcon icon={faFileCsv} />
            Export CSV
          </button>
        )}

        {/* Revert */}
        <button className="revert" onClick={handleRevertChanges} title="Revert all unsaved changes">
          <FontAwesomeIcon icon={faUndo} />
          Revert
        </button>

        {/* Reset to Default */}
        <button
          className="reset-default"
          onClick={handleResetToDefault}
          title="Reset all drones so each one flies its own show slot (Position ID = Hardware ID)"
        >
          <FontAwesomeIcon icon={faSync} />
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
  openGcsConfigModal: PropTypes.func.isRequired,
  handleResetToDefault: PropTypes.func.isRequired,
  configData: PropTypes.array.isRequired,
  setConfigData: PropTypes.func.isRequired,
  loading: PropTypes.bool.isRequired,
  mode: PropTypes.oneOf(['full', 'secondary']),
};

export default ControlButtons;
