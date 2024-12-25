//app/dashboard/drone-dashboard/src/components/DroneGitStatus.js
import React, { useState, useEffect } from 'react';
import { getUnifiedGitStatusURL } from '../utilities/utilities';
import '../styles/DroneGitStatus.css'; // Import for consistent styling

const DroneGitStatus = ({ droneID, droneName }) => {
  const [gitStatuses, setGitStatuses] = useState(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchGitStatus() {
      try {
        const response = await fetch(getUnifiedGitStatusURL());
        if (response.ok) {
          const data = await response.json();
          setGitStatuses(data);
          setLoading(false);
        } else {
          setErrorMessage('Failed to load Git statuses from GCS.');
          setLoading(false);
        }
      } catch (error) {
        setErrorMessage('An error occurred while loading the Git statuses.');
        setLoading(false);
      }
    }

    fetchGitStatus();

    // Optionally, set an interval to refresh data every 10 seconds
    const interval = setInterval(fetchGitStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return <div className="git-loading">Loading Git status...</div>;
  }

  if (errorMessage) {
    return <div className="git-error-message">{errorMessage}</div>;
  }

  const droneGitStatus = gitStatuses ? gitStatuses[droneID] : null;

  if (!droneGitStatus) {
    return (
      <div className="git-error-message">
        Git status for this drone is not available.
      </div>
    );
  }

  const isInSync =
    gitStatuses &&
    gitStatuses.gcs &&
    droneGitStatus.branch === gitStatuses.gcs.branch &&
    droneGitStatus.commit === gitStatuses.gcs.commit;

  return (
    <div className="drone-git-status">
      <div className={`git-status-summary ${isInSync ? 'sync' : 'not-sync'}`}>
        <p><strong>Drone Name:</strong> {droneName}</p>
        <p><strong>Branch:</strong> {droneGitStatus.branch}</p>
        <p><strong>Commit:</strong> {droneGitStatus.commit}</p>
        {!isInSync && (
          <p className="warning-text">
            <strong>Warning:</strong> This drone's Git status differs from the GCS.
          </p>
        )}
      </div>
    </div>
  );
};

export default DroneGitStatus;
