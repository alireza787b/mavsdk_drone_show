import React, { useState, useEffect } from 'react';
import '../styles/MissionDetails.css';
import { DRONE_MISSION_IMAGES, DRONE_MISSION_TYPES } from '../constants/droneConstants';
import { getSwarmClusterStatus } from '../services/droneApiService';

const MissionDetails = ({
  missionType,
  icon,
  label,
  description,
  useSlider,
  timeDelay,
  selectedTime,
  onTimeDelayChange,
  onTimePickerChange,
  onSliderToggle,
  onSend,
  onBack,
}) => {
  const [clusterStatus, setClusterStatus] = useState(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const missionImageSrc = DRONE_MISSION_IMAGES[missionType];

  useEffect(() => {
    if (missionType === DRONE_MISSION_TYPES.SWARM_TRAJECTORY) {
      setStatusLoading(true);
      getSwarmClusterStatus()
        .then(data => {
          setClusterStatus(data);
        })
        .catch(error => {
          console.error('Failed to fetch cluster status:', error);
          setClusterStatus({ error: 'Failed to load cluster status' });
        })
        .finally(() => {
          setStatusLoading(false);
        });
    }
  }, [missionType]);

  return (
    <div className="mission-details">
      <div className="selected-mission-card">
        <div className="mission-icon">{icon}</div>
        <div className="mission-name">{label}</div>
        <div className="mission-description">{description}</div>
      </div>

      {/* Display mission-specific image */}
      {missionImageSrc && (
        <div className="mission-preview">
          <h3>Mission Preview:</h3>
          <img src={missionImageSrc} alt={`${label} Image`} className="mission-image" />
        </div>
      )}

      {/* Trajectory Status Summary for Swarm Trajectory Mode */}
      {missionType === DRONE_MISSION_TYPES.SWARM_TRAJECTORY && (
        <div className="trajectory-status-summary">
          <h3>Swarm Trajectory Status</h3>
          {statusLoading ? (
            <div className="status-loading">
              <span className="loading-spinner">⏳</span> Loading cluster status...
            </div>
          ) : clusterStatus?.error ? (
            <div className="status-error">
              <span className="error-icon">⚠️</span> {clusterStatus.error}
            </div>
          ) : clusterStatus ? (
            <div className="cluster-summary">
              <div className="summary-stats">
                <div className="stat-item">
                  <span className="stat-value">{clusterStatus.clusters?.length || 0}</span>
                  <span className="stat-label">Clusters</span>
                </div>
                <div className="stat-item">
                  <span className="stat-value">{clusterStatus.total_leaders || 0}</span>
                  <span className="stat-label">Leaders</span>
                </div>
                <div className="stat-item">
                  <span className="stat-value">{clusterStatus.total_followers || 0}</span>
                  <span className="stat-label">Followers</span>
                </div>
                <div className="stat-item">
                  <span className="stat-value">{clusterStatus.processed_trajectories || 0}</span>
                  <span className="stat-label">Processed</span>
                </div>
              </div>
              
              {clusterStatus.clusters && clusterStatus.clusters.length > 0 && (
                <div className="cluster-details">
                  <h4>Cluster Configuration:</h4>
                  <div className="cluster-list">
                    {clusterStatus.clusters.map((cluster, index) => (
                      <div key={index} className="cluster-item">
                        <div className="cluster-info">
                          <span className="cluster-leader">Leader {cluster.leader_id}</span>
                          <span className="cluster-count">{cluster.follower_count} followers</span>
                        </div>
                        <div className="cluster-status">
                          {cluster.has_trajectory ? (
                            <span className="status-ready">✅ Ready</span>
                          ) : (
                            <span className="status-missing">❌ Missing CSV</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              <div className="status-reminder">
                <div className="reminder-icon">💡</div>
                <div className="reminder-text">
                  <strong>Reminder:</strong> You can select specific drones to target from the drone selection options above.
                  Upload trajectories and process formations in the Swarm Trajectory page before triggering.
                </div>
              </div>
            </div>
          ) : (
            <div className="status-unavailable">
              <span className="info-icon">ℹ️</span> Status information unavailable
            </div>
          )}
        </div>
      )}

      <div className="time-selection">
        <label>
          <input
            type="radio"
            checked={useSlider}
            onChange={() => onSliderToggle(true)}
          />
          Set delay in seconds
        </label>
        <label>
          <input
            type="radio"
            checked={!useSlider}
            onChange={() => onSliderToggle(false)}
          />
          Set exact time
        </label>
      </div>

      {useSlider ? (
        <div className="time-delay-slider">
          <label htmlFor="time-delay">Time Delay (seconds): {timeDelay}</label>
          <input
            type="range"
            id="time-delay"
            min="0"
            max="60"
            value={timeDelay}
            onChange={(e) => onTimeDelayChange(e.target.value)}
          />
        </div>
      ) : (
        <div className="time-picker">
          <label htmlFor="time-picker">Select Time:</label>
          <input
            type="time"
            id="time-picker"
            value={selectedTime}
            onChange={(e) => onTimePickerChange(e.target.value)}
            step="1"
          />
        </div>
      )}

      <button onClick={onSend} className="mission-button">
        Send Command
      </button>
      <button onClick={onBack} className="back-button">
        Back
      </button>
    </div>
  );
};

export default MissionDetails;
