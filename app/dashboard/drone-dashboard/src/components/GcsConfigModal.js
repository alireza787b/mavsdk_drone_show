import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import '../styles/GcsConfigModal.css';
import { toast } from 'react-toastify';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faExclamationTriangle, faServer } from '@fortawesome/free-solid-svg-icons';

const GcsConfigModal = ({ isOpen, onClose, onSubmit, currentGcsIp }) => {
  const [gcsIp, setGcsIp] = useState('');
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);

  // Initialize modal with current IP
  useEffect(() => {
    if (isOpen && currentGcsIp) {
      setGcsIp(currentGcsIp);
      setErrors({});
    }
  }, [isOpen, currentGcsIp]);

  // Validate IP address format
  const validateIpAddress = (ip) => {
    const ipRegex = /^(\d{1,3}\.){3}\d{1,3}$/;
    if (!ipRegex.test(ip)) {
      return 'Invalid IP format. Expected: XXX.XXX.XXX.XXX';
    }

    const octets = ip.split('.');
    for (const octet of octets) {
      const num = parseInt(octet, 10);
      if (num < 0 || num > 255) {
        return `Invalid octet value: ${num} (must be 0-255)`;
      }
    }

    return null;
  };

  const handleInputChange = (e) => {
    setGcsIp(e.target.value);
    setErrors({});
  };

  const handleSubmit = () => {
    // Validate input
    const validationError = validateIpAddress(gcsIp.trim());
    if (validationError) {
      setErrors({ ip: validationError });
      toast.error(validationError);
      return;
    }

    // Check if IP actually changed
    if (gcsIp.trim() === currentGcsIp) {
      toast.info('No changes made to GCS IP');
      onClose();
      return;
    }

    // Submit new IP
    setLoading(true);
    onSubmit({ gcs_ip: gcsIp.trim() })
      .finally(() => {
        setLoading(false);
      });
  };

  if (!isOpen) return null;

  return (
    <div className="gcs-config-modal-overlay" onClick={onClose}>
      <div className="gcs-config-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <FontAwesomeIcon icon={faServer} className="modal-icon" />
          <h3>Configure GCS IP Address</h3>
        </div>

        <div className="modal-body">
          <label>
            GCS IP Address:
            <input
              type="text"
              value={gcsIp}
              onChange={handleInputChange}
              placeholder="e.g., 192.168.1.100"
              disabled={loading}
            />
          </label>
          {errors.ip && <span className="error-message">{errors.ip}</span>}

          <div className="info-box">
            <p><strong>Current IP:</strong> {currentGcsIp}</p>
          </div>

          <div className="warning-box">
            <FontAwesomeIcon icon={faExclamationTriangle} />
            <div>
              <strong>Important:</strong>
              <ul>
                <li>All drones must be restarted to apply this change</li>
                <li>GCS server must be restarted after save</li>
                <li>Changes will be committed to git repository</li>
                <li>Ensure the new IP is correct before saving</li>
              </ul>
            </div>
          </div>

          <div className="help-box">
            <p><small>
              This IP address is used by all drones for:
              <br/>• Heartbeat reporting
              <br/>• MAVLink routing
              <br/>• Telemetry transmission
              <br/>• Command reception
            </small></p>
            <p><small>
              <strong>Alternative:</strong> You can also edit this directly in <code>src/params.py</code>
            </small></p>
          </div>
        </div>

        <div className="modal-actions">
          <button
            onClick={handleSubmit}
            className="ok-button"
            disabled={loading}
          >
            {loading ? 'Saving...' : 'Save & Commit'}
          </button>
          <button
            onClick={onClose}
            className="cancel-button"
            disabled={loading}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

GcsConfigModal.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onSubmit: PropTypes.func.isRequired,
  currentGcsIp: PropTypes.string.isRequired,
};

export default GcsConfigModal;
