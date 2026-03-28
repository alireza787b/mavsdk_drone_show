import React, { useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';

import { calculateTrajectoryStats } from '../../utilities/SpeedCalculator';
import '../../styles/TrajectoryLibraryDialog.css';

const formatDistance = (distance = 0) => {
  if (distance >= 1000) {
    return `${(distance / 1000).toFixed(2)} km`;
  }

  return `${distance.toFixed(0)} m`;
};

const formatDuration = (seconds = 0) => {
  if (seconds >= 60) {
    const minutes = Math.floor(seconds / 60);
    const remainder = Math.round(seconds % 60);
    return `${minutes}m ${remainder}s`;
  }

  return `${Math.round(seconds)}s`;
};

const formatModifiedTime = (timestamp) => {
  if (!timestamp) {
    return 'Unknown save time';
  }

  return new Date(timestamp).toLocaleString([], {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const getTrajectoryStats = (trajectory) => {
  if (trajectory?.metadata?.stats) {
    return trajectory.metadata.stats;
  }

  return calculateTrajectoryStats(trajectory?.waypoints || []);
};

const TrajectorySummary = ({ stats, waypointCount }) => (
  <div className="trajectory-library-dialog__summary">
    <div>
      <span className="trajectory-library-dialog__summary-label">Current path</span>
      <strong>
        {waypointCount} waypoint{waypointCount === 1 ? '' : 's'}
      </strong>
    </div>
    <div>
      <span className="trajectory-library-dialog__summary-label">Distance</span>
      <strong>{formatDistance(stats.totalDistance)}</strong>
    </div>
    <div>
      <span className="trajectory-library-dialog__summary-label">Duration</span>
      <strong>{formatDuration(stats.totalTime)}</strong>
    </div>
    <div>
      <span className="trajectory-library-dialog__summary-label">Max speed</span>
      <strong>{stats.maxSpeed.toFixed(1)} m/s</strong>
    </div>
  </div>
);

TrajectorySummary.propTypes = {
  stats: PropTypes.shape({
    maxSpeed: PropTypes.number,
    totalDistance: PropTypes.number,
    totalTime: PropTypes.number,
  }).isRequired,
  waypointCount: PropTypes.number.isRequired,
};

const TrajectoryLibraryDialog = ({
  mode,
  isOpen,
  onClose,
  onSave = () => {},
  onLoad = () => {},
  initialName = '',
  trajectories = [],
  currentStats = { totalDistance: 0, totalTime: 0, maxSpeed: 0 },
  currentWaypointCount = 0,
}) => {
  const [draftName, setDraftName] = useState(initialName);

  useEffect(() => {
    if (isOpen && mode === 'save') {
      setDraftName(initialName);
    }
  }, [initialName, isOpen, mode]);

  const sortedTrajectories = useMemo(() => {
    return [...trajectories].sort((a, b) => {
      const aAuto = a?.metadata?.isAutoSave ? 1 : 0;
      const bAuto = b?.metadata?.isAutoSave ? 1 : 0;

      if (aAuto !== bAuto) {
        return aAuto - bAuto;
      }

      const aModified = a?.metadata?.modifiedAt || a?.metadata?.createdAt || 0;
      const bModified = b?.metadata?.modifiedAt || b?.metadata?.createdAt || 0;
      return bModified - aModified;
    });
  }, [trajectories]);

  if (!isOpen) {
    return null;
  }

  const handleSave = () => {
    onSave(draftName);
  };

  const title = mode === 'save' ? 'Save Trajectory' : 'Load Trajectory';

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div
        className="dialog-content trajectory-library-dialog"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`trajectory-library-dialog-${mode}`}
      >
        <h3 id={`trajectory-library-dialog-${mode}`}>{title}</h3>

        {mode === 'save' ? (
          <>
            <p className="dialog-body-copy">
              Save the current leader route for later editing, transfer, or export. Reusing an
              existing name updates that saved trajectory in place.
            </p>
            <TrajectorySummary stats={currentStats} waypointCount={currentWaypointCount} />
            <label className="trajectory-library-dialog__field">
              <span>Name</span>
              <input
                type="text"
                placeholder="Enter trajectory name"
                value={draftName}
                onChange={(event) => setDraftName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    handleSave();
                  } else if (event.key === 'Escape') {
                    onClose();
                  }
                }}
                autoFocus
              />
            </label>
            <div className="dialog-buttons">
              <button type="button" onClick={onClose}>
                Cancel
              </button>
              <button type="button" onClick={handleSave}>
                Save Trajectory
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="dialog-body-copy">
              Reload a saved leader path into the planner. Loading replaces the current in-memory
              path but does not change Swarm Trajectory outputs until you send and process again.
            </p>
            <div className="trajectory-list trajectory-library-dialog__list">
              {sortedTrajectories.length === 0 ? (
                <p className="trajectory-library-dialog__empty">No saved trajectories found.</p>
              ) : (
                sortedTrajectories.map((trajectory) => {
                  const stats = getTrajectoryStats(trajectory);
                  const modifiedAt = trajectory?.metadata?.modifiedAt || trajectory?.metadata?.createdAt;

                  return (
                    <div key={trajectory.id} className="trajectory-item trajectory-library-dialog__item">
                      <div className="trajectory-info trajectory-library-dialog__info">
                        <div className="trajectory-library-dialog__name-row">
                          <strong>{trajectory.name}</strong>
                          {trajectory?.metadata?.isAutoSave ? (
                            <span className="trajectory-library-dialog__badge">Autosave</span>
                          ) : null}
                        </div>
                        <small>
                          {trajectory.waypoints.length} waypoint{trajectory.waypoints.length === 1 ? '' : 's'} •{' '}
                          {formatDuration(stats.totalTime)} • {formatDistance(stats.totalDistance)}
                        </small>
                        <small>
                          Max {stats.maxSpeed.toFixed(1)} m/s • Updated {formatModifiedTime(modifiedAt)}
                        </small>
                      </div>
                      <button type="button" onClick={() => onLoad(trajectory.id)}>
                        Load
                      </button>
                    </div>
                  );
                })
              )}
            </div>
            <div className="dialog-buttons">
              <button type="button" onClick={onClose}>
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

TrajectoryLibraryDialog.propTypes = {
  mode: PropTypes.oneOf(['save', 'load']).isRequired,
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onSave: PropTypes.func,
  onLoad: PropTypes.func,
  initialName: PropTypes.string,
  trajectories: PropTypes.arrayOf(
    PropTypes.shape({
      id: PropTypes.string.isRequired,
      name: PropTypes.string.isRequired,
      waypoints: PropTypes.arrayOf(PropTypes.object).isRequired,
      metadata: PropTypes.shape({
        createdAt: PropTypes.number,
        isAutoSave: PropTypes.bool,
        modifiedAt: PropTypes.number,
        stats: PropTypes.object,
      }),
    })
  ),
  currentStats: PropTypes.shape({
    maxSpeed: PropTypes.number,
    totalDistance: PropTypes.number,
    totalTime: PropTypes.number,
  }),
  currentWaypointCount: PropTypes.number,
};

export default TrajectoryLibraryDialog;
