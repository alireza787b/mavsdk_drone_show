import React, { useCallback } from 'react';
import { toast } from 'react-toastify';

import { createFinding } from '../../services/sarApiService';

let Marker;
let Popup;
let mapboxAvailable = false;

try {
  const rgl = require('react-map-gl');
  Marker = rgl.Marker;
  Popup = rgl.Popup;
  mapboxAvailable = true;
} catch (error) {
  mapboxAvailable = false;
}

const PRIORITY_COLORS = {
  critical: '#dc3545',
  high: '#fd7e14',
  medium: '#ffc107',
  low: '#00d4ff',
};

const buildDefaultFinding = (lat, lng) => ({
  lat,
  lng,
  summary: 'Unreviewed observation',
  type: 'other',
  priority: 'medium',
  confidence: 'medium',
  source: 'operator_mark',
  status: 'new',
  notes: '',
});

const FindingMarkerSystem = ({
  findings,
  missionId,
  onFindingAdded,
  markingFinding,
  onMapClick,
  selectedFindingId,
  onFindingSelect,
}) => {
  const handleMapClick = useCallback(async (event) => {
    if (!markingFinding || !missionId) return;

    const { lng, lat } = event.lngLat;
    try {
      const finding = await createFinding(missionId, buildDefaultFinding(lat, lng));
      onFindingAdded?.(finding);
      onFindingSelect?.(finding);
      toast.success('Finding marked');
    } catch (error) {
      toast.error('Failed to mark finding');
    }
  }, [markingFinding, missionId, onFindingAdded, onFindingSelect]);

  if (onMapClick) {
    onMapClick.current = handleMapClick;
  }

  if (!mapboxAvailable || !findings || findings.length === 0) {
    return null;
  }

  const selectedFinding = findings.find((finding) => finding.id === selectedFindingId) || null;

  return (
    <>
      {findings.map((finding) => (
        <Marker
          key={finding.id}
          latitude={finding.lat}
          longitude={finding.lng}
          anchor="center"
          onClick={(event) => {
            event.originalEvent.stopPropagation();
            onFindingSelect?.(finding);
          }}
        >
          <div
            className={`qs-finding-marker ${selectedFindingId === finding.id ? 'selected' : ''}`}
            style={{
              background: PRIORITY_COLORS[finding.priority] || PRIORITY_COLORS.medium,
            }}
          />
        </Marker>
      ))}

      {selectedFinding ? (
        <Popup
          latitude={selectedFinding.lat}
          longitude={selectedFinding.lng}
          anchor="bottom"
          onClose={() => onFindingSelect?.(null)}
          closeOnClick={false}
        >
          <div className="qs-finding-popup">
            <div className="qs-finding-popup__title">
              {selectedFinding.summary || 'Unreviewed observation'}
            </div>
            <div className="qs-launch-review__chip-row">
              <span className="qs-inline-chip">{selectedFinding.type || 'other'}</span>
              <span className="qs-inline-chip">{selectedFinding.status || 'new'}</span>
              <span className="qs-inline-chip">{selectedFinding.priority || 'medium'}</span>
            </div>
            {selectedFinding.notes ? <div>{selectedFinding.notes}</div> : null}
          </div>
        </Popup>
      ) : null}
    </>
  );
};

export default FindingMarkerSystem;
