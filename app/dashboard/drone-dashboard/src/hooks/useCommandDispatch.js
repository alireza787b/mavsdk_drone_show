import { useEffect, useRef, useState } from 'react';
import { useCommandActivity } from '../contexts/CommandActivityContext';
import { buildGcsUrl, fetchGcsResource } from '../services/gcsApiService';
import { createCommandIdempotencyKey, isAmbiguousSubmissionTransportFailure, sendDroneCommand,
  serializeCommandSubmission } from '../services/droneApiService';
import { trackCommandReceipt } from '../utilities/commandLifecycleFeedback';

const resolved = new Set();
const resolvedKey = (store, command) => `${store}:${command.idempotency_key}`;
function read(store) {
  try {
    const raw = sessionStorage.getItem(store);
    const saved = raw ? JSON.parse(raw) : {};
    if (!saved || typeof saved !== 'object' || Array.isArray(saved)) throw new Error('Invalid command journal');
    const pending = {};
    Object.entries(saved).forEach(([action, request]) => {
      const command = request?.command;
      if (!command?.idempotency_key || !Array.isArray(command.target_drone_ids) || !command.target_drone_ids.length
        || command.target_scope || !Number.isInteger(command.mission_type)) throw new Error('Invalid command journal');
      if (!resolved.has(resolvedKey(store, command))) pending[action] = request;
    });
    return { pending, error: '' };
  } catch (_) { return { pending: {}, error: 'Saved command recovery data is unavailable. Restore session storage before sending.' }; }
}
function forget(store, action, command) {
  resolved.add(resolvedKey(store, command));
  if (resolved.size > 128) resolved.delete(resolved.values().next().value);
  // A storage cleanup error cannot undo an authoritative receipt/rejection.
  try {
    const next = read(store).pending;
    delete next[action];
    sessionStorage.setItem(store, JSON.stringify(next));
  } catch (_) { /* Read-only lookup remains safe after a later reload. */ }
}

// One transaction boundary for mission workspaces and immediate aircraft moves.
// Recovery is GET-only and explicit; reconnect/re-render never executes commands.
export default function useCommandDispatch(namespace, runtimeMode, operatorId = '') {
  const { commandLifecycleCallbacks } = useCommandActivity();
  const store = `mds.command-intents.v1:${buildGcsUrl('/api/v1/commands')}:${runtimeMode}:${operatorId}:${namespace}`;
  const scope = useRef({ store, epoch: 0 });
  if (scope.current.store !== store) scope.current = { store, epoch: scope.current.epoch + 1 };
  const epoch = scope.current.epoch;
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [, refresh] = useState(0);
  const [status, setStatus] = useState({ epoch, busy: false, error: '' });
  const inFlight = useRef(false);
  const journal = read(store);
  const isCurrent = () => mounted.current && scope.current.store === store && scope.current.epoch === epoch;
  const update = next => { if (isCurrent()) setStatus({ epoch, ...next }); };
  const run = async (action, command, recovering) => {
    if (!isCurrent() || inFlight.current || !['real', 'sitl'].includes(runtimeMode)) return false;
    const saved = read(store);
    if (saved.error) { update({ busy: false, error: saved.error }); return false; }
    if (!recovering && saved.pending[action]) {
      update({ busy: false, error: 'Check the saved receipt before sending another command.' }); return false;
    }
    inFlight.current = true;
    update({ busy: true, error: '' });
    let request = saved.pending[action];
    let posted = false;
    let accepted = false;
    try {
      let receipt;
      if (recovering) {
        if (!request) throw new Error('No saved request to recover.');
        const response = await fetchGcsResource('/api/v1/commands/lookup', {
          params: { idempotency_key: request.command.idempotency_key },
        });
        receipt = response.data;
      } else {
        const snapshot = JSON.parse(JSON.stringify(command));
        if (!snapshot || !Array.isArray(snapshot.target_drone_ids) || !snapshot.target_drone_ids.length
          || snapshot.target_drone_ids.some(id => typeof id !== 'string' || !id.trim() || id !== id.trim())
          || new Set(snapshot.target_drone_ids).size !== snapshot.target_drone_ids.length
          || Object.prototype.hasOwnProperty.call(snapshot, 'target_scope')) throw new Error('Review exact aircraft before sending.');
        request = { command: serializeCommandSubmission({ ...snapshot,
          idempotency_key: snapshot.idempotency_key || createCommandIdempotencyKey() }) };
        const serialized = JSON.stringify({ ...saved.pending, [action]: request });
        try {
          sessionStorage.setItem(store, serialized);
          if (sessionStorage.getItem(store) !== serialized) throw new Error('Recovery identity was not saved');
        } catch (_) { throw new Error('Command not sent: this browser cannot save its recovery identity.'); }
        if (isCurrent()) refresh(value => value + 1);
        posted = true;
        receipt = await sendDroneCommand(request.command, { recoverAmbiguousSubmission: false });
      }
      if (receipt?.accepted_for_tracking !== true || !receipt.command_id) {
        throw Object.assign(new Error('Receipt unconfirmed'), { code: 'COMMAND_RECEIPT_UNCONFIRMED' });
      }
      accepted = true;
      forget(store, action, request.command);
      if (isCurrent()) {
        const callbacks = Object.fromEntries(Object.entries(commandLifecycleCallbacks || {}).map(([key, callback]) =>
          [key, (...args) => { if (isCurrent()) callback(...args); }]));
        trackCommandReceipt(request.command, receipt, callbacks);
        refresh(value => value + 1);
      }
      return isCurrent();
    } catch (exc) {
      if (accepted) {
        update({ busy: false, error: 'Command accepted. Check command history for live tracking.' });
        return isCurrent();
      }
      if (request && !recovering && (!posted || !isAmbiguousSubmissionTransportFailure(exc))) forget(store, action, request.command);
      update({ busy: false, error: exc.response?.status === 404
        ? 'Receipt not found. No command was resent. Check aircraft and command history; the original request remains saved.'
        : typeof exc.response?.data?.detail === 'string' ? exc.response.data.detail
          : exc.message || 'Receipt unconfirmed. Check command status.' });
      return false;
    } finally {
      inFlight.current = false;
      if (isCurrent()) {
        setStatus(previous => ({ ...previous, busy: false }));
        refresh(value => value + 1);
      }
    }
  };
  return {
    pending: journal.pending,
    busy: status.epoch === epoch && status.busy,
    error: journal.error || (status.epoch === epoch ? status.error : ''),
    enabled: ['real', 'sitl'].includes(runtimeMode) && !journal.error,
    clearError: () => update({ busy: false, error: '' }),
    submit: (action, command) => run(action, command, false),
    recover: action => run(action, null, true),
  };
}
