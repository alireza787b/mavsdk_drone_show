import React from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';

import '../../styles/SwarmTrajectoryTransferDialog.css';

const formatDistance = (distance = 0) => {
  if (distance >= 1000) {
    return `${(distance / 1000).toFixed(2)} km`;
  }
  return `${distance.toFixed(0)} m`;
};

const formatTime = (time = 0) => {
  if (time >= 60) {
    const minutes = Math.floor(time / 60);
    const seconds = Math.round(time % 60);
    return `${minutes}m ${seconds}s`;
  }
  return `${Math.round(time)}s`;
};

const getClusterStatusLabel = (cluster) => {
  if (cluster.ready) {
    return 'Ready';
  }
  if (cluster.leader_uploaded) {
    return 'Needs Processing';
  }
  return 'Missing CSV';
};

const getClusterStatusTone = (cluster) => {
  if (cluster.ready) {
    return 'ready';
  }
  if (cluster.leader_uploaded) {
    return 'processing';
  }
  return 'missing';
};

const getClusterStatusDetail = (cluster) => {
  if (cluster.ready) {
    return 'Leader and followers already have processed trajectory outputs.';
  }
  if (cluster.leader_uploaded) {
    return 'A leader CSV exists, but this cluster still needs a fresh processing pass.';
  }
  return 'No leader trajectory is uploaded for this cluster yet.';
};

const SwarmTrajectoryTransferDialog = ({
  isOpen,
  onClose,
  onSubmit,
  clusters,
  loading = false,
  submitting = false,
  selectedLeaderId = '',
  onSelectLeaderId,
  error = '',
  successMessage = '',
  onOpenSwarmTrajectory,
  onOpenSwarmDesign,
  trajectoryName = '',
  waypointCount = 0,
  totalDistance = 0,
  totalTime = 0,
}) => {
  if (!isOpen) {
    return null;
  }

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div
        className="dialog-content swarm-transfer-dialog"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="swarm-transfer-dialog-title"
      >
        <div className="swarm-transfer-dialog__header">
          <h3 id="swarm-transfer-dialog-title">Send Trajectory to Swarm</h3>
          <p>
            Assign the current planned path to a top leader. Follower paths are regenerated later
            from the current <Link to="/swarm-design">Swarm Design</Link> during processing.
          </p>
        </div>

        <div className="swarm-transfer-summary">
          <div className="swarm-transfer-summary__item">
            <span className="swarm-transfer-summary__label">Trajectory</span>
            <strong>{trajectoryName || 'Unsaved trajectory'}</strong>
          </div>
          <div className="swarm-transfer-summary__item">
            <span className="swarm-transfer-summary__label">Waypoints</span>
            <strong>{waypointCount}</strong>
          </div>
          <div className="swarm-transfer-summary__item">
            <span className="swarm-transfer-summary__label">Path Length</span>
            <strong>{formatDistance(totalDistance)}</strong>
          </div>
          <div className="swarm-transfer-summary__item">
            <span className="swarm-transfer-summary__label">Duration</span>
            <strong>{formatTime(totalTime)}</strong>
          </div>
        </div>

        {error ? (
          <div className="swarm-transfer-alert swarm-transfer-alert--error" role="alert">
            {error}
          </div>
        ) : null}

        {successMessage ? (
          <div className="swarm-transfer-alert swarm-transfer-alert--success" role="status">
            {successMessage}
          </div>
        ) : null}

        {loading ? (
          <div className="swarm-transfer-loading">Loading current swarm clusters...</div>
        ) : clusters.length === 0 ? (
          <div className="swarm-transfer-empty">
            <p>No top leaders are available yet.</p>
            <p>
              Configure the hierarchy first in <Link to="/swarm-design">Swarm Design</Link>, then
              reopen this transfer flow.
            </p>
            <div className="swarm-transfer-inline-actions">
              <button type="button" onClick={onOpenSwarmDesign}>
                Open Swarm Design
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="swarm-transfer-clusters">
              {clusters.map((cluster) => {
                const selected = Number(selectedLeaderId) === Number(cluster.leader_id);
                const tone = getClusterStatusTone(cluster);
                const followerPreview = cluster.follower_ids.length > 0
                  ? cluster.follower_ids.join(', ')
                  : 'No followers';

                return (
                  <button
                    type="button"
                    key={cluster.leader_id}
                    className={`swarm-transfer-cluster-card ${selected ? 'selected' : ''}`}
                    onClick={() => onSelectLeaderId(cluster.leader_id)}
                  >
                    <div className="swarm-transfer-cluster-card__header">
                      <div>
                        <strong>Leader {cluster.leader_id}</strong>
                        <p>{cluster.follower_count} follower{cluster.follower_count === 1 ? '' : 's'}</p>
                      </div>
                      <span className={`swarm-transfer-status-badge ${tone}`}>
                        {getClusterStatusLabel(cluster)}
                      </span>
                    </div>
                    <p className="swarm-transfer-cluster-card__detail">
                      {getClusterStatusDetail(cluster)}
                    </p>
                    <p className="swarm-transfer-cluster-card__followers">
                      Followers: {followerPreview}
                    </p>
                  </button>
                );
              })}
            </div>

            <div className="swarm-transfer-note">
              <strong>Execution note:</strong> this step uploads only the selected leader CSV.
              Run processing on <Link to="/swarm-trajectory">Swarm Trajectory</Link> to regenerate
              follower paths, plots, and commit-ready outputs.
            </div>

            {successMessage ? (
              <div className="swarm-transfer-inline-actions">
                <button type="button" onClick={onOpenSwarmTrajectory}>
                  Open Swarm Trajectory
                </button>
              </div>
            ) : null}
          </>
        )}

        <div className="dialog-buttons">
          <button type="button" onClick={onClose}>
            Close
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={loading || submitting || !selectedLeaderId || clusters.length === 0}
          >
            {submitting ? 'Uploading...' : 'Send to Leader'}
          </button>
        </div>
      </div>
    </div>
  );
};

SwarmTrajectoryTransferDialog.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onSubmit: PropTypes.func.isRequired,
  clusters: PropTypes.arrayOf(
    PropTypes.shape({
      leader_id: PropTypes.oneOfType([PropTypes.number, PropTypes.string]).isRequired,
      follower_ids: PropTypes.arrayOf(PropTypes.oneOfType([PropTypes.number, PropTypes.string])).isRequired,
      follower_count: PropTypes.number.isRequired,
      ready: PropTypes.bool,
      leader_uploaded: PropTypes.bool,
    })
  ).isRequired,
  loading: PropTypes.bool,
  submitting: PropTypes.bool,
  selectedLeaderId: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  onSelectLeaderId: PropTypes.func.isRequired,
  error: PropTypes.string,
  successMessage: PropTypes.string,
  onOpenSwarmTrajectory: PropTypes.func.isRequired,
  onOpenSwarmDesign: PropTypes.func.isRequired,
  trajectoryName: PropTypes.string,
  waypointCount: PropTypes.number,
  totalDistance: PropTypes.number,
  totalTime: PropTypes.number,
};

export default SwarmTrajectoryTransferDialog;
