import React, { useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { FaSyncAlt } from 'react-icons/fa';

import MapSelector from './MapSelector';
import useComputeOrigin from '../hooks/useComputeOrigin';
import { extractApiErrorMessage } from '../services/apiError';
import { normalizeComparableId } from '../utilities/missionIdentityUtils';
import {
  candidateMatchesDrone,
  describeOriginReference,
} from '../utilities/originReference';
import '../styles/OriginModal.css';

function validatedCoordinates(value) {
  const lat = Number(value?.lat);
  const lon = Number(value?.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return { lat, lon };
}

/**
 * Review and persist the formation origin.
 *
 * Drone-reference previews and writes send hardware identity only. The GCS
 * resolves slot ownership and validates a fresh PX4 global-position snapshot.
 */
const OriginModal = ({
  isOpen,
  onClose,
  onSubmit,
  telemetryData,
  configData,
  currentOrigin,
}) => {
  const [coordinateInput, setCoordinateInput] = useState('');
  const [selectedLatLon, setSelectedLatLon] = useState(null);
  const [originMethod, setOriginMethod] = useState('manual');
  const [selectedDroneId, setSelectedDroneId] = useState('');
  const [altitude, setAltitude] = useState('');
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  const {
    origin,
    error,
    loading,
    computeOrigin,
    resetOrigin,
  } = useComputeOrigin();

  const selectedDrone = useMemo(() => {
    const selectedId = normalizeComparableId(selectedDroneId);
    return configData.find(
      (drone) => normalizeComparableId(drone.hw_id) === selectedId
    ) || null;
  }, [configData, selectedDroneId]);
  const selectedReferenceStatus = useMemo(
    () => describeOriginReference(telemetryData, selectedDroneId),
    [selectedDroneId, telemetryData]
  );
  const hasMatchingCandidate = candidateMatchesDrone(origin, selectedDroneId);

  useEffect(() => {
    if (!isOpen) return;

    const existingCoordinates = validatedCoordinates(currentOrigin);
    if (existingCoordinates) {
      setCoordinateInput(`${existingCoordinates.lat}, ${existingCoordinates.lon}`);
      setSelectedLatLon(existingCoordinates);
      setAltitude(
        currentOrigin?.alt !== undefined && currentOrigin?.alt !== null
          ? String(currentOrigin.alt)
          : ''
      );
    } else {
      setCoordinateInput('');
      setSelectedLatLon(null);
      setAltitude('');
    }

    setOriginMethod('manual');
    setSelectedDroneId('');
    setErrors({});
    setSaving(false);
    resetOrigin();
  }, [currentOrigin, isOpen, resetOrigin]);

  useEffect(() => {
    if (selectedLatLon) {
      setCoordinateInput(`${selectedLatLon.lat}, ${selectedLatLon.lon}`);
    }
  }, [selectedLatLon]);

  useEffect(() => {
    if (originMethod !== 'drone' || !selectedDroneId) return;
    if (!selectedDrone) {
      setErrors({ drone: 'Selected drone was not found in Mission Config.' });
      return;
    }
    computeOrigin({ hw_id: normalizeComparableId(selectedDrone.hw_id) });
  }, [computeOrigin, originMethod, selectedDrone, selectedDroneId]);

  const validateManualInput = () => {
    const coordinatePattern = /^-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?$/;
    if (coordinatePattern.test(coordinateInput.trim())) {
      const [lat, lon] = coordinateInput.trim().split(',').map(Number);
      const validated = validatedCoordinates({ lat, lon });
      if (validated) return validated;
    }
    setErrors({
      input: 'Enter decimal latitude and longitude within valid ranges, for example “35.4079, 50.1649”.',
    });
    return null;
  };

  const handleRetryCompute = () => {
    if (!selectedDrone) {
      setErrors({ drone: 'Select a configured drone before retrying.' });
      return;
    }
    setErrors({});
    computeOrigin({ hw_id: normalizeComparableId(selectedDrone.hw_id) });
  };

  const handleSubmit = async () => {
    let request;
    if (originMethod === 'manual') {
      const coordinates = validatedCoordinates(selectedLatLon) || validateManualInput();
      if (!coordinates) return;

      const altitudeMsl = altitude.trim() === '' ? 0 : Number(altitude);
      if (!Number.isFinite(altitudeMsl)) {
        setErrors({ input: 'Altitude MSL must be a finite number.' });
        return;
      }
      request = {
        method: 'manual',
        lat: coordinates.lat,
        lon: coordinates.lon,
        alt: altitudeMsl,
      };
    } else {
      if (!selectedDroneId || !hasMatchingCandidate) {
        setErrors({ drone: 'Compute a current preview for the selected drone before saving.' });
        return;
      }
      request = {
        method: 'drone_reference',
        hw_id: normalizeComparableId(selectedDroneId),
      };
    }

    setSaving(true);
    setErrors({});
    try {
      await onSubmit(request);
    } catch (submitError) {
      setErrors({
        submit: await extractApiErrorMessage(submitError, 'Failed to save formation origin.'),
      });
    } finally {
      setSaving(false);
    }
  };

  const handleInputChange = (event) => {
    setCoordinateInput(event.target.value);
    setSelectedLatLon(null);
    setErrors({});
  };

  if (!isOpen) return null;

  return (
    <div
      className="origin-modal-overlay"
      onClick={() => { if (!saving) onClose(); }}
    >
      <div className="origin-modal" onClick={(event) => event.stopPropagation()}>
        <h3>Set Formation Origin</h3>

        <div className="origin-method-selection">
          <button
            className={`method-button ${originMethod === 'manual' ? 'active' : ''}`}
            onClick={() => {
              setOriginMethod('manual');
              setErrors({});
            }}
            disabled={saving}
          >
            Enter Coordinates Manually
          </button>
          <button
            className={`method-button ${originMethod === 'drone' ? 'active' : ''}`}
            onClick={() => {
              setOriginMethod('drone');
              setErrors({});
            }}
            disabled={saving}
          >
            Use Drone as Reference
          </button>
        </div>

        {originMethod === 'manual' && (
          <div className="manual-entry">
            <label>
              Coordinates (lat, lon):
              <input
                type="text"
                value={coordinateInput}
                onChange={handleInputChange}
                placeholder='e.g., "35.4079, 50.1649"'
                disabled={saving}
              />
            </label>
            {errors.input && <span className="error-message">{errors.input}</span>}

            <label className="manual-entry__altitude-label">
              Altitude MSL (meters):
              <input
                type="number"
                step="0.1"
                value={altitude}
                onChange={(event) => setAltitude(event.target.value)}
                placeholder="0.0"
                disabled={saving}
              />
            </label>
            <small className="help-text">
              Use absolute altitude above mean sea level. Blank means 0 m MSL.
            </small>

            <p className="or-text">OR</p>
            <MapSelector
              onSelect={setSelectedLatLon}
              initialPosition={selectedLatLon}
            />
          </div>
        )}

        {originMethod === 'drone' && (
          <div className="drone-reference">
            <label>
              Select Drone:
              <select
                value={selectedDroneId}
                onChange={(event) => {
                  setSelectedDroneId(event.target.value);
                  setErrors({});
                  resetOrigin();
                }}
                disabled={saving}
              >
                <option value="">-- Select Drone --</option>
                {configData.map((drone) => {
                  const status = describeOriginReference(telemetryData, drone.hw_id);
                  return (
                    <option key={drone.hw_id} value={normalizeComparableId(drone.hw_id)}>
                      Position {drone.pos_id} (HW {drone.hw_id}) — {status.label}
                    </option>
                  );
                })}
              </select>
            </label>

            {errors.drone && <span className="error-message">{errors.drone}</span>}
            {selectedDroneId && (
              <p className={selectedReferenceStatus.eligible ? 'reference-status ready' : 'reference-status pending'}>
                <strong>{selectedReferenceStatus.label}.</strong> {selectedReferenceStatus.detail}
              </p>
            )}
            {loading && <p className="loading-text">Computing origin preview...</p>}
            {error && <span className="error-message">{error}</span>}

            {hasMatchingCandidate && (
              <div className="computed-origin">
                <p><strong>Computed Origin</strong></p>
                <p>Latitude: {origin.origin.lat.toFixed(8)}</p>
                <p>Longitude: {origin.origin.lon.toFixed(8)}</p>
                <p>Altitude: {origin.origin.alt.toFixed(1)} m MSL</p>
                <p>Reference: HW {origin.reference.hw_id}, Position {origin.reference.pos_id}</p>
                <p>PX4 global sample: {(origin.reference.position_age_ms / 1000).toFixed(1)}s old</p>
              </div>
            )}

            {selectedDroneId && (
              <button
                className="retry-button"
                onClick={handleRetryCompute}
                disabled={loading || saving}
              >
                <FaSyncAlt />
                Retry with latest telemetry
              </button>
            )}
          </div>
        )}

        <div className="modal-actions">
          {errors.submit && <span className="error-message">{errors.submit}</span>}
          <button
            onClick={handleSubmit}
            className="ok-button"
            disabled={loading || saving || (originMethod === 'drone' && !hasMatchingCandidate)}
          >
            {saving ? 'Saving...' : 'Set Origin'}
          </button>
          <button onClick={onClose} className="cancel-button" disabled={loading || saving}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

OriginModal.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onSubmit: PropTypes.func.isRequired,
  telemetryData: PropTypes.object.isRequired,
  configData: PropTypes.array.isRequired,
  currentOrigin: PropTypes.shape({
    lat: PropTypes.number,
    lon: PropTypes.number,
    alt: PropTypes.number,
    source: PropTypes.string,
  }),
};

export default OriginModal;
