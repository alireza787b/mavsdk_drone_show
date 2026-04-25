import React from 'react';
import PropTypes from 'prop-types';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faExchangeAlt,
  faExclamationTriangle,
  faPlus,
} from '@fortawesome/free-solid-svg-icons';

import { formatDroneLabel, formatShowSlotLabel } from '../../utilities/missionIdentityUtils';

export default function MissionConfigAlertStack({
  pendingEnrollmentDrones,
  duplicateHwIds,
  duplicatePosIds,
  roleSwaps,
  originStatus,
  onReviewPendingEnrollment,
  onReviewDuplicateHardwareIds,
  onReviewDuplicateSlots,
  onReviewRoleSwaps,
  onReviewOrigin,
}) {
  const shouldShow = (
    duplicateHwIds.length > 0
    || duplicatePosIds.length > 0
    || roleSwaps.length > 0
    || pendingEnrollmentDrones.length > 0
    || (originStatus !== 'ready' && originStatus !== 'checking')
  );

  if (!shouldShow) {
    return null;
  }

  return (
    <div className="mission-config-alert-stack">
      {pendingEnrollmentDrones.length > 0 && (
        <button
          type="button"
          className="mission-config-alert mission-config-alert--info mission-config-alert--actionable"
          onClick={onReviewPendingEnrollment}
        >
          <FontAwesomeIcon icon={faPlus} />
          <div>
            <strong>{pendingEnrollmentDrones.length} detected, not enrolled</strong>
            <span>
              {pendingEnrollmentDrones.slice(0, 3).map((candidate) => formatDroneLabel(candidate.hw_id)).join(' • ')}
              {pendingEnrollmentDrones.length > 3 ? ` • +${pendingEnrollmentDrones.length - 3} more` : ''}
            </span>
          </div>
          <span className="mission-config-alert__action">Review</span>
        </button>
      )}

      {duplicateHwIds.length > 0 && (
        <button
          type="button"
          className="mission-config-alert mission-config-alert--danger mission-config-alert--actionable"
          onClick={onReviewDuplicateHardwareIds}
        >
          <FontAwesomeIcon icon={faExclamationTriangle} />
          <div>
            <strong>{duplicateHwIds.length} duplicate hardware ID{duplicateHwIds.length === 1 ? '' : 's'}</strong>
            <span>
              {duplicateHwIds.map((duplicate) => formatDroneLabel(duplicate.hw_id)).join(', ')}
            </span>
          </div>
          <span className="mission-config-alert__action">Review</span>
        </button>
      )}

      {duplicatePosIds.length > 0 && (
        <button
          type="button"
          className="mission-config-alert mission-config-alert--danger mission-config-alert--actionable"
          onClick={onReviewDuplicateSlots}
        >
          <FontAwesomeIcon icon={faExclamationTriangle} />
          <div>
            <strong>{duplicatePosIds.length} slot collision{duplicatePosIds.length === 1 ? '' : 's'}</strong>
            <span>
              {duplicatePosIds.map((duplicate) => (
                `${formatShowSlotLabel(duplicate.pos_id)} -> ${duplicate.hw_ids.map((hwId) => formatDroneLabel(hwId)).join(', ')}`
              )).join(' • ')}
            </span>
          </div>
          <span className="mission-config-alert__action">Review</span>
        </button>
      )}

      {roleSwaps.length > 0 && (
        <button
          type="button"
          className="mission-config-alert mission-config-alert--info mission-config-alert--actionable"
          onClick={onReviewRoleSwaps}
        >
          <FontAwesomeIcon icon={faExchangeAlt} />
          <div>
            <strong>{roleSwaps.length} slot reassignment{roleSwaps.length === 1 ? '' : 's'} active</strong>
            <span>
              {roleSwaps.slice(0, 3).map((drone) => (
                `${formatDroneLabel(drone.hw_id)} -> ${formatShowSlotLabel(drone.pos_id)}`
              )).join(' • ')}
              {roleSwaps.length > 0 ? ' • Smart Swarm follow-links stay on hardware IDs.' : ''}
            </span>
          </div>
          <span className="mission-config-alert__action">{roleSwaps.length > 3 ? 'View all' : 'Review'}</span>
        </button>
      )}

      {(originStatus === 'needed' || originStatus === 'unavailable') && (
        <button
          type="button"
          className="mission-config-alert mission-config-alert--warning mission-config-alert--actionable"
          onClick={onReviewOrigin}
        >
          <FontAwesomeIcon icon={faExclamationTriangle} />
          <div>
            <strong>{originStatus === 'unavailable' ? 'Origin check failed' : 'Origin needed'}</strong>
            <span>
              {originStatus === 'unavailable'
                ? 'Could not confirm the current origin. Open origin tools to review.'
                : 'Set the origin before using deviation-based launch review.'}
            </span>
          </div>
          <span className="mission-config-alert__action">{originStatus === 'unavailable' ? 'Review' : 'Set origin'}</span>
        </button>
      )}
    </div>
  );
}

MissionConfigAlertStack.propTypes = {
  pendingEnrollmentDrones: PropTypes.arrayOf(PropTypes.shape({
    hw_id: PropTypes.string,
  })).isRequired,
  duplicateHwIds: PropTypes.arrayOf(PropTypes.shape({
    hw_id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  })).isRequired,
  duplicatePosIds: PropTypes.arrayOf(PropTypes.shape({
    pos_id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    hw_ids: PropTypes.arrayOf(PropTypes.oneOfType([PropTypes.string, PropTypes.number])),
  })).isRequired,
  roleSwaps: PropTypes.arrayOf(PropTypes.shape({
    hw_id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    pos_id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  })).isRequired,
  originStatus: PropTypes.string.isRequired,
  onReviewPendingEnrollment: PropTypes.func.isRequired,
  onReviewDuplicateHardwareIds: PropTypes.func.isRequired,
  onReviewDuplicateSlots: PropTypes.func.isRequired,
  onReviewRoleSwaps: PropTypes.func.isRequired,
  onReviewOrigin: PropTypes.func.isRequired,
};
