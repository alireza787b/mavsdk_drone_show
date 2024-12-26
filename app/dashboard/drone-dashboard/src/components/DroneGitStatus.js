// src/components/DroneGitStatus.js

import React from 'react';
import '../styles/DroneGitStatus.css';

const DroneGitStatus = ({ gitStatus, droneName }) => {
  if (!gitStatus) {
    return <div className="git-loading">Git status not available.</div>;
  }

  const isInSync = gitStatus.status === 'clean';

  return (
    <div className={`drone-git-status ${isInSync ? 'sync' : 'not-sync'}`}>
      <p><strong>{droneName}</strong></p>
      <p><strong>Branch:</strong> {gitStatus.branch}</p>
      <p><strong>Commit:</strong> {gitStatus.commit}</p>
      <p><strong>Status:</strong> {gitStatus.status}</p>
      {gitStatus.uncommitted_changes && (
        <div>
          <p><strong>Uncommitted Changes:</strong></p>
          <ul>
            {gitStatus.uncommitted_changes.map((change, index) => (
              <li key={index}>{change}</li>
            ))}
          </ul>
        </div>
      )}
      {!isInSync && <p className="warning-text">This drone's Git status is not in sync.</p>}
    </div>
  );
};

export default DroneGitStatus;
