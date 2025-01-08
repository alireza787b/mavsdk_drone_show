// src/components/ConfirmationModal.js

import React from 'react';
import PropTypes from 'prop-types';
import '../styles/ConfirmationModal.css'; // Optional external CSS file

/**
 * A reusable ConfirmationModal component.
 * 
 * Props:
 * - isOpen (bool): Whether the modal is visible.
 * - title (string): Optional title text.
 * - message (string or React node): Main message to show in the modal.
 * - confirmLabel (string): Label for the Confirm/Yes button.
 * - cancelLabel (string): Label for the Cancel/No button.
 * - isDanger (bool): If true, styles the confirm button as "danger" (e.g., red).
 * - onConfirm (func): Called when user confirms.
 * - onCancel (func): Called when user cancels or clicks outside.
 */
const ConfirmationModal = ({
  isOpen,
  title,
  message,
  confirmLabel,
  cancelLabel,
  isDanger,
  onConfirm,
  onCancel,
}) => {
  if (!isOpen) {
    return null;
  }

  const handleOverlayClick = (e) => {
    // If user clicks outside the modal content, treat as cancel
    if (e.target.classList.contains('modal-overlay')) {
      onCancel();
    }
  };

  return (
    <div className="modal-overlay" onClick={handleOverlayClick}>
      <div className="modal-content">
        {title && <h3 className="modal-title">{title}</h3>}
        <div className="modal-message">{message}</div>
        <div className="modal-actions">
          <button
            className={`confirm-button ${isDanger ? 'danger' : ''}`}
            onClick={onConfirm}
          >
            {confirmLabel || 'Yes'}
          </button>
          <button className="cancel-button" onClick={onCancel}>
            {cancelLabel || 'No'}
          </button>
        </div>
      </div>
    </div>
  );
};

ConfirmationModal.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  title: PropTypes.string,
  message: PropTypes.oneOfType([PropTypes.string, PropTypes.node]),
  confirmLabel: PropTypes.string,
  cancelLabel: PropTypes.string,
  isDanger: PropTypes.bool,
  onConfirm: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

ConfirmationModal.defaultProps = {
  title: '',
  message: '',
  confirmLabel: 'Yes',
  cancelLabel: 'No',
  isDanger: false,
};

export default ConfirmationModal;
