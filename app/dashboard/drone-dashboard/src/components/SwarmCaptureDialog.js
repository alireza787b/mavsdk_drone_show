import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ConfirmDialog, OperatorNotice } from './ui/OperatorPrimitives';
import InfoHint from './InfoHint';
import { FaCheck, FaCrosshairs, FaGlobe, FaLayerGroup, FaSlidersH } from 'react-icons/fa';
import { previewSwarmCaptureResponse } from '../services/gcsApiService';
import { buildAircraftLabels, formationReferenceLabel } from '../utilities/swarmDesignPresentation';
import { deriveSwarmCaptureDraft, swarmCaptureError } from '../utilities/swarmCaptureDraft';
import SwarmCapturePreview from './SwarmCapturePreview';
import { HeightChoiceSymbol } from './SwarmAircraftSymbol';
import '../styles/SwarmCapture.css';

/** A read-only sample preview; only Use capture edits the browser draft. */
function CaptureCluster({ request, configData, onUse, onClose, scopeControl }) {
  const [settings, setSettings] = useState({ leaderId: request.clusterId, frame: request.frame, heightMode: null });
  const heightExplicit = useRef(false);
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
    try { return deriveSwarmCaptureDraft(request.assignments, snapshot, { ...settings, heightMode: settings.heightMode || 'keep' }); }
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
        frame: current.frame, height_mode: 'keep', leader_hw_id: current.leaderId },
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
      if (!heightExplicit.current) setSettings(value => ({ ...value,
        heightMode: ['level', 'current'].includes(data.recommended_height_mode) ? data.recommended_height_mode : null }));
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

  const change = (field, value) => {
    if (field === 'heightMode') heightExplicit.current = true;
    setSettings((current) => ({ ...current, [field]: value }));
  };
  const ids = request.hwIds;
  const close = () => { sequence.current += 1; controller.current?.abort(); onClose(); };
  const ready = verified && settings.heightMode && candidate && !candidate.error && !error && !busy;
  const capturedTime = snapshot ? new Date(snapshot.captured_at_ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';
  return <ConfirmDialog open appearance="console" size="wide" title="Capture current spacing"
    confirmLabel="Use capture" cancelLabel="Cancel" busy={busy} allowDismissWhileBusy
    confirmDisabled={!ready} onCancel={close}
    onConfirm={() => ready && onUse(candidate, snapshot, settings)}
    message={<div className="swarm-capture">
      {scopeControl}
      <div className="swarm-capture__status" role="status">
        <strong><FaLayerGroup aria-hidden="true" /> {ids.length} aircraft</strong>
        <span>{busy ? 'Checking…' : error ? 'Refresh needed' : snapshot?.flight_state === 'grounded' ? 'Grounded'
          : snapshot?.flight_state === 'airborne' ? 'Airborne' : 'Review height'}</span>
        <InfoHint label="Capture status help" content={snapshot ? `Captured ${capturedTime}. Use capture changes the draft only; Apply plan is separate.` : 'Reading current aircraft positions. No flight commands.'} />
        <button type="button" className="operator-button operator-button--ghost" disabled={busy} onClick={refresh}><FaCrosshairs aria-hidden="true" /> Refresh</button>
      </div>
      <div className="swarm-capture__body">
      <SwarmCapturePreview request={request} snapshot={snapshot} candidate={candidate?.error ? null : candidate}
        settings={settings} labels={labels} configData={configData} />
      </div>
      <fieldset disabled={busy} className="capture-height-choices"><legend>Height <InfoHint content="Same height sets relative heights to zero. Current uses estimated height differences in settled hover. Keep plan retains saved heights. Defaults come from the captured aircraft state, never cached live markers." label="Capture height help" /></legend>
        {[['level', 'Same height'], ['current', 'Current'], ['keep', 'Keep plan']].map(([value, label]) => <label key={value}>
          <input type="radio" name="capture-height" aria-label={label} value={value}
            disabled={value === 'current' && snapshot?.current_heights_available !== true}
            checked={settings.heightMode === value} onChange={() => change('heightMode', value)} />
          <HeightChoiceSymbol mode={value} /><span>{label}</span><FaCheck className="capture-height-choices__check" aria-hidden="true" />
        </label>)}
        {snapshot?.current_heights_available !== true && <InfoHint label="Current heights availability"
          content={snapshot?.current_heights_reason || 'Current requires every aircraft settled airborne. Refresh after hovering.'} />}
      </fieldset>
      {verified && !settings.heightMode && <span className="swarm-capture__choice-needed" role="status">Choose height before continuing.</span>}
      <details className="swarm-capture__adjust"><summary><FaSlidersH aria-hidden="true" /> Adjust formation
        <span>{labels[settings.leaderId] || `H${settings.leaderId}`} · {formationReferenceLabel(settings.frame)}</span></summary>
      <fieldset disabled={busy} className="swarm-capture__settings">
        <label htmlFor="capture-leader">Leader <InfoHint label="Capture leader help" content="Changing leader reverses its path to the previous leader. Other relay branches stay linked. Review the resulting roles below." /></label>
        <select id="capture-leader" value={settings.leaderId} onChange={(event) => change('leaderId', event.target.value)}>
          {ids.map((id) => <option key={id} value={id}>{labels[id] || `H${id}`}</option>)}
        </select>
        <fieldset><legend>Reference <InfoHint content="Geographic (NED) keeps North/East spacing. Leader-relative (Body) rotates spacing with the followed aircraft’s heading. This preview uses captured headings; turning before Start can change target positions." label="Capture reference help" /></legend>
          <label><input type="radio" name="capture-frame" value="ned" checked={settings.frame === 'ned'} onChange={() => change('frame', 'ned')} /> <FaGlobe aria-hidden="true" /> Geographic</label>
          <label><input type="radio" name="capture-frame" value="body" checked={settings.frame === 'body'} onChange={() => change('frame', 'body')} /> <FaCrosshairs aria-hidden="true" /> Leader-relative</label>
        </fieldset>
      </fieldset>
      </details>
      {(error || candidate?.error) && <OperatorNotice tone="warning" title="Capture unavailable"><span>{error || candidate.error}</span></OperatorNotice>}
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
