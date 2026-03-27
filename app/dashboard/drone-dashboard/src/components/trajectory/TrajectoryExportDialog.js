import React, { useState } from 'react';
import PropTypes from 'prop-types';

const EXPORT_FORMATS = [
  {
    id: 'csv',
    label: 'CSV',
    description: 'Leader trajectory format for swarm upload or external review.',
  },
  {
    id: 'json',
    label: 'JSON',
    description: 'Full planner data with metadata for local backup and editing.',
  },
  {
    id: 'kml',
    label: 'KML',
    description: 'Google Earth preview for quick 3D route inspection.',
  },
];

const TrajectoryExportDialog = ({ isOpen, onClose, onExport, trajectoryName = '' }) => {
  const [selectedFormat, setSelectedFormat] = useState('csv');

  if (!isOpen) {
    return null;
  }

  const handleExport = () => {
    onExport(selectedFormat);
  };

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog-content trajectory-export-dialog" onClick={(event) => event.stopPropagation()}>
        <h3>Export Trajectory</h3>
        <p className="dialog-body-copy">
          Choose the output format for <strong>{trajectoryName || 'the current trajectory'}</strong>.
        </p>

        <div className="trajectory-export-options">
          {EXPORT_FORMATS.map((format) => (
            <label
              key={format.id}
              className={`trajectory-export-option ${selectedFormat === format.id ? 'selected' : ''}`}
            >
              <input
                type="radio"
                name="trajectory-export-format"
                value={format.id}
                checked={selectedFormat === format.id}
                onChange={(event) => setSelectedFormat(event.target.value)}
              />
              <div>
                <strong>{format.label}</strong>
                <p>{format.description}</p>
              </div>
            </label>
          ))}
        </div>

        <div className="dialog-buttons">
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" onClick={handleExport}>
            Export {selectedFormat.toUpperCase()}
          </button>
        </div>
      </div>
    </div>
  );
};

TrajectoryExportDialog.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onExport: PropTypes.func.isRequired,
  trajectoryName: PropTypes.string,
};

export default TrajectoryExportDialog;
