import React, { useState, useEffect } from 'react';
import '../styles/GitInfo.css';
import { getGitStatusURL } from '../utilities/utilities';

const GitInfo = () => {
  const [gitInfo, setGitInfo] = useState({});
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    async function fetchGitInfo() {
      try {
        const response = await fetch(getGitStatusURL());
        const data = await response.json();
        setGitInfo(data);
      } catch (error) {
        console.error('Failed to fetch Git status:', error);
      }
    }

    fetchGitInfo();
  }, []);

  return (
    <div className="git-info-container">
      <div className="git-info-summary" onClick={() => setExpanded(!expanded)}>
        <div><strong>Branch:</strong> {gitInfo.branch}</div>
        <div><strong>Commit:</strong> {gitInfo.commit?.slice(0, 7)}...</div>
        <div className="toggle-details">{expanded ? '▲' : '▼'}</div>
      </div>

      {expanded && (
        <div className="git-info-details">
          <ul>
            <li><strong>Branch:</strong> {gitInfo.branch}</li>
            <li><strong>Commit:</strong> {gitInfo.commit}</li>
            <li><strong>Author:</strong> {gitInfo.author_name} ({gitInfo.author_email})</li>
            <li><strong>Date:</strong> {gitInfo.commit_date}</li>
            <li><strong>Message:</strong> {gitInfo.commit_message}</li>
            <li><strong>Remote URL:</strong> {gitInfo.remote_url}</li>
            <li><strong>Tracking Branch:</strong> {gitInfo.tracking_branch}</li>
            {gitInfo.uncommitted_changes && gitInfo.uncommitted_changes.length > 0 && (
              <li>
                <strong>Uncommitted Changes:</strong>
                <ul>
                  {gitInfo.uncommitted_changes.map((change, index) => (
                    <li key={index}>{change}</li>
                  ))}
                </ul>
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
};

export default GitInfo;
