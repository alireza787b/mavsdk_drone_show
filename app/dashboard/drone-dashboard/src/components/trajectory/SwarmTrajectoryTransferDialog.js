import React from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import { getClusterStateMeta } from '../../utilities/swarmTrajectoryViewModel';

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

const formatAltitudeMix = (stats = {}) => {
  const counts = stats.altitudeReferenceCounts || {};
  return `MSL ${counts.msl || 0} · AGL ${counts.agl || 0}`;
};

const formatTerrainMix = (stats = {}) => {
  const terrain = stats.terrainCoverage || {};
  return `Accurate ${terrain.accurate || 0} · Estimated ${(terrain.estimated || 0) + (terrain.unknown || 0)}`;
};

const getClusterStatusTone = (cluster) => {
  const meta = getClusterStateMeta(cluster);
  return meta.tone === 'warning' ? 'attention' : meta.tone;
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
  stats = {},
  missionReadiness,
}) => {
  if (!isOpen) {
    return null;
  }

  const selectedCluster = clusters.find((cluster) => Number(cluster.leader_id) === Number(selectedLeaderId));
  const selectedClusterMeta = selectedCluster ? getClusterStateMeta(selectedCluster) : null;
  const missionAlerts = [
    ...missionReadiness.blockers,
    ...missionReadiness.advisories,
    ...missionReadiness.notes,
  ];

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
          <h3 id="swarm-transfer-dialog-title">Assign Leader Path</h3>
          <p>
            Assign the current planned path to a top leader cluster. Follower paths are regenerated later
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
          <div className="swarm-transfer-summary__item">
            <span className="swarm-transfer-summary__label">Altitude Plan</span>
            <strong>{formatAltitudeMix(stats)}</strong>
          </div>
          <div className="swarm-transfer-summary__item">
            <span className="swarm-transfer-summary__label">Terrain</span>
            <strong>{formatTerrainMix(stats)}</strong>
          </div>
          <div className="swarm-transfer-summary__item">
            <span className="swarm-transfer-summary__label">Transfer Posture</span>
            <strong>{missionReadiness.posture.label}</strong>
          </div>
        </div>

        <div className={`swarm-transfer-posture swarm-transfer-posture--${missionReadiness.posture.tone}`}>
          <strong>{missionReadiness.posture.label}</strong>
          <p>{missionReadiness.posture.summary}</p>
          {missionAlerts.length > 0 ? (
            <ul className="swarm-transfer-posture__list">
              {missionAlerts.map((item) => (
                <li key={`${item.code}-${item.text}`}>{item.text}</li>
              ))}
            </ul>
          ) : null}
        </div>

        {missionReadiness.blockers.length > 0 ? (
          <div className="swarm-transfer-alert swarm-transfer-alert--error" role="alert">
            <strong>Launch blockers</strong>
            <ul className="swarm-transfer-alert__list">
              {missionReadiness.blockers.map((item) => (
                <li key={`${item.code}-${item.text}`}>{item.text}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {missionReadiness.advisories.length > 0 ? (
          <div className="swarm-transfer-alert swarm-transfer-alert--warning" role="status">
            <strong>Operator review items</strong>
            <ul className="swarm-transfer-alert__list">
              {missionReadiness.advisories.map((item) => (
                <li key={`${item.code}-${item.text}`}>{item.text}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {missionReadiness.notes.length > 0 ? (
          <div className="swarm-transfer-alert swarm-transfer-alert--info" role="status">
            <strong>Mission notes</strong>
            <ul className="swarm-transfer-alert__list">
              {missionReadiness.notes.map((item) => (
                <li key={`${item.code}-${item.text}`}>{item.text}</li>
              ))}
            </ul>
          </div>
        ) : null}

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
                const meta = getClusterStateMeta(cluster);
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
                        {meta.label}
                      </span>
                    </div>
                    <p className="swarm-transfer-cluster-card__detail">
                      {meta.summary}
                    </p>
                    <p className="swarm-transfer-cluster-card__followers">
                      Followers: {followerPreview}
                    </p>
                    {(cluster.issues?.length || cluster.advisories?.length) ? (
                      <div className="swarm-transfer-cluster-card__flags">
                        {(cluster.issues || []).slice(0, 2).map((issue) => (
                          <span key={issue} className="swarm-transfer-flag swarm-transfer-flag--issue">{issue}</span>
                        ))}
                        {(cluster.advisories || []).slice(0, 2).map((advisory) => (
                          <span key={advisory} className="swarm-transfer-flag swarm-transfer-flag--advisory">{advisory}</span>
                        ))}
                      </div>
                    ) : null}
                  </button>
                );
              })}
            </div>

            {selectedCluster && selectedClusterMeta ? (
              <div className="swarm-transfer-selected-cluster">
                <strong>
                  Selected cluster: Leader {selectedCluster.leader_id} · {selectedClusterMeta.label}
                </strong>
                <p>{selectedClusterMeta.summary}</p>
                <p>
                  Uploading this path replaces the current leader CSV for the selected cluster.
                  Run processing on <Link to="/swarm-trajectory">Swarm Trajectory</Link> afterward to refresh follower outputs and review plots.
                </p>
              </div>
            ) : null}

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
            {submitting ? 'Uploading...' : missionReadiness.posture.transferLabel}
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
  stats: PropTypes.object,
  missionReadiness: PropTypes.shape({
    blockers: PropTypes.arrayOf(PropTypes.shape({
      code: PropTypes.string,
      text: PropTypes.string,
      tone: PropTypes.string,
    })),
    advisories: PropTypes.arrayOf(PropTypes.shape({
      code: PropTypes.string,
      text: PropTypes.string,
      tone: PropTypes.string,
    })),
    notes: PropTypes.arrayOf(PropTypes.shape({
      code: PropTypes.string,
      text: PropTypes.string,
      tone: PropTypes.string,
    })),
    posture: PropTypes.shape({
      tone: PropTypes.string,
      label: PropTypes.string,
      summary: PropTypes.string,
      transferLabel: PropTypes.string,
    }).isRequired,
  }).isRequired,
};

export default SwarmTrajectoryTransferDialog;
