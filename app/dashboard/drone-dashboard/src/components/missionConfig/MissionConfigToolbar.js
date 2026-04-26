import React from 'react';
import PropTypes from 'prop-types';
import { CircularProgress } from '@mui/material';
import { FaPlus, FaSave } from 'react-icons/fa';

import ClusterScopeBar from '../ClusterScopeBar';
import IdentityDoctrineStrip from '../IdentityDoctrineStrip';

export default function MissionConfigToolbar({
  headline,
  loading,
  onSave,
  onAddDrone,
  searchValue,
  onSearchChange,
  searchPlaceholder,
  searchSummary,
  stats,
  onReviewOrigin,
  assignmentFilterOptions,
  assignmentFilter,
  onAssignmentFilterChange,
  clusterScopeOptions,
  clusterScope,
  onClusterScopeChange,
}) {
  return (
    <section className="mission-config-workspace-shell" aria-label="Assignment workspace">
      <div className="mission-config-primary-bar">
        <div className="mission-config-primary-bar__copy">
          <span className="mission-config-primary-bar__kicker">Assignment wall</span>
          <strong>{headline}</strong>
        </div>
        <div className="mission-config-primary-bar__actions">
          <button
            type="button"
            className="mission-config-primary-button mission-config-primary-button--save"
            onClick={onSave}
            disabled={loading}
          >
            {loading ? (
              <>
                <CircularProgress size={18} color="inherit" />
                Saving...
              </>
            ) : (
              <>
                <FaSave />
                Save & Commit
              </>
            )}
          </button>
          <button
            type="button"
            className="mission-config-primary-button mission-config-primary-button--add"
            onClick={onAddDrone}
          >
            <FaPlus />
            Add Drone
          </button>
        </div>
      </div>

      <IdentityDoctrineStrip surface="mission-config" />

      <section className="mission-config-ops-toolbar" aria-label="Mission configuration filters">
        <div className="mission-config-ops-toolbar__main">
          <label className="mission-config-search">
            <span>Search</span>
            <input
              type="search"
              value={searchValue}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder={searchPlaceholder}
              aria-label="Search assignments by position, hardware ID, or callsign"
            />
          </label>
          <div className="mission-config-ops-toolbar__summary">
            <p className="mission-config-ops-note">{searchSummary}</p>
            <div className="mission-config-ops-summary" aria-label="Mission configuration status summary">
              {stats.map((stat) => (
                <button
                  key={stat.label}
                  type="button"
                  className={`mission-config-ops-stat ${stat.tone ? `mission-config-ops-stat--${stat.tone}` : ''}`}
                  onClick={stat.label === 'Origin' ? onReviewOrigin : undefined}
                  disabled={stat.label !== 'Origin'}
                >
                  <span className="mission-config-ops-stat__label">{stat.label}</span>
                  <strong className="mission-config-ops-stat__value">{stat.value}</strong>
                  {stat.actionLabel ? (
                    <span className="mission-config-ops-stat__action">{stat.actionLabel}</span>
                  ) : null}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="mission-config-filter-rails">
          {assignmentFilterOptions.length > 1 && (
            <ClusterScopeBar
              label="Issue focus"
              options={assignmentFilterOptions}
              selectedId={assignmentFilter}
              onSelect={onAssignmentFilterChange}
            />
          )}

          {clusterScopeOptions.length > 1 && (
            <ClusterScopeBar
              label="Cluster scope"
              options={clusterScopeOptions}
              selectedId={clusterScope}
              onSelect={onClusterScopeChange}
            />
          )}
        </div>
      </section>
    </section>
  );
}

MissionConfigToolbar.propTypes = {
  headline: PropTypes.string.isRequired,
  loading: PropTypes.bool.isRequired,
  onSave: PropTypes.func.isRequired,
  onAddDrone: PropTypes.func.isRequired,
  searchValue: PropTypes.string.isRequired,
  onSearchChange: PropTypes.func.isRequired,
  searchPlaceholder: PropTypes.string.isRequired,
  searchSummary: PropTypes.string.isRequired,
  stats: PropTypes.arrayOf(PropTypes.shape({
    label: PropTypes.string.isRequired,
    value: PropTypes.node.isRequired,
    tone: PropTypes.string,
    actionLabel: PropTypes.string,
  })).isRequired,
  onReviewOrigin: PropTypes.func.isRequired,
  assignmentFilterOptions: PropTypes.arrayOf(PropTypes.shape({
    id: PropTypes.string.isRequired,
    label: PropTypes.string.isRequired,
    count: PropTypes.number,
    description: PropTypes.string,
  })).isRequired,
  assignmentFilter: PropTypes.string.isRequired,
  onAssignmentFilterChange: PropTypes.func.isRequired,
  clusterScopeOptions: PropTypes.arrayOf(PropTypes.shape({
    id: PropTypes.string.isRequired,
    label: PropTypes.string.isRequired,
    count: PropTypes.number,
    description: PropTypes.string,
  })).isRequired,
  clusterScope: PropTypes.string.isRequired,
  onClusterScopeChange: PropTypes.func.isRequired,
};
