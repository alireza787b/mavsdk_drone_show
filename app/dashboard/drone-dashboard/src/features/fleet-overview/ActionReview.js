import React, { useEffect, useRef, useState } from 'react';
import { ConfirmDialog } from '../../components/ui';
import { useCommandActivity } from '../../contexts/CommandActivityContext';
import { createCommandIdempotencyKey, isAmbiguousSubmissionTransportFailure, serializeCommandSubmission } from '../../services/droneApiService';
import { fetchGcsResource } from '../../services/gcsApiService';
import { submitCommandWithLifecycleFeedback, trackCommandReceipt } from '../../utilities/commandLifecycleFeedback';
import { DRONE_ACTION_TYPES, DRONE_MISSION_TYPES } from '../../constants/droneConstants';

// If storage becomes read-only after acceptance, do not turn a confirmed command
// back into a pending action in this tab. The backend journal remains authority.
const resolvedRequests = new Set();
function removeSavedRequest(key, command) {
  try {
    if (JSON.parse(sessionStorage.getItem(key))?.idempotency_key === command?.idempotency_key) sessionStorage.removeItem(key);
  } catch (_) { /* Storage cleanup must never reinterpret the submission result. */ }
}
function markResolved(key, command) {
  resolvedRequests.add(`${key}:${command.idempotency_key}`);
  if (resolvedRequests.size > 64) resolvedRequests.delete(resolvedRequests.values().next().value);
  removeSavedRequest(key, command);
}

function validTargets(command) {
  return command && !Object.prototype.hasOwnProperty.call(command, 'target_scope')
    && Array.isArray(command.target_drone_ids) && command.target_drone_ids.length > 0
    && command.target_drone_ids.every(id => typeof id === 'string' && id.trim() === id && id.length > 0)
    && new Set(command.target_drone_ids).size === command.target_drone_ids.length;
}

// Scope by native action kind and the exact unordered aircraft set. Parameters
// do not create a bypass for an unresolved request of the same action/scope.
export function buildActionStorageKey(prefix, command) {
  if (typeof prefix !== 'string' || !prefix || !validTargets(command)
    || !Number.isInteger(Number(command.mission_type))) return null;
  return `${prefix}:action:${encodeURIComponent(JSON.stringify([Number(command.mission_type), [...command.target_drone_ids].sort()]))}`;
}

export function readPendingAction(key) {
  try {
    const value = JSON.parse(sessionStorage.getItem(key));
    return value && typeof value.idempotency_key === 'string' && value.idempotency_key
      && Number.isInteger(value.mission_type) && Number.isInteger(value.trigger_time) && value.trigger_time >= 0
      && validTargets(value) && !resolvedRequests.has(`${key}:${value.idempotency_key}`) ? value : null;
  } catch (_) { return null; }
}

export function readPendingActions(prefix) {
  if (typeof prefix !== 'string' || !prefix) return [];
  const pending = [];
  const add = (storageKey) => {
    const command = readPendingAction(storageKey);
    if (command) pending.push({ storageKey, command });
  };
  // Include the former singleton receipt without rewriting or replaying it.
  add(prefix);
  try {
    for (let index = 0; index < Math.min(sessionStorage.length, 512) && pending.length < 64; index += 1) {
      const key = sessionStorage.key(index);
      if (key?.startsWith(`${prefix}:action:`)) add(key);
    }
  } catch (_) { /* Unavailable storage is not permission to submit. */ }
  return pending;
}

export default function ActionReview({ intent, storageKey, aircraft = [], runtimeMode, onClose, onResolved }) {
  const [initialIntent] = useState(() => {
    const saved = readPendingAction(storageKey);
    return saved ? { ...saved, recover: true } : intent;
  });
  const [uncertain, setUncertain] = useState(initialIntent.recover === true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [ack, setAck] = useState({});
  const [reviewContext] = useState(() => ({ storageKey, runtimeMode }));
  const [command] = useState(() => {
    const { recover, ...body } = JSON.parse(JSON.stringify(initialIntent));
    return { ...body, mission_type: Number(body.mission_type), idempotency_key: body.idempotency_key || createCommandIdempotencyKey(),
      target_drone_ids: Array.isArray(body.target_drone_ids) ? [...body.target_drone_ids] : [] };
  });
  const submitted = useRef(initialIntent.recover === true ? command : null);
  const lock = useRef(false), mounted = useRef(true);
  const settled = useRef(false);
  const liveContext = useRef({ storageKey, runtimeMode });
  liveContext.current = { storageKey, runtimeMode };
  const { commandLifecycleCallbacks } = useCommandActivity();
  const test = command.mission_type === DRONE_ACTION_TYPES.TEST;
  const modeKnown = ['real', 'sitl'].includes(reviewContext.runtimeMode);
  const contextMatches = reviewContext.runtimeMode === runtimeMode && reviewContext.storageKey === storageKey;
  const realTest = test && reviewContext.runtimeMode === 'real';
  const safety = !realTest || ['props', 'secured', 'area'].every((key) => ack[key]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const names = command.target_drone_ids.map((id) => aircraft.find((row) => row.id === id)?.label || `Aircraft ${id}`);
  const submit = async () => {
    if (!mounted.current || lock.current || settled.current || !contextMatches || !modeKnown || !validTargets(command) || (!uncertain && !safety)) return;
    lock.current = true; setBusy(true); setError('');
    try {
      let receipt;
      if (uncertain) {
        const { data } = await fetchGcsResource('/api/v1/commands/lookup', { params: { idempotency_key: submitted.current.idempotency_key } });
        receipt = trackCommandReceipt(submitted.current, data, commandLifecycleCallbacks);
      } else {
        // Another open review may have persisted this same action/scope since
        // this dialog opened. Never overwrite its identity or dispatch anew.
        if (readPendingAction(reviewContext.storageKey)) {
          setError('This action already has an unconfirmed receipt. Close and reopen it to check the saved command.');
          return;
        }
        const body = { ...command };
        if (test) body.ground_test_safety = reviewContext.runtimeMode === 'sitl' ? { mode: 'sitl_not_applicable' }
          : { mode: 'operator_acknowledged', props_removed: ack.props === true, airframe_secured: ack.secured === true, area_clear: ack.area === true };
        // The saved intent is the exact sent body. Recovery only looks it up;
        // it never resends an uncertain motor/flight command.
        submitted.current = serializeCommandSubmission(body);
        try {
          const serialized = JSON.stringify(submitted.current);
          sessionStorage.setItem(reviewContext.storageKey, serialized);
          if (sessionStorage.getItem(reviewContext.storageKey) !== serialized) throw new Error('Recovery identity was not saved');
        }
        catch (_) { throw new Error('Command not sent: this browser cannot save its recovery identity. Restore session storage before confirming.'); }
        receipt = await submitCommandWithLifecycleFeedback(submitted.current, commandLifecycleCallbacks);
      }
      if (receipt?.accepted_for_tracking === true && receipt?.command_id) {
        settled.current = true;
        markResolved(reviewContext.storageKey, submitted.current);
        if (mounted.current && liveContext.current.storageKey === reviewContext.storageKey
          && liveContext.current.runtimeMode === reviewContext.runtimeMode) { onResolved(); onClose(); }
      } else {
        throw Object.assign(new Error('Command receipt unconfirmed'), { code: 'COMMAND_RECEIPT_UNCONFIRMED' });
      }
    } catch (exc) {
      if (settled.current) return; // A UI callback failure cannot undo an accepted receipt.
      if (isAmbiguousSubmissionTransportFailure(exc) || uncertain) {
        if (mounted.current) { setUncertain(true); setError('Receipt unconfirmed. Check this saved action before repeating it. Other actions remain separate.'); }
      } else {
        removeSavedRequest(reviewContext.storageKey, submitted.current);
        if (mounted.current) setError(typeof exc?.response?.data?.detail === 'string' ? exc.response.data.detail : exc?.message || 'Command rejected');
      }
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  };
  const close = () => { mounted.current = false; onClose(); };
  return <ConfirmDialog open appearance="console" title={command.uiMeta?.operatorLabel || command.operator_label || 'Review action'}
    tone={command.mission_type === DRONE_ACTION_TYPES.KILL_TERMINATE ? 'danger' : 'neutral'}
    confirmLabel={uncertain ? 'Check command' : `Confirm · ${names.length} aircraft`}
    confirmDisabled={!contextMatches || !modeKnown || !validTargets(command) || (!uncertain && !safety)}
    busy={busy} allowDismissWhileBusy onConfirm={submit} onCancel={close} cancelLabel="Close"
    message={<div className="fleet-action-review">
      <strong>{names.length} aircraft · {String(reviewContext.runtimeMode || 'unknown').toUpperCase()}</strong>
      <ul className="fleet-review-targets">{names.map((name, index) => <li key={command.target_drone_ids[index]}>{name}</li>)}</ul>
      {command.mission_type === DRONE_ACTION_TYPES.RETURN_RTL && <p>Immediate PX4 return. No sequencing or route separation.</p>}
      {command.mission_type === DRONE_ACTION_TYPES.HOLD && <p>Hold position. Replaces the current flight command.</p>}
      {command.mission_type === DRONE_MISSION_TYPES.NONE && <p>Cancel the current mission on these aircraft. Cancellation alone is not verified Hold or landing.</p>}
      {command.mission_type === DRONE_ACTION_TYPES.LAND && <p>Land at each aircraft’s current position.</p>}
      {command.mission_type === DRONE_ACTION_TYPES.HOVER_TEST && <p>Take off, run the hover-test trajectory, then land.</p>}
      {command.mission_type === DRONE_ACTION_TYPES.KILL_TERMINATE && <p>Stop motors immediately. An airborne aircraft will fall.</p>}
      {command.uiMeta?.triggerSummary && <p>{command.uiMeta.triggerSummary}</p>}
      {test && <p>Brief motor-arm test. Motors will arm.</p>}
      {uncertain && <p>Read-only receipt check. No command will be resent and saved safety acknowledgments are unchanged.</p>}
      {busy && <p>Closing this review does not cancel the request. Its receipt remains available to check.</p>}
      {realTest && !uncertain && <fieldset disabled={busy}><legend>Confirm physical checks</legend>{[
        ['props', 'All propellers removed'], ['secured', 'Every airframe secured'], ['area', 'Test area clear'],
      ].map(([key, label]) => <label key={key}><input type="checkbox" checked={Boolean(ack[key])}
        onChange={(event) => setAck({ ...ack, [key]: event.target.checked })} />{label}</label>)}</fieldset>}
      {(!modeKnown || !contextMatches) && <p role="alert">Runtime context unavailable or changed. Close and review again.</p>}
      {error && <p role="alert">{error}</p>}
    </div>} />;
}
