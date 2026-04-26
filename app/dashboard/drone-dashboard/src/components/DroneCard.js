import React, { forwardRef } from 'react';
import {
  FaChevronDown,
  FaChevronRight,
  FaExclamationTriangle,
  FaExchangeAlt,
  FaLink,
  FaSatelliteDish,
} from 'react-icons/fa';
import '../styles/DroneCard.css';
import { formatDroneLabel, formatShowSlotLabel } from '../utilities/missionIdentityUtils';

const DroneCard = forwardRef(function DroneCard(
  {
    drone,
    draftAssignment,
    followOptions,
    onSelect,
    onToggleExpand,
    onAssignmentChange,
    isSelected,
    isExpanded,
    isDirty,
  },
  ref
) {
  const draft = draftAssignment || drone;
  const followValue = String(draft.follow ?? drone.follow ?? '0');
  const frameValue = String(draft.frame ?? drone.frame ?? 'ned');
  const isIndependentLeader = followValue === '0';

  const handleCardSelect = () => {
    onSelect(drone.hw_id);
  };

  const handleToggleExpand = (event) => {
    event.stopPropagation();
    onSelect(drone.hw_id);
    onToggleExpand(drone.hw_id);
  };

  const handleFollowChange = (event) => {
    const nextFollow = event.target.value;

    onAssignmentChange(drone.hw_id, {
      follow: nextFollow,
      offset_x: nextFollow === '0' ? '0' : draft.offset_x,
      offset_y: nextFollow === '0' ? '0' : draft.offset_y,
      offset_z: nextFollow === '0' ? '0' : draft.offset_z,
    });
  };

  const handleFrameChange = (event) => {
    onAssignmentChange(drone.hw_id, {
      frame: event.target.value,
    });
  };

  const handleOffsetChange = (axisKey) => (event) => {
    onAssignmentChange(drone.hw_id, {
      [axisKey]: event.target.value,
    });
  };

  const followTargetText = drone.follow === '0'
    ? 'Independent leader'
    : drone.followTargetExists
      ? `${formatDroneLabel(drone.follow)} · ${formatShowSlotLabel(drone.followTargetPosId)}`
      : `${formatDroneLabel(drone.follow)} unavailable`;

  const followerSummary = drone.directFollowers.length > 0
    ? drone.directFollowers.map((followerId) => formatDroneLabel(followerId)).join(', ')
    : 'None';

  return (
    <article
      ref={ref}
      tabIndex={-1}
      className={[
        'swarm-drone-card',
        isSelected ? 'is-selected' : '',
        isExpanded ? 'is-expanded' : '',
        isDirty ? 'is-dirty' : '',
        drone.hasWarnings ? 'has-warnings' : '',
      ].filter(Boolean).join(' ')}
      onClick={handleCardSelect}
    >
      <button
        type="button"
        className="swarm-drone-card__header"
        onClick={handleToggleExpand}
        aria-expanded={isExpanded}
      >
        <div className="swarm-drone-card__header-main">
          <div className="swarm-drone-card__eyebrow">Smart Swarm Assignment</div>
          <div className="swarm-drone-card__title-row">
            <h3>{drone.title}</h3>
            <span className="swarm-drone-card__slot-pill">{drone.subtitle}</span>
            {drone.alias && drone.alias !== drone.title && (
              <span className="swarm-drone-card__alias-pill">{drone.alias}</span>
            )}
          </div>
          <p className="swarm-drone-card__summary">{drone.roleSummary}</p>
        </div>

        <div className="swarm-drone-card__header-status">
          <span className={`swarm-role-badge ${drone.role}`}>
            {drone.roleLabel}
          </span>
          {drone.isRoleSwap && (
            <span className="swarm-status-pill role-swap">
              <FaExchangeAlt />
              Slot Swap
            </span>
          )}
          {isDirty && (
            <span className="swarm-status-pill staged">
              Staged
            </span>
          )}
          {drone.hasWarnings && (
            <span className="swarm-status-pill attention">
              <FaExclamationTriangle />
              {drone.warnings.length} issue{drone.warnings.length === 1 ? '' : 's'}
            </span>
          )}
          <span className="swarm-drone-card__expand-indicator" aria-hidden="true">
            {isExpanded ? <FaChevronDown /> : <FaChevronRight />}
          </span>
        </div>
      </button>

      {!isExpanded && (
        <div className="swarm-drone-card__meta-grid">
          <div className="swarm-drone-card__meta-item">
            <span className="swarm-drone-card__meta-label">Follow target</span>
            <span className="swarm-drone-card__meta-value">{followTargetText}</span>
          </div>

          <div className="swarm-drone-card__meta-item">
            <span className="swarm-drone-card__meta-label">Offset frame</span>
            <span className="swarm-drone-card__meta-value">{drone.frameLabel}</span>
          </div>

          <div className="swarm-drone-card__meta-item">
            <span className="swarm-drone-card__meta-label">Direct followers</span>
            <span className="swarm-drone-card__meta-value">{followerSummary}</span>
          </div>

          <div className="swarm-drone-card__meta-item span-two">
            <span className="swarm-drone-card__meta-label">Relative offset</span>
            <span className="swarm-drone-card__meta-value">{drone.offsetSummary}</span>
          </div>
        </div>
      )}

      {drone.warnings.length > 0 && (
        <div className="swarm-drone-card__warning-list" role="status">
          {drone.warnings.map((warning) => (
            <div
              key={`${drone.hw_id}-${warning.code}`}
              className={`swarm-drone-card__warning ${warning.severity}`}
            >
              <FaExclamationTriangle />
              <span>{warning.message}</span>
            </div>
          ))}
        </div>
      )}

      {isExpanded && (
        <div
          className="swarm-drone-card__editor"
          onClick={(event) => event.stopPropagation()}
        >
          <div className="swarm-drone-card__editor-grid">
            <label className="swarm-drone-card__field">
              <span className="swarm-drone-card__field-label">
                <FaLink />
                Leader link
              </span>
              <select value={followValue} onChange={handleFollowChange}>
                <option value="0">Independent leader</option>
                {followOptions
                  .filter((option) => option.value !== drone.hw_id)
                  .map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
              </select>
              <small>Follow chains always reference drone hardware IDs, not show slots.</small>
            </label>

            <label className="swarm-drone-card__field">
              <span className="swarm-drone-card__field-label">
                <FaSatelliteDish />
                Offset frame
              </span>
              <select
                value={frameValue}
                onChange={handleFrameChange}
                disabled={isIndependentLeader}
              >
                <option value="ned">Geographic (North / East / Up)</option>
                <option value="body">Leader body (Forward / Right / Up)</option>
              </select>
              <small>{drone.frameDescription}</small>
            </label>
          </div>

          <div className="swarm-drone-card__offset-grid">
            <label className="swarm-drone-card__field">
              <span className="swarm-drone-card__field-label">{drone.axisLabels.x}</span>
              <input
                type="number"
                step="0.1"
                value={draft.offset_x ?? drone.offset_x}
                onChange={handleOffsetChange('offset_x')}
                disabled={isIndependentLeader}
              />
            </label>

            <label className="swarm-drone-card__field">
              <span className="swarm-drone-card__field-label">{drone.axisLabels.y}</span>
              <input
                type="number"
                step="0.1"
                value={draft.offset_y ?? drone.offset_y}
                onChange={handleOffsetChange('offset_y')}
                disabled={isIndependentLeader}
              />
            </label>

            <label className="swarm-drone-card__field">
              <span className="swarm-drone-card__field-label">{drone.axisLabels.z}</span>
              <input
                type="number"
                step="0.1"
                value={draft.offset_z ?? drone.offset_z}
                onChange={handleOffsetChange('offset_z')}
                disabled={isIndependentLeader}
              />
            </label>
          </div>
        </div>
      )}
    </article>
  );
});

export default DroneCard;
