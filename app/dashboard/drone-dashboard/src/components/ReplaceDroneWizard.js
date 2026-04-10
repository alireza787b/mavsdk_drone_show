import React, { useState, useMemo } from 'react';
import PropTypes from 'prop-types';
import '../styles/ReplaceDroneWizard.css';
import {
  formatDroneLabel,
  formatShowSlotLabel,
  getHeartbeatTimestamp,
  normalizeComparableId,
} from '../utilities/missionIdentityUtils';

/**
 * ReplaceDroneWizard — 3-step modal wizard for replacing a failed drone.
 *
 * Step 1: Select the failed drone to replace
 * Step 2: Select or enter the replacement drone's hw_id
 * Step 3: Review summary and confirm
 */
export default function ReplaceDroneWizard({
  isOpen,
  onClose,
  configData,
  heartbeats,
  pendingEnrollmentDrones,
  onSave,
  preselectedHwId,
}) {
  const [step, setStep] = useState(1);
  const [selectedHwId, setSelectedHwId] = useState(normalizeComparableId(preselectedHwId));
  const [newHwId, setNewHwId] = useState('');
  const [newIp, setNewIp] = useState('');
  const [newPort, setNewPort] = useState('');
  const [useManualEntry, setUseManualEntry] = useState(true);

  // Initialize preselected drone on open
  React.useEffect(() => {
    if (isOpen && preselectedHwId) {
      setSelectedHwId(normalizeComparableId(preselectedHwId));
    }
  }, [isOpen, preselectedHwId]);

  // Reset wizard state when modal closes
  React.useEffect(() => {
    if (!isOpen) {
      setStep(1);
      setSelectedHwId(normalizeComparableId(preselectedHwId));
      setNewHwId('');
      setNewIp('');
      setNewPort('');
      setUseManualEntry(true);
    }
  }, [isOpen, preselectedHwId]);

  const pendingCandidates = useMemo(() => (
    Array.isArray(pendingEnrollmentDrones)
      ? pendingEnrollmentDrones.map((candidate) => ({
          hw_id: normalizeComparableId(candidate.hw_id),
          ip: candidate.ip || '',
          port: candidate.mavlink_port || '',
        }))
      : []
  ), [pendingEnrollmentDrones]);

  // Helper: get heartbeat status label for a drone
  const getStatusLabel = (hwId) => {
    const hb = heartbeats[normalizeComparableId(hwId)];
    if (!hb) return 'No heartbeat';
    const timestamp = getHeartbeatTimestamp(hb);
    if (timestamp === null) return 'No heartbeat';
    const ageSec = Math.floor((Date.now() - timestamp) / 1000);
    if (ageSec < 20) return 'Online';
    if (ageSec < 60) return 'Stale';
    return 'Offline';
  };

  const isOffline = (hwId) => {
    const label = getStatusLabel(hwId);
    return label === 'Offline' || label === 'No heartbeat';
  };

  // The drone being replaced
  const failedDrone = configData.find((drone) => normalizeComparableId(drone.hw_id) === normalizeComparableId(selectedHwId));

  // When user selects a spare drone from list
  const handleSelectSpare = (spare) => {
    setNewHwId(normalizeComparableId(spare.hw_id));
    setNewIp(spare.ip);
    setNewPort(spare.port);
    setUseManualEntry(false);
  };

  // Confirm and apply
  const handleConfirm = () => {
    const normalizedSelectedHwId = normalizeComparableId(selectedHwId);
    const normalizedNewHwId = normalizeComparableId(newHwId);

    if (!failedDrone || !normalizedNewHwId) return;

    // Prevent duplicate hw_id conflicts
    const existingDrone = configData.find(
      (drone) =>
        normalizeComparableId(drone.hw_id) === normalizedNewHwId &&
        normalizeComparableId(drone.hw_id) !== normalizedSelectedHwId
    );
    if (existingDrone) {
      alert(`Hardware ID ${normalizedNewHwId} is already assigned to ${formatShowSlotLabel(existingDrone.pos_id)}. Choose a different ID.`);
      return;
    }

    const updatedConfig = configData.map((drone) => {
      if (normalizeComparableId(drone.hw_id) !== normalizedSelectedHwId) return drone;
      return {
        ...drone,
        hw_id: normalizedNewHwId,
        ip: newIp || drone.ip,
        mavlink_port: newPort || drone.mavlink_port,
        // pos_id stays the same — that is the point of replacement
      };
    });

    onSave(updatedConfig);
    onClose();
  };

  // Validation per step
  const canAdvanceStep1 = !!selectedHwId;
  const canAdvanceStep2 = !!newHwId;

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="replace-wizard-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Replace Drone Wizard"
      >
        {/* Step Indicator */}
        <div className="wizard-step-indicator">
          {[1, 2, 3].map((s) => (
            <div key={s} className={`wizard-step ${step === s ? 'active' : ''} ${step > s ? 'completed' : ''}`}>
              <div className="step-circle">{step > s ? '\u2713' : s}</div>
              <span className="step-label">
                {s === 1 && 'Select Failed'}
                {s === 2 && 'Select Replacement'}
                {s === 3 && 'Confirm'}
              </span>
            </div>
          ))}
        </div>

        {/* Step 1: Select Failed Drone */}
        {step === 1 && (
          <div className="wizard-body">
            <h3>Step 1: Select the Failed Drone</h3>
            <p className="wizard-description">
              Choose which drone is being replaced. Offline drones are highlighted.
            </p>
            <div className="drone-select-list">
              {configData.map((drone) => {
                const status = getStatusLabel(drone.hw_id);
                const offline = isOffline(drone.hw_id);
                const selected = normalizeComparableId(selectedHwId) === normalizeComparableId(drone.hw_id);
                return (
                  <div
                    key={drone.hw_id}
                    className={`drone-select-item ${selected ? 'selected' : ''} ${offline ? 'offline-highlight' : ''}`}
                    onClick={() => setSelectedHwId(normalizeComparableId(drone.hw_id))}
                  >
                    <div className="drone-select-info">
                      <strong>{formatShowSlotLabel(drone.pos_id)}</strong> · {formatDroneLabel(drone.hw_id)}
                    </div>
                    <div className={`drone-select-status ${offline ? 'offline' : 'online'}`}>
                      {status}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Step 2: Select Replacement */}
        {step === 2 && (
          <div className="wizard-body">
            <h3>Step 2: Select Replacement Drone</h3>
            <p className="wizard-description">
              Keep the failed drone&apos;s show slot and assign it to another hardware ID.
            </p>

            {/* Option A: Manual Entry */}
            <div className="replacement-section">
              <label className="section-label">
                <input
                  type="radio"
                  checked={useManualEntry}
                  onChange={() => setUseManualEntry(true)}
                />
                Enter new Hardware ID manually
              </label>
              {useManualEntry && (
                <div className="manual-entry-fields">
                  <div className="field-row">
                    <label>Hardware ID</label>
                    <input
                      type="text"
                      value={newHwId}
                      onChange={(e) => setNewHwId(normalizeComparableId(e.target.value))}
                      placeholder="e.g., 42"
                      className="wizard-input"
                    />
                  </div>
                  <div className="field-row">
                    <label>IP Address</label>
                    <input
                      type="text"
                      value={newIp}
                      onChange={(e) => setNewIp(e.target.value)}
                      placeholder={failedDrone?.ip || 'e.g., 192.168.1.100'}
                      className="wizard-input"
                    />
                  </div>
                  <div className="field-row">
                    <label>MAVLink Port</label>
                    <input
                      type="text"
                      value={newPort}
                      onChange={(e) => setNewPort(e.target.value)}
                      placeholder={failedDrone?.mavlink_port || 'e.g., 14560'}
                      className="wizard-input"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Option B: Select from spares */}
            {pendingCandidates.length > 0 && (
              <div className="replacement-section">
                <label className="section-label">
                  <input
                    type="radio"
                    checked={!useManualEntry}
                    onChange={() => setUseManualEntry(false)}
                  />
                  Select from detected standby nodes ({pendingCandidates.length} available)
                </label>
                {!useManualEntry && (
                  <div className="spare-drone-list">
                    {pendingCandidates.map((spare) => (
                      <div
                        key={spare.hw_id}
                        className={`spare-drone-item ${normalizeComparableId(newHwId) === normalizeComparableId(spare.hw_id) ? 'selected' : ''}`}
                        onClick={() => handleSelectSpare(spare)}
                      >
                        <strong>{formatDroneLabel(spare.hw_id)}</strong>
                        {spare.ip && <span className="spare-detail">IP: {spare.ip}</span>}
                        {spare.port && <span className="spare-detail">Port: {spare.port}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Editable fields when spare is selected */}
            {!useManualEntry && newHwId && (
              <div className="manual-entry-fields" style={{ marginTop: '12px' }}>
                <div className="field-row">
                  <label>IP Address</label>
                  <input
                    type="text"
                    value={newIp}
                    onChange={(e) => setNewIp(e.target.value)}
                    className="wizard-input"
                  />
                </div>
                <div className="field-row">
                  <label>MAVLink Port</label>
                  <input
                    type="text"
                    value={newPort}
                    onChange={(e) => setNewPort(e.target.value)}
                    className="wizard-input"
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {/* Step 3: Confirm & Apply */}
        {step === 3 && failedDrone && (
          <div className="wizard-body">
            <h3>Step 3: Confirm Replacement</h3>
            <p className="wizard-description">
              Review the changes below before applying.
            </p>

            <div className="summary-card">
              <div className="summary-row">
                <span className="summary-label">Show slot transferred:</span>
                <span className="summary-value">{formatShowSlotLabel(failedDrone.pos_id)}</span>
              </div>
              <div className="summary-divider" />
              <div className="summary-row">
                <span className="summary-label">From (being replaced):</span>
                <span className="summary-value summary-old">{formatDroneLabel(selectedHwId)}</span>
              </div>
              <div className="summary-row">
                <span className="summary-label">To (replacement):</span>
                <span className="summary-value summary-new">{formatDroneLabel(newHwId)}</span>
              </div>
              <div className="summary-divider" />
              <div className="summary-row">
                <span className="summary-label">IP Address:</span>
                <span className="summary-value">{newIp || failedDrone.ip}</span>
              </div>
              <div className="summary-row">
                <span className="summary-label">MAVLink Port:</span>
                <span className="summary-value">{newPort || failedDrone.mavlink_port}</span>
              </div>
            </div>

            <div className="wizard-note">
              After saving, reboot the replacement drone to apply the new configuration.
            </div>
          </div>
        )}

        {/* Footer Buttons */}
        <div className="wizard-footer">
          <button className="wizard-btn cancel" onClick={onClose}>
            Cancel
          </button>
          <div className="wizard-footer-right">
            {step > 1 && (
              <button className="wizard-btn secondary" onClick={() => setStep(step - 1)}>
                Back
              </button>
            )}
            {step < 3 && (
              <button
                className="wizard-btn primary"
                disabled={step === 1 ? !canAdvanceStep1 : !canAdvanceStep2}
                onClick={() => setStep(step + 1)}
              >
                Next
              </button>
            )}
            {step === 3 && (
              <button className="wizard-btn primary" onClick={handleConfirm}>
                Confirm &amp; Save
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

ReplaceDroneWizard.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  configData: PropTypes.array.isRequired,
  heartbeats: PropTypes.object.isRequired,
  pendingEnrollmentDrones: PropTypes.array,
  onSave: PropTypes.func.isRequired,
  preselectedHwId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
};

ReplaceDroneWizard.defaultProps = {
  pendingEnrollmentDrones: [],
  preselectedHwId: null,
};
