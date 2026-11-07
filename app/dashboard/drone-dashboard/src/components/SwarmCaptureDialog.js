import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ConfirmDialog, OperatorNotice } from './ui/OperatorPrimitives';
import InfoHint from './InfoHint';
import { previewSwarmCaptureResponse } from '../services/gcsApiService';
import { buildAircraftLabels } from '../utilities/swarmDesignPresentation';
import { deriveSwarmCaptureDraft, swarmCaptureError } from '../utilities/swarmCaptureDraft';
import SwarmCapturePreview from './SwarmCapturePreview';
import '../styles/SwarmCapture.css';

/** A read-only sample preview; only Use capture edits the browser draft. */
function CaptureCluster({ request, configData, onUse, onClose, scopeControl }) {
  const [settings, setSettings] = useState({ leaderId: request.clusterId, frame: request.frame, heightMode: 'keep' });
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const sequence = useRef(0);
  const controller = useRef(null);
  const [snapshot, setSnapshot] = useState(null);
  const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const labels = useMemo(() => buildAircraftLabels(configData), [configData]);
  const candidate = useMemo(() => {
    if (!snapshot) return null;
    try { return deriveSwarmCaptureDraft(request.assignments, snapshot, settings); }
    catch (failure) { return { error: failure.message }; }
  }, [request.assignments, snapshot, settings]);

  const refresh = async () => {
    const attempt = ++sequence.current;
    controller.current?.abort();
    controller.current = new AbortController();
    setBusy(true);
    setError('');
    // Keep the drawing on a failed refresh, but invalidate its Use action.
    setVerified(false);
    try {
      const current = settingsRef.current;
      const { data } = await previewSwarmCaptureResponse({ revision: request.revision,
        assignments: request.assignments, cluster_id: request.clusterId,
        frame: current.frame, height_mode: current.heightMode, leader_hw_id: current.leaderId },
        { signal: controller.current.signal });
      if (sequence.current !== attempt) return;
      if (data?.revision !== request.revision || data?.saved !== false || data?.commands_sent !== false
        || !data?.capture_id || !Number.isFinite(data?.captured_at_ms)) {
        throw new Error('Capture response could not be verified. Refresh before using it.');
      }
      const observedIds = Object.keys(data.observations || {});
      if (observedIds.length !== request.hwIds.length || request.hwIds.some((id) => !observedIds.includes(id))) {
        throw new Error('The complete formation was not captured. Refresh before using it.');
      }
      setSnapshot(data);
      setVerified(true);
    } catch (failure) {
      if (sequence.current === attempt) setError(swarmCaptureError(failure));
    } finally {
      if (sequence.current === attempt) setBusy(false);
    }
  };
  useEffect(() => {
    refresh();
    return () => { sequence.current += 1; controller.current?.abort(); };
    // This component is mounted for one immutable draft/revision request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const change = (field, value) => setSettings((current) => ({ ...current, [field]: value }));
  const ids = request.hwIds;
  const close = () => { sequence.current += 1; controller.current?.abort(); onClose(); };
  const ready = verified && candidate && !candidate.error && !error && !busy;
  const capturedTime = snapshot ? new Date(snapshot.captured_at_ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';
  return <ConfirmDialog open appearance="console" size="wide" title="Capture current spacing"
    confirmLabel="Use capture" cancelLabel="Cancel" busy={busy} allowDismissWhileBusy
    confirmDisabled={!ready} onCancel={close}
    onConfirm={() => ready && onUse(candidate, snapshot, settings)}
    message={<div className="swarm-capture">
      {scopeControl}
      <div className="swarm-capture__status" role="status">
        <strong>{busy ? 'Checking aircraft…' : error ? 'Refresh needed' : snapshot ? `Captured ${capturedTime}` : 'Capture unavailable'}</strong>
        <span>{ids.length} aircraft · Draft only</span>
        <button type="button" className="operator-button operator-button--ghost" disabled={busy} onClick={refresh}>Refresh</button>
      </div>
      <div className="swarm-capture__body">
      <SwarmCapturePreview request={request} snapshot={snapshot} candidate={candidate?.error ? null : candidate}
        settings={settings} labels={labels} configData={configData} />
      <fieldset disabled={busy} className="swarm-capture__settings">
        <label htmlFor="capture-leader">Leader <InfoHint label="Capture leader help" content="Changing leader reverses its path to the previous leader. Other relay branches stay linked. Review the resulting roles below." /></label>
        <select id="capture-leader" value={settings.leaderId} onChange={(event) => change('leaderId', event.target.value)}>
          {ids.map((id) => <option key={id} value={id}>{labels[id] || `H${id}`}</option>)}
        </select>
        <fieldset><legend>Reference <InfoHint content="Geographic (NED) keeps North/East spacing. Leader-relative (Body) rotates spacing with the followed aircraft’s heading. This preview uses captured headings; turning before Start can change target positions." label="Capture reference help" /></legend>
          <label><input type="radio" name="capture-frame" value="ned" checked={settings.frame === 'ned'} onChange={() => change('frame', 'ned')} /> Geographic</label>
          <label><input type="radio" name="capture-frame" value="body" checked={settings.frame === 'body'} onChange={() => change('frame', 'body')} /> Leader-relative</label>
        </fieldset>
        <fieldset><legend>Height <InfoHint content="Keep plan preserves planned relative heights. Same height sets relative heights to zero. Current copies estimated airborne height differences from a common MSL reference; it is not an altitude calibration." label="Capture height help" /></legend>
          <label><input type="radio" name="capture-height" value="keep" checked={settings.heightMode === 'keep'} onChange={() => change('heightMode', 'keep')} /> Keep plan</label>
          <label><input type="radio" name="capture-height" value="level" checked={settings.heightMode === 'level'} onChange={() => change('heightMode', 'level')} /> Same height</label>
          <label><input type="radio" name="capture-height" aria-label="Current" value="current" disabled={snapshot?.current_heights_available !== true}
            checked={settings.heightMode === 'current'} onChange={() => change('heightMode', 'current')} /> Current
            {snapshot?.current_heights_available !== true && <InfoHint label="Current heights availability"
              content={snapshot?.current_heights_reason || 'Current heights require a settled airborne capture. Refresh after all aircraft are hovering.'} />}
          </label>
        </fieldset>
      </fieldset>
      </div>
      {(error || candidate?.error) && <OperatorNotice tone="warning" title="Capture unavailable"><span>{error || candidate.error}</span></OperatorNotice>}
      <p className="swarm-capture__note">Draft only · No flight commands</p>
    </div>} />;
}

/** One-cluster use has no scope selection; multi-cluster capture never merges roots. */
export default function SwarmCaptureDialog({ request, configData, onUse, onClose }) {
  const scopes = request.clusters;
  const labels = useMemo(() => buildAircraftLabels(configData), [configData]);
  const [scopeId, setScopeId] = useState(request.clusterId || (scopes.length === 1 ? scopes[0].clusterId : ''));
  const scope = scopes.find(item => item.clusterId === scopeId);
  const control = scopes.length > 1 ? <label className="swarm-capture__scope">Formation
    <select aria-label="Capture formation" value={scopeId} onChange={event => setScopeId(event.target.value)}>
      <option value="" disabled>Select formation</option>
      {scopes.map(item => <option key={item.clusterId} value={item.clusterId}>
        {labels[item.clusterId] || `H${item.clusterId}`} · {item.hwIds.length} aircraft</option>)}
    </select>
  </label> : null;
  if (!scope) return <ConfirmDialog open appearance="console" title="Capture current spacing"
    confirmLabel="Use capture" confirmDisabled onCancel={onClose} onConfirm={() => {}}
    message={control || <p>No formation with followers is available.</p>} />;
  return <CaptureCluster key={scope.clusterId} request={{ ...request, ...scope }} configData={configData}
    scopeControl={control} onUse={onUse} onClose={onClose} />;
}
