// src/components/ConfirmationDialog.js

import React from 'react';
import PropTypes from 'prop-types';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCheckCircle, faTimesCircle } from '@fortawesome/free-solid-svg-icons';
import '../styles/ConfirmationDialog.css';

/**
 * ConfirmationDialog Component
 * 
 * A reusable modal dialog that prompts the user to confirm or cancel an action.
 * 
 * Props:
 * - isOpen (bool): Controls the visibility of the dialog.
 * - message (string): The confirmation message to display.
 * - onConfirm (func): Handler for the confirm action.
 * - onCancel (func): Handler for the cancel action.
 */
const ConfirmationDialog = ({ isOpen, message, onConfirm, onCancel }) => {
  if (!isOpen) return null;

  return (
    <>
      {/* Overlay */}
      <div className="confirmation-overlay" aria-hidden="true"></div>
      
      {/* Dialog */}
      <div
        className="confirmation-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirmation-dialog-title"
      >
        <h3 id="confirmation-dialog-title">Confirm Action</h3>
        <p>{message}</p>
        <div className="confirmation-buttons">
          <button
            className="confirm-button"
            onClick={onConfirm}
            aria-label="Confirm"
          >
            <FontAwesomeIcon icon={faCheckCircle} /> Confirm
          </button>
          <button
            className="cancel-button"
            onClick={onCancel}
            aria-label="Cancel"
          >
            <FontAwesomeIcon icon={faTimesCircle} /> Cancel
          </button>
        </div>
      </div>
    </>
  );
};

ConfirmationDialog.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  message: PropTypes.string.isRequired,
  onConfirm: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

export default ConfirmationDialog;
