import React from 'react';
import PropTypes from 'prop-types';
import { FaMapMarkerAlt, FaPlus, FaSave } from 'react-icons/fa';

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
  const origin = stats.find(stat => stat.label === 'Origin');
  return (
    <section className="mission-config-workspace-shell" aria-label="Assignment workspace">
      <div className="mission-config-primary-bar">
        <label className="mission-config-search"><span className="mission-config-sr-only">Search</span>
          <input type="search" value={searchValue} onChange={event => onSearchChange(event.target.value)}
            placeholder="Find aircraft or slot" title={searchPlaceholder} aria-label="Search assignments by position, hardware ID, or callsign" />
        </label>
        <div className="mission-config-primary-bar__actions">
          <button
            type="button"
            className="mission-config-primary-button mission-config-primary-button--save"
            onClick={onSave}
            disabled={loading}
          >
            <FaSave aria-hidden="true" />{loading ? 'Saving…' : 'Save & Commit'}
          </button>
          <button
            type="button"
            className="mission-config-primary-button mission-config-primary-button--add"
            onClick={onAddDrone}
          >
            <FaPlus aria-hidden="true" />Add aircraft
          </button>
          <button type="button" className="mission-config-primary-button" onClick={onReviewOrigin}
            aria-label={`Origin ${origin?.value || 'unknown'} review`}><FaMapMarkerAlt aria-hidden="true" />Origin · <span>{origin?.value || 'Unknown'}</span></button>
        </div>
      </div>

      <section className="mission-config-ops-toolbar" aria-label="Mission configuration filters">
        <span className="mission-config-ops-note" title={headline}>{searchSummary.replace(/assignment cards? visible/, 'aircraft')}</span>
          {assignmentFilterOptions.length > 1 && (
            <select aria-label="Assignment filter" value={assignmentFilter} onChange={event => onAssignmentFilterChange(event.target.value)}>
              {assignmentFilterOptions.map(option => <option key={option.id} value={option.id}>{option.label} · {option.count}</option>)}
            </select>
          )}
          {clusterScopeOptions.filter(option => option.id !== 'all').length > 1 && (
            <select aria-label="Cluster scope" value={clusterScope} onChange={event => onClusterScopeChange(event.target.value)}>
              {clusterScopeOptions.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
            </select>
          )}
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
