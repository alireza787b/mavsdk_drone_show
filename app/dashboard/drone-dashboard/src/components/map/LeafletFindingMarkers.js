import React from 'react';
import { CircleMarker, Popup, useMapEvents } from 'react-leaflet';
import { toast } from 'react-toastify';

import { createFinding } from '../../services/sarApiService';
import { getFindingPriorityColors } from '../../utilities/plotThemeColors';

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

const FindingClickHandler = ({ markingFinding, missionId, onFindingAdded, onFindingSelect }) => {
  useMapEvents({
    click(event) {
      if (!markingFinding || !missionId) return;

      const { lat, lng } = event.latlng;
      createFinding(missionId, buildDefaultFinding(lat, lng))
        .then((finding) => {
          onFindingAdded?.(finding);
          onFindingSelect?.(finding);
          toast.success('Finding marked');
        })
        .catch(() => {
          toast.error('Failed to mark finding');
        });
    },
  });

  return null;
};

const LeafletFindingMarkers = ({
  findings,
  missionId,
  onFindingAdded,
  markingFinding,
  selectedFindingId,
  onFindingSelect,
}) => {
  const priorityColors = getFindingPriorityColors();

  return (
    <>
      <FindingClickHandler
        markingFinding={markingFinding}
        missionId={missionId}
        onFindingAdded={onFindingAdded}
        onFindingSelect={onFindingSelect}
      />

      {(findings || []).map((finding) => (
        <CircleMarker
          key={finding.id}
          center={[finding.lat, finding.lng]}
          radius={selectedFindingId === finding.id ? 8 : 7}
          pathOptions={{
            color: priorityColors.border,
            fillColor: priorityColors[finding.priority] || priorityColors.medium,
            fillOpacity: 1,
            weight: selectedFindingId === finding.id ? 3 : 2,
          }}
          eventHandlers={{
            click: () => onFindingSelect?.(finding),
          }}
        >
          {selectedFindingId === finding.id ? (
            <Popup onClose={() => onFindingSelect?.(null)}>
              <div className="qs-finding-popup">
                <div className="qs-finding-popup__title">
                  {finding.summary || 'Unreviewed observation'}
                </div>
                <div className="qs-launch-review__chip-row">
                  <span className="qs-inline-chip">{finding.type || 'other'}</span>
                  <span className="qs-inline-chip">{finding.status || 'new'}</span>
                  <span className="qs-inline-chip">{finding.priority || 'medium'}</span>
                </div>
                {finding.notes ? <div>{finding.notes}</div> : null}
              </div>
            </Popup>
          ) : null}
        </CircleMarker>
      ))}
    </>
  );
};

export default LeafletFindingMarkers;
