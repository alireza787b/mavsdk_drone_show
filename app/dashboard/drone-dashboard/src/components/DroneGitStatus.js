//app/dashboard/drone-dashboard/src/components/DroneGitStatus.js
import React, { useState, useEffect } from 'react';
import { getDroneGitStatusURLById, getGitStatusURL } from '../utilities/utilities';
import '../styles/DroneGitStatus.css'; // Import for consistent styling

const DroneGitStatus = ({ droneID, droneName }) => {
  const [gitStatus, setGitStatus] = useState(null);
  const [gcsGitStatus, setGcsGitStatus] = useState(null);
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    async function fetchGitStatuses() {
      try {
        const [droneResponse, gcsResponse] = await Promise.all([
          fetch(getDroneGitStatusURLById(droneID)),
          fetch(getGitStatusURL()),
        ]);

        if (droneResponse.ok && gcsResponse.ok) {
          const droneData = await droneResponse.json();
          const gcsData = await gcsResponse.json();

          setGitStatus(droneData);
          setGcsGitStatus(gcsData);
        } else {
          setErrorMessage('Failed to load Git statuses.');
        }
      } catch (error) {
        setErrorMessage('An error occurred while loading the Git statuses.');
      }
    }

    fetchGitStatuses();
  }, [droneID]);

  const isInSync =
    gitStatus &&
    gcsGitStatus &&
    gitStatus.branch === gcsGitStatus.branch &&
    gitStatus.commit === gcsGitStatus.commit;

  return (
    <div className="drone-git-status">
      {errorMessage && <div className="git-error-message">{errorMessage}</div>}
      {gitStatus && gcsGitStatus ? (
        <div className={`git-status-summary ${isInSync ? 'sync' : 'not-sync'}`}>
          <p><strong>Git Status</strong></p>
          <p><strong>Branch:</strong> {gitStatus.branch}</p>
          <p><strong>Commit:</strong> {gitStatus.commit}</p>
          {!isInSync && (
            <p className="warning-text"><strong>Warning:</strong> This drone's Git status differs from the GCS.</p>
          )}
        </div>
      ) : (
        <div className="git-loading">Loading Git status...</div>
      )}
    </div>
  );
};

export default DroneGitStatus;
