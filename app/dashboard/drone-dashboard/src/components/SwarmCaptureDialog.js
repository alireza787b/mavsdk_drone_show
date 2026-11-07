import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ConfirmDialog, OperatorNotice } from './ui/OperatorPrimitives';
import InfoHint from './InfoHint';
import { previewSwarmCaptureResponse } from '../services/gcsApiService';
import { buildAircraftLabels, formatFormationDistance } from '../utilities/swarmDesignPresentation';
import { deriveSwarmCaptureDraft, swarmCaptureError } from '../utilities/swarmCaptureDraft';
import '../styles/SwarmCapture.css';

/** A read-only sample preview; only Use capture edits the browser draft. */
export default function SwarmCaptureDialog({ request, configData, onUse, onClose }) {
  const [settings, setSettings] = useState({ leaderId: request.clusterId, frame: request.frame, heightMode: 'keep' });
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const sequence = useRef(0);
  const [snapshot, setSnapshot] = useState(null);
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
    setBusy(true);
    setError('');
    // A failed refresh must not leave an older sample looking newly captured.
    setSnapshot(null);
    try {
      const current = settingsRef.current;
      const { data } = await previewSwarmCaptureResponse({ revision: request.revision,
        assignments: request.assignments, cluster_id: request.clusterId,
        frame: current.frame, height_mode: current.heightMode, leader_hw_id: current.leaderId });
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
    } catch (failure) {
      if (sequence.current === attempt) setError(swarmCaptureError(failure));
    } finally {
      if (sequence.current === attempt) setBusy(false);
    }
  };
  useEffect(() => {
    refresh();
    return () => { sequence.current += 1; };
    // This component is mounted for one immutable draft/revision request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const change = (field, value) => setSettings((current) => ({ ...current, [field]: value }));
  const ids = request.hwIds;
  const close = () => { sequence.current += 1; onClose(); };
  const ready = candidate && !candidate.error && !error && !busy;
  const capturedTime = snapshot ? new Date(snapshot.captured_at_ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';
  return <ConfirmDialog open appearance="console" title="Capture current spacing"
    confirmLabel="Use capture" cancelLabel="Cancel" busy={busy} allowDismissWhileBusy
    confirmDisabled={!ready} onCancel={close}
    onConfirm={() => ready && onUse(candidate, snapshot, settings)}
    message={<div className="swarm-capture">
      <div className="swarm-capture__status" role="status">
        <strong>{busy ? 'Checking aircraft…' : snapshot ? `Captured ${capturedTime}` : 'Capture unavailable'}</strong>
        <span>{ids.length} aircraft · Draft only</span>
        <button type="button" className="operator-button operator-button--ghost" disabled={busy} onClick={refresh}>Refresh</button>
      </div>
      <fieldset disabled={busy} className="swarm-capture__settings">
        <label htmlFor="capture-leader">Leader <InfoHint label="Capture leader help" content="Changing leader reverses its path to the previous leader. Other relay branches stay linked. Review the resulting roles below." /></label>
        <select id="capture-leader" value={settings.leaderId} onChange={(event) => change('leaderId', event.target.value)}>
          {ids.map((id) => <option key={id} value={id}>{labels[id] || `H${id}`}</option>)}
        </select>
        <fieldset><legend>Reference <InfoHint content="NED keeps North/East spacing. Body rotates spacing with the followed aircraft’s heading. This preview uses captured headings; turning before Start can change target positions." label="Capture reference help" /></legend>
          <label><input type="radio" name="capture-frame" value="ned" checked={settings.frame === 'ned'} onChange={() => change('frame', 'ned')} /> NED</label>
          <label><input type="radio" name="capture-frame" value="body" checked={settings.frame === 'body'} onChange={() => change('frame', 'body')} /> Body</label>
        </fieldset>
        <fieldset><legend>Height <InfoHint content="Keep plan preserves the draft’s relative heights. Same height sets all captured aircraft to their leader’s height when following. Ground or hover altitude is never copied." label="Capture height help" /></legend>
          <label><input type="radio" name="capture-height" value="keep" checked={settings.heightMode === 'keep'} onChange={() => change('heightMode', 'keep')} /> Keep plan</label>
          <label><input type="radio" name="capture-height" value="level" checked={settings.heightMode === 'level'} onChange={() => change('heightMode', 'level')} /> Same height</label>
        </fieldset>
      </fieldset>
      {(error || candidate?.error) && <OperatorNotice tone="warning" title="Capture unavailable"><span>{error || candidate.error}</span></OperatorNotice>}
      {ready && <ul className="swarm-capture__aircraft" aria-label="Captured aircraft roles">
        {candidate.assignments.filter((entry) => ids.includes(String(entry.hw_id))).map((entry) => {
          const id = String(entry.hw_id);
          const root = String(entry.follow) === '0';
          const relay = candidate.assignments.some((other) => String(other.follow) === id);
          return <li key={id}><strong>{labels[id] || `H${id}`}</strong>
            <span>{root ? 'Leader' : `${relay ? 'Relay' : 'Follower'} → ${labels[String(entry.follow)] || `H${entry.follow}`}`}</span>
            {!root && <small>{settings.frame === 'body' ? 'Forward' : 'North'} {formatFormationDistance(entry.offset_x)} · {settings.frame === 'body' ? 'Right' : 'East'} {formatFormationDistance(entry.offset_y)} · Above {formatFormationDistance(entry.offset_z)} m</small>}
          </li>;
        })}
      </ul>}
      <p className="swarm-capture__note">Frozen spacing. Review the draft before Apply; no aircraft commands are sent.</p>
    </div>} />;
}
