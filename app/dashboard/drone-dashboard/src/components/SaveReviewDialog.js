// src/components/SaveReviewDialog.js

import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faCheckCircle,
  faTimesCircle,
  faExclamationTriangle,
  faExchangeAlt,
  faInfoCircle
} from '@fortawesome/free-solid-svg-icons';
import '../styles/SaveReviewDialog.css';

/**
 * SaveReviewDialog Component
 *
 * A comprehensive review dialog shown before saving config changes.
 * Displays validation warnings, changes summary, and requires acknowledgment for risky operations.
 *
 * Props:
 * - isOpen (bool): Controls visibility
 * - validationReport (object): Report from /validate-config endpoint
 * - onConfirm (func): Handler for confirmed save
 * - onCancel (func): Handler for cancel
 */
const SaveReviewDialog = ({ isOpen, validationReport, onConfirm, onCancel }) => {
  const [duplicateAcknowledged, setDuplicateAcknowledged] = useState(false);

  if (!isOpen || !validationReport) return null;

  const { warnings, changes, summary } = validationReport;
  const hasDuplicates = warnings.duplicates && warnings.duplicates.length > 0;
  const hasMissingTrajectories = warnings.missing_trajectories && warnings.missing_trajectories.length > 0;
  const hasRoleSwaps = warnings.role_swaps && warnings.role_swaps.length > 0;
  const hasChanges = changes.pos_id_changes.length > 0;

  // Disable confirm button if duplicates exist and not acknowledged, or if missing trajectories
  const canConfirm = (!hasDuplicates || duplicateAcknowledged) && !hasMissingTrajectories;

  const handleConfirm = () => {
    if (canConfirm) {
      onConfirm();
      setDuplicateAcknowledged(false); // Reset for next time
    }
  };

  const handleCancel = () => {
    setDuplicateAcknowledged(false); // Reset for next time
    onCancel();
  };

  return (
    <>
      {/* Overlay */}
      <div className="save-review-overlay" aria-hidden="true"></div>

      {/* Dialog */}
      <div
        className="save-review-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="save-review-dialog-title"
      >
        <h3 id="save-review-dialog-title">
          <FontAwesomeIcon icon={faInfoCircle} /> Review Configuration Changes
        </h3>

        {/* Missing Trajectories - BLOCKING ERROR */}
        {hasMissingTrajectories && (
          <div className="review-section error-section">
            <h4>
              <FontAwesomeIcon icon={faTimesCircle} /> Missing Trajectory Files
            </h4>
            <p className="error-text">
              Cannot save: The following drones have pos_id values without corresponding trajectory files:
            </p>
            <ul className="error-list">
              {warnings.missing_trajectories.map((item, idx) => (
                <li key={idx}>
                  <strong>Drone {item.hw_id}</strong> → pos_id {item.pos_id}: {item.message}
                </li>
              ))}
            </ul>
            <p className="error-hint">
              Please upload a drone show with trajectory files for these positions, or change the pos_id values.
            </p>
          </div>
        )}

        {/* Duplicate pos_id - WARNING (not blocking) */}
        {hasDuplicates && (
          <div className="review-section warning-section">
            <h4>
              <FontAwesomeIcon icon={faExclamationTriangle} /> COLLISION RISK: Duplicate Position IDs
            </h4>
            <p className="warning-text">
              Multiple drones are assigned the same pos_id! They will fly IDENTICAL trajectories and COLLIDE!
            </p>
            <ul className="warning-list">
              {warnings.duplicates.map((dup, idx) => (
                <li key={idx}>
                  <strong>pos_id {dup.pos_id}</strong> assigned to drones: {dup.hw_ids.join(', ')}
                </li>
              ))}
            </ul>
            <div className="acknowledgment-checkbox">
              <input
                type="checkbox"
                id="duplicate-ack"
                checked={duplicateAcknowledged}
                onChange={(e) => setDuplicateAcknowledged(e.target.checked)}
              />
              <label htmlFor="duplicate-ack">
                I understand the collision risk and want to proceed (for testing only)
              </label>
            </div>
          </div>
        )}

        {/* Role Swaps - INFO */}
        {hasRoleSwaps && (
          <div className="review-section info-section">
            <h4>
              <FontAwesomeIcon icon={faExchangeAlt} /> Active Role Swaps
            </h4>
            <p>The following drones will fly different positions' trajectories:</p>
            <ul className="info-list">
              {warnings.role_swaps.map((swap, idx) => (
                <li key={idx}>
                  Drone <strong>{swap.hw_id}</strong> → will fly Position <strong>{swap.pos_id}</strong>'s show
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* pos_id Changes */}
        {changes.pos_id_changes.length > 0 && (
          <div className="review-section changes-section">
            <h4>Position ID Changes ({changes.pos_id_changes.length})</h4>
            <p className="info-hint">
              <FontAwesomeIcon icon={faInfoCircle} />
              {' '}Position coordinates come from trajectory CSV files (single source of truth)
            </p>
            <table className="changes-table">
              <thead>
                <tr>
                  <th>Drone (hw_id)</th>
                  <th>Old pos_id</th>
                  <th></th>
                  <th>New pos_id</th>
                </tr>
              </thead>
              <tbody>
                {changes.pos_id_changes.map((change, idx) => (
                  <tr key={idx}>
                    <td><strong>{change.hw_id}</strong></td>
                    <td>{change.old_pos_id}</td>
                    <td>→</td>
                    <td><strong>{change.new_pos_id}</strong></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* No Changes */}
        {!hasChanges && (
          <div className="review-section info-section">
            <p>
              <FontAwesomeIcon icon={faInfoCircle} /> No changes detected. Configuration is already up to date.
            </p>
          </div>
        )}

        {/* Summary */}
        <div className="review-summary">
          <strong>Summary:</strong> {summary.total_drones} drones,
          {' '}{summary.pos_id_changes_count} position changes
          {summary.duplicates_count > 0 && (
            <span className="summary-warning">
              , <FontAwesomeIcon icon={faExclamationTriangle} /> {summary.duplicates_count} duplicates
            </span>
          )}
        </div>

        {/* Action Buttons */}
        <div className="review-buttons">
          <button
            className="cancel-button"
            onClick={handleCancel}
            aria-label="Cancel"
          >
            <FontAwesomeIcon icon={faTimesCircle} /> Cancel
          </button>
          <button
            className={`confirm-button ${!canConfirm ? 'disabled' : ''}`}
            onClick={handleConfirm}
            disabled={!canConfirm}
            aria-label="Confirm and Save"
            title={
              hasMissingTrajectories
                ? "Cannot save: Missing trajectory files"
                : hasDuplicates && !duplicateAcknowledged
                  ? "Please acknowledge collision risk to proceed"
                  : "Save configuration"
            }
          >
            <FontAwesomeIcon icon={faCheckCircle} />
            {hasMissingTrajectories ? 'Cannot Save' : 'Confirm & Save'}
          </button>
        </div>
      </div>
    </>
  );
};

SaveReviewDialog.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  validationReport: PropTypes.shape({
    warnings: PropTypes.shape({
      duplicates: PropTypes.array,
      missing_trajectories: PropTypes.array,
      role_swaps: PropTypes.array
    }),
    changes: PropTypes.shape({
      pos_id_changes: PropTypes.array
    }),
    summary: PropTypes.shape({
      total_drones: PropTypes.number,
      pos_id_changes_count: PropTypes.number,
      duplicates_count: PropTypes.number,
      missing_trajectories_count: PropTypes.number,
      role_swaps_count: PropTypes.number
    })
  }),
  onConfirm: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

export default SaveReviewDialog;
