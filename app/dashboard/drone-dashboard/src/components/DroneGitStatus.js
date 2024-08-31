import React, { useState, useEffect } from 'react';
import { getDroneGitStatusURLById, getGitStatusURL } from '../utilities/utilities';

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
      <h4>Git Status for {droneName}</h4>
      {errorMessage && <div className="error-message">{errorMessage}</div>}
      {gitStatus && gcsGitStatus ? (
        <div
          className="git-status-summary"
          style={{
            color: isInSync ? 'green' : 'red',
            border: `1px solid ${isInSync ? 'green' : 'red'}`,
            padding: '10px',
            borderRadius: '5px',
            marginBottom: '10px',
          }}
        >
          <p><strong>Branch:</strong> {gitStatus.branch}</p>
          <p><strong>Commit:</strong> {gitStatus.commit}</p>
          <p><strong>Status:</strong> {gitStatus.status}</p>
          {!isInSync && (
            <p><strong>Note:</strong> This drone's Git status differs from the GCS.</p>
          )}
        </div>
      ) : (
        <div>Loading Git status...</div>
      )}
    </div>
  );
};

export default DroneGitStatus;
