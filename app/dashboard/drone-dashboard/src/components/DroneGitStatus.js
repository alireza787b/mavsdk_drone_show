// src/components/DroneGitStatus.js

import React from 'react';
import PropTypes from 'prop-types';
import '../styles/DroneGitStatus.css';

/**
 * DroneGitStatus Component
 * Displays the Git status information for a drone.
 * Shows a loading message if Git status is unavailable.
 */
const DroneGitStatus = ({ gitStatus, droneName }) => {
  if (!gitStatus) {
    return (
      <div className="git-loading" role="status" aria-label={`Git status unavailable for ${droneName}`}>
        Git status not available.
      </div>
    );
  }

  const isInSync = gitStatus.status === 'clean';

  return (
    <div
      className={`drone-git-status ${isInSync ? 'sync' : 'not-sync'}`}
      aria-label={`Git Status for ${droneName}`}
    >
      <p>
        <strong>{droneName}</strong>
      </p>
      <p>
        <strong>Branch:</strong> {gitStatus.branch || 'N/A'}
      </p>
      <p>
        <strong>Commit:</strong> {gitStatus.commit || 'N/A'}
      </p>
      <p>
        <strong>Status:</strong> {gitStatus.status || 'N/A'}
      </p>
      {gitStatus.uncommitted_changes && gitStatus.uncommitted_changes.length > 0 && (
        <div>
          <p>
            <strong>Uncommitted Changes:</strong>
          </p>
          <ul>
            {gitStatus.uncommitted_changes.map((change, index) => (
              <li key={index}>{change}</li>
            ))}
          </ul>
        </div>
      )}
      {!isInSync && (
        <p className="warning-text" role="alert">
          This drone's Git status is not in sync.
        </p>
      )}
    </div>
  );
};

DroneGitStatus.propTypes = {
  gitStatus: PropTypes.shape({
    branch: PropTypes.string,
    commit: PropTypes.string,
    status: PropTypes.string,
    uncommitted_changes: PropTypes.arrayOf(PropTypes.string),
  }),
  droneName: PropTypes.string.isRequired,
};

export default DroneGitStatus;
