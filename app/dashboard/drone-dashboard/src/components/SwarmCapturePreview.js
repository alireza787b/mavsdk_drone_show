import React, { useState } from 'react';
import SwarmFormationCanvas from './SwarmFormationCanvas';
import useSwarmCaptureLiveView from '../hooks/useSwarmCaptureLiveView';
import { formatFormationDistance } from '../utilities/swarmDesignPresentation';

/** One shared drawing model; captured targets never move with live telemetry. */
export default function SwarmCapturePreview({ request, snapshot, candidate, settings, labels, configData }) {
  const [selectedId, setSelectedId] = useState(settings.leaderId);
  const [viewportCommand, setViewportCommand] = useState({ sequence: 0, action: null });
  const live = useSwarmCaptureLiveView(request.hwIds, snapshot?.reference, request.clusterId);
  const base = snapshot?.observations?.[settings.leaderId];
  const overlays = live.positions.map(point => ({ ...point, north: point.north - (base?.north_m || 0),
    east: point.east - (base?.east_m || 0), up: point.up - (base?.current_up_m || 0) }));
  const entries = candidate?.assignments?.filter(entry => request.hwIds.includes(String(entry.hw_id)));
  const selected = entries?.find(entry => String(entry.hw_id) === selectedId);
  const root = entries?.find(entry => String(entry.follow) === '0');
  const props = { assignments: entries || request.assignments, configData,
    clusterId: root ? String(root.hw_id) : request.clusterId,
    selectedId, onSelect: setSelectedId, readOnly: true, compact: true,
    aircraftLabels: labels, previewHeadings: candidate?.headings || {},
    viewFrame: candidate ? settings.frame : 'ned', viewHeading: candidate?.headings?.[settings.leaderId] || 0,
    showFormation: Boolean(entries), overlayPositions: overlays, linkedViews: true, viewportCommand,
    onViewportCommand: action => setViewportCommand(value => ({ sequence: value.sequence + 1, action })) };
  return <section className="swarm-capture-preview" aria-label="Capture visual preview">
    <div className="swarm-capture-preview__legend">
      <span><i className="is-captured" aria-hidden="true" /> Capture</span>
      <span><i className={live.freshCount === request.hwIds.length ? 'is-live' : 'is-delayed'} aria-hidden="true" />
        {live.loading ? 'Connecting…' : live.freshCount === request.hwIds.length ? 'Live' : 'Delayed'} · {live.freshCount}/{request.hwIds.length}</span>
    </div>
    <div className="swarm-capture-preview__plots">
      {[['top', 'Top'], ['north-up', 'Side']].map(([plane, name]) => <div key={plane}>
        <strong>{name}</strong><SwarmFormationCanvas {...props} plane={plane} labelPolicy={plane === 'top' ? 'all' : 'selection'} />
      </div>)}
    </div>
    {selected && <div className="swarm-capture-preview__selection" aria-live="polite">
      <strong>{labels[selectedId] || `H${selectedId}`}</strong>
      <span>{String(selected.follow) === '0' ? 'Leader' : `→ ${labels[String(selected.follow)] || `H${selected.follow}`}`}</span>
      {String(selected.follow) !== '0' && <span>
        {settings.frame === 'body' ? 'Forward' : 'North'} {formatFormationDistance(selected.offset_x)} ·
        {' '}{settings.frame === 'body' ? 'Right' : 'East'} {formatFormationDistance(selected.offset_y)} ·
        {' '}Above {formatFormationDistance(selected.offset_z)} m
      </span>}
    </div>}
  </section>;
}
