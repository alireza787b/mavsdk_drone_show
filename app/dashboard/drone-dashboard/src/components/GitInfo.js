import React, { useState, useEffect } from 'react';
import '../styles/GitInfo.css';
import { getGitStatusURL } from '../utilities/utilities';

const GitInfo = ({ collapsed = false }) => {
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

  if (collapsed) {
    return (
      <div className="git-info-collapsed" title={`${gitInfo.branch || 'main'} • ${gitInfo.commit?.slice(0, 7) || 'loading...'}`}>
        <div className="git-branch-indicator">
          <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
            <path d="M11.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm-2.25.75a2.25 2.25 0 113 2.122V6A2.5 2.5 0 018 8.5H6.5v1.378a2.25 2.25 0 11-1.5 0V5.372a2.25 2.25 0 111.5 0V7H8a1 1 0 001-1V5.622A2.25 2.25 0 0111.75 2.5zM5 4.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zM5 11.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0z"/>
          </svg>
        </div>
      </div>
    );
  }

  return (
    <div className={`git-info-simple ${expanded ? 'expanded' : ''}`} onClick={() => setExpanded(!expanded)}>
      <div className="git-summary">
        <div className="git-branch-line">
          <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor" className="branch-icon">
            <path d="M11.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm-2.25.75a2.25 2.25 0 113 2.122V6A2.5 2.5 0 018 8.5H6.5v1.378a2.25 2.25 0 11-1.5 0V5.372a2.25 2.25 0 111.5 0V7H8a1 1 0 001-1V5.622A2.25 2.25 0 0111.75 2.5zM5 4.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zM5 11.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0z"/>
          </svg>
          <span className="branch-text">{gitInfo.branch || 'main'}</span>
          <span className="commit-hash">{gitInfo.commit?.slice(0, 7) || '...'}</span>
        </div>
      </div>

      {expanded && (
        <div className="git-details">
          <div className="detail-line">
            <span className="detail-key">Author:</span>
            <span className="detail-val">{gitInfo.author_name}</span>
          </div>
          <div className="detail-line">
            <span className="detail-key">Date:</span>
            <span className="detail-val">{new Date(gitInfo.commit_date).toLocaleDateString()}</span>
          </div>
          <div className="detail-line message-line">
            <span className="detail-key">Message:</span>
            <span className="detail-val">{gitInfo.commit_message}</span>
          </div>
          {gitInfo.uncommitted_changes && gitInfo.uncommitted_changes.length > 0 && (
            <div className="changes-line">
              <span className="changes-count">{gitInfo.uncommitted_changes.length}</span> uncommitted
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default GitInfo;
