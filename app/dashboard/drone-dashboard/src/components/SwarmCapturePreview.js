import React, { useState } from 'react';
import SwarmCaptureScene from './SwarmCaptureScene';
import useSwarmCaptureLiveView from '../hooks/useSwarmCaptureLiveView';
import { formatFormationDistance } from '../utilities/swarmDesignPresentation';

/** One shared drawing model; captured targets never move with live telemetry. */
export default function SwarmCapturePreview({ request, snapshot, candidate, settings, labels }) {
  const [selectedId, setSelectedId] = useState(settings.leaderId);
  const live = useSwarmCaptureLiveView(request.hwIds, snapshot?.reference, request.clusterId);
  const base = snapshot?.observations?.[settings.leaderId];
  const overlays = live.positions.map(point => ({ ...point, north: point.north - (base?.north_m || 0),
    east: point.east - (base?.east_m || 0), up: point.up - (base?.current_up_m || 0) }));
  const entries = candidate?.assignments?.filter(entry => request.hwIds.includes(String(entry.hw_id)));
  const selected = entries?.find(entry => String(entry.hw_id) === selectedId);
  const root = entries?.find(entry => String(entry.follow) === '0');
  const selectedObservation = snapshot?.observations?.[selectedId];
  const rootObservation = snapshot?.observations?.[String(root?.hw_id)];
  const heightField = settings.heightMode === 'current' ? 'current_up_m' : 'planned_up_m';
  const heightDifference = selectedObservation && rootObservation
    && Number.isFinite(Number(selectedObservation[heightField]))
    && Number.isFinite(Number(rootObservation[heightField]))
    ? Number(selectedObservation[heightField]) - Number(rootObservation[heightField]) : null;
  return <section className="swarm-capture-preview" aria-label="Capture visual preview">
    <div className="swarm-capture-preview__legend">
      <span><i className="is-captured" aria-hidden="true" /> Capture</span>
      <span><i className={live.freshCount === request.hwIds.length ? 'is-live' : 'is-delayed'} aria-hidden="true" />
        {live.loading ? 'Connecting…' : live.freshCount === request.hwIds.length ? 'Live' : 'Delayed'} · {live.freshCount}/{request.hwIds.length}</span>
    </div>
    <SwarmCaptureScene entries={entries || []} headings={candidate?.headings || {}} overlays={overlays}
      labels={labels} selectedId={selectedId} onSelect={setSelectedId}
      frame={candidate ? settings.frame : 'ned'} heading={candidate?.headings?.[settings.leaderId] || 0}
      heightReference={settings.heightMode === 'current' ? 'captured PX4 estimate' : 'planned reference'}
      captureId={`${snapshot?.capture_id || ''}:${root?.hw_id || ''}:${settings.frame}:${settings.heightMode || ''}`} />
    {selected && <div className="swarm-capture-preview__selection" aria-live="polite">
      <strong>{labels[selectedId] || `H${selectedId}`}</strong>
      <span>{String(selected.follow) === '0' ? 'Leader' : `→ ${labels[String(selected.follow)] || `H${selected.follow}`}`}</span>
      {String(selected.follow) !== '0' && <span>
        {settings.frame === 'body' ? 'Forward' : 'North'} {formatFormationDistance(selected.offset_x)} ·
        {' '}{settings.frame === 'body' ? 'Right' : 'East'} {formatFormationDistance(selected.offset_y)} ·
        {' '}Above {formatFormationDistance(selected.offset_z)} m
      </span>}
      {selected && <span>Height difference {heightDifference == null ? 'unknown' : `${heightDifference.toFixed(2)} m`}
        {' '}({settings.heightMode === 'current' ? 'captured estimate' : 'planned reference'})</span>}
    </div>}
  </section>;
}
